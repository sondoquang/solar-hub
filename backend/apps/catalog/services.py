"""Service layer for the catalog app: view/task → service → model/WooClient.

Owns SKU normalization, the WooCommerce product payload, the per-site push (the
core of the "Sync all"), and the list/stats queries for the API. All WooCommerce
traffic goes through ``WooClient`` (built by ``apps.sites.services.client_for_site``).
"""

import logging
import re
import time

import httpx
from django.conf import settings
from django.db.models import Count, Exists, OuterRef
from django.utils import timezone

from apps.sync.models import SyncLog

from .models import (
    Category,
    CategoryMapping,
    MasterProduct,
    ProductMapping,
    ProductVariationMapping,
)

logger = logging.getLogger(__name__)

OPERATION = "push_products"
CATEGORY_OPERATION = "pull_categories"

_WS = re.compile(r"\s+")


def _item_limit() -> int:
    """Max items (create+update+delete) per batch request (settings, ~100)."""
    return max(1, getattr(settings, "PRODUCT_BATCH_ITEM_LIMIT", 100))


def _throttle_seconds() -> float:
    """Delay between batch chunks to one site (settings, default 0.5s)."""
    return max(0.0, getattr(settings, "PRODUCT_PUSH_THROTTLE_SECONDS", 0.5))


def normalize_sku(value: str) -> str:
    """Normalize a SKU before storing/matching: trim, collapse whitespace, upper.

    SKU is the cross-site matching key (PROJECT_RULE §SKU); normalizing keeps
    ``" sp-1 "`` and ``"SP-1"`` from becoming two different products.
    """
    return _WS.sub(" ", (value or "").strip()).upper()


def normalize_category_name(value: str) -> str:
    """Normalize a category name before storing/matching: trim + collapse ws.

    Unlike ``normalize_sku`` the case is preserved (categories are display
    strings), so ``" Pin  mặt trời "`` and ``"Pin mặt trời"`` converge but
    ``"Pin"`` and ``"PIN"`` stay distinct.
    """
    return _WS.sub(" ", (value or "").strip())


def _category_refs(names, category_id_by_name: dict) -> list[dict]:
    """Map category names to Woo refs: ``{"id": woo_id}`` when the name is mapped
    on this site, else ``{"name": name}`` so Woo creates it (the next category
    pull then captures its id)."""
    refs = []
    for name in names or []:
        woo_id = category_id_by_name.get(normalize_category_name(name))
        refs.append({"id": woo_id} if woo_id else {"name": name})
    return refs


def _attribute_refs(attributes) -> list[dict]:
    """Map stored attribute dicts to Woo's product-attribute shape."""
    return [
        {
            "name": a.get("name", ""),
            "options": a.get("options", []),
            "variation": bool(a.get("variation")),
            "visible": bool(a.get("visible", True)),
        }
        for a in attributes or []
    ]


def build_product_payload(
    master: MasterProduct,
    *,
    category_id_by_name: dict | None = None,
    grouped_ids: list[int] | None = None,
) -> dict:
    """Map a ``MasterProduct`` to a WooCommerce product payload.

    Prices/weight are sent as strings (Woo's API expects strings). Categories
    resolve to ``{"id"}`` when mapped on the site (via ``category_id_by_name``),
    else ``{"name"}`` so Woo creates them; images as ``[{"src"}]``. Branches on
    ``type``: ``external`` adds the affiliate link, ``grouped`` the resolved child
    ids, ``variable`` the attribute definitions (variations are pushed separately,
    not in this payload). Kept site-agnostic via the injected maps so it can be
    unit-tested without a DB.
    """
    category_id_by_name = category_id_by_name or {}
    payload = {
        "name": master.name,
        "sku": master.sku,
        "type": master.type,
        "description": master.description,
        "short_description": master.short_description,
        "regular_price": str(master.regular_price),
        "status": master.status,
        "stock_status": master.stock_status,
        "categories": _category_refs(master.categories, category_id_by_name),
        "images": [{"src": url} for url in (master.images or [])],
    }
    if master.sale_price is not None:
        payload["sale_price"] = str(master.sale_price)
    if master.weight is not None:
        payload["weight"] = str(master.weight)

    if master.type == MasterProduct.Type.EXTERNAL:
        payload["external_url"] = master.external_url
        payload["button_text"] = master.button_text
    elif master.type == MasterProduct.Type.GROUPED:
        payload["grouped_products"] = grouped_ids or []
    elif master.type == MasterProduct.Type.VARIABLE:
        payload["attributes"] = _attribute_refs(master.attributes)
    return payload


def build_variation_payload(variation: dict) -> dict:
    """Map a stored variation dict to a WooCommerce variation payload.

    Variation attributes are a list of ``{"name", "option"}`` (one option per
    attribute, unlike the parent's ``options`` list). Prices/weight as strings.
    """
    payload = {
        "sku": normalize_sku(variation.get("sku", "")),
        "regular_price": (
            str(variation["regular_price"]) if variation.get("regular_price") is not None else ""
        ),
        "stock_status": variation.get("stock_status") or "instock",
        "attributes": [
            {"name": name, "option": option}
            for name, option in (variation.get("attributes") or {}).items()
        ],
    }
    if variation.get("sale_price") is not None:
        payload["sale_price"] = str(variation["sale_price"])
    if variation.get("weight") is not None:
        payload["weight"] = str(variation["weight"])
    if variation.get("image"):
        payload["image"] = {"src": variation["image"]}
    return payload


def _chunked(items: list, size: int):
    """Yield ``items`` in chunks of at most ``size`` (size >= 1)."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _category_id_map(site) -> dict:
    """``{normalized_category_name: woo_category_id}`` for one site (one query).

    Built once per ``push_products_to_site`` and threaded into every
    ``build_product_payload`` so each product references the site's own category
    ids (RIÊNG per site) instead of re-creating categories by name every push.
    """
    return {
        normalize_category_name(cm.category.name): cm.woo_category_id
        for cm in CategoryMapping.objects.filter(site=site).select_related("category")
    }


def _resolve_grouped_ids(site, master: MasterProduct) -> tuple[list, list]:
    """Resolve a grouped product's child SKUs to this site's ``woo_product_id``s.

    Returns ``(ids, missing_skus)``. A child is resolvable only once it is mapped
    on the site (a prior push), so on the first run children may be ``missing``;
    they self-heal on the next sync once their own create has mapped them.
    """
    skus = [normalize_sku(s) for s in (master.grouped_skus or [])]
    children = list(MasterProduct.objects.filter(sku__in=skus))
    child_by_sku = {c.sku: c for c in children}
    id_by_master = {
        pm.master_id: pm.woo_product_id
        for pm in ProductMapping.objects.filter(site=site, master__in=children)
    }
    ids, missing = [], []
    for sku in skus:
        child = child_by_sku.get(sku)
        woo_id = id_by_master.get(child.id) if child else None
        if woo_id:
            ids.append(woo_id)
        else:
            missing.append(sku)
    return ids, missing


def _plan_site_push(site, masters, category_id_by_name) -> tuple[list, list, list, dict]:
    """Split masters into Woo create/update/delete work for one site.

    Uses the site's existing ``ProductMapping`` rows: unmapped & live → create;
    mapped & live → update (keyed by ``woo_product_id``); mapped & soft-deleted →
    delete. Unmapped & deleted products are skipped (nothing to remove remotely).
    Grouped products are ordered last (leaf-first) so their children tend to be
    mapped before they are referenced; unresolved children are returned in
    ``grouped_unresolved`` ({sku: [missing_child_sku, ...]}) for the SyncLog.
    """
    mapping_by_master = {
        m.master_id: m for m in ProductMapping.objects.filter(site=site, master__in=masters)
    }
    ordered = sorted(masters, key=lambda m: m.type == MasterProduct.Type.GROUPED)
    create, update, delete = [], [], []
    grouped_unresolved: dict = {}
    for master in ordered:
        mapping = mapping_by_master.get(master.id)
        if master.is_deleted:
            if mapping:
                delete.append(mapping.woo_product_id)
            continue
        grouped_ids = None
        if master.type == MasterProduct.Type.GROUPED:
            grouped_ids, missing = _resolve_grouped_ids(site, master)
            if missing:
                grouped_unresolved[master.sku] = missing
        payload = build_product_payload(
            master,
            category_id_by_name=category_id_by_name,
            grouped_ids=grouped_ids,
        )
        if mapping:
            update.append({"id": mapping.woo_product_id, **payload})
        else:
            create.append(payload)
    return create, update, delete, grouped_unresolved


def _save_mappings(site, returned_items: list[dict]) -> None:
    """Upsert ``ProductMapping`` from a batch response (matched by SKU).

    Idempotent on ``(master, site)``: a re-push updates the existing row instead
    of creating a duplicate. Items without a resolvable id/sku (Woo per-item
    errors) are skipped — they stay unmapped and are retried next run.
    """
    skus = [normalize_sku(it.get("sku", "")) for it in returned_items if it.get("sku")]
    masters_by_sku = {m.sku: m for m in MasterProduct.objects.filter(sku__in=skus)}
    now = timezone.now()
    for item in returned_items:
        woo_id = item.get("id")
        master = masters_by_sku.get(normalize_sku(item.get("sku", "")))
        if not woo_id or master is None:
            continue
        ProductMapping.objects.update_or_create(
            master=master,
            site=site,
            defaults={"woo_product_id": woo_id, "last_synced_at": now},
        )


def _save_variation_mappings(site, master, parent_id, returned_items) -> None:
    """Upsert ``ProductVariationMapping`` from a variations-batch response.

    Matched by ``woo_variation_id`` (unique per site); idempotent on
    ``(master, site, variation_sku)``. Items without a resolvable id/sku are
    skipped (retried next run).
    """
    now = timezone.now()
    for item in returned_items:
        woo_id = item.get("id")
        sku = normalize_sku(item.get("sku", ""))
        if not woo_id or not sku:
            continue
        ProductVariationMapping.objects.update_or_create(
            site=site,
            woo_variation_id=woo_id,
            defaults={
                "master": master,
                "variation_sku": sku,
                "woo_parent_id": parent_id,
                "last_synced_at": now,
            },
        )


def _push_variations(site, client, masters) -> dict:
    """Push variations for variable masters; runs after the parent batch.

    Each variable master must already have a ``ProductMapping`` on the site (its
    parent woo id), so this is called only after ``_save_mappings``. For each
    master: diff ``master.variations`` against ``ProductVariationMapping`` by
    ``variation_sku`` → create / update / delete, chunked + throttled like the
    parent push, then upsert the returned ids and drop deleted var-mappings.
    Returns ``{"created", "updated", "deleted"}`` for the SyncLog detail.
    """
    limit = _item_limit()
    throttle = _throttle_seconds()
    created = updated = deleted = 0
    parent_by_master = {
        pm.master_id: pm.woo_product_id
        for pm in ProductMapping.objects.filter(site=site, master__in=masters)
    }
    for master in masters:
        parent_id = parent_by_master.get(master.id)
        if not parent_id:
            continue  # parent create failed/unmapped → variations wait for next run
        existing = {
            vm.variation_sku: vm
            for vm in ProductVariationMapping.objects.filter(site=site, master=master)
        }
        desired = {
            normalize_sku(v.get("sku", "")): v for v in (master.variations or []) if v.get("sku")
        }
        create_v, update_v, delete_v = [], [], []
        for sku, variation in desired.items():
            payload = build_variation_payload(variation)
            if sku in existing:
                update_v.append({"id": existing[sku].woo_variation_id, **payload})
            else:
                create_v.append(payload)
        for sku, vm in existing.items():
            if sku not in desired:
                delete_v.append(vm.woo_variation_id)

        work = (
            [("create", x) for x in create_v]
            + [("update", x) for x in update_v]
            + [("delete", x) for x in delete_v]
        )
        if not work:
            continue
        for index, chunk in enumerate(_chunked(work, limit)):
            if index and throttle:
                time.sleep(throttle)
            c = [x for kind, x in chunk if kind == "create"]
            u = [x for kind, x in chunk if kind == "update"]
            d = [x for kind, x in chunk if kind == "delete"]
            resp = client.batch_variations(parent_id, create=c, update=u, delete=d)
            _save_variation_mappings(
                site,
                master,
                parent_id,
                (resp.get("create") or []) + (resp.get("update") or []),
            )
            created += len(resp.get("create") or [])
            updated += len(resp.get("update") or [])
            deleted += len(resp.get("delete") or [])
        if delete_v:
            ProductVariationMapping.objects.filter(
                site=site, master=master, woo_variation_id__in=delete_v
            ).delete()
    return {"created": created, "updated": updated, "deleted": deleted}


def push_products_to_site(site, *, masters=None) -> dict:
    """Push products to one WooCommerce site; the core of the "Sync all".

    Plans create/update/delete from the site's mappings, sends them in batches of
    at most ``PRODUCT_BATCH_ITEM_LIMIT`` (throttled between chunks), then saves the
    returned ``woo_product_id`` back onto ``ProductMapping`` and drops mappings for
    deleted products. Network errors are caught and returned (never raised) so one
    bad site does not abort the fan-out; a ``SyncLog`` row records the outcome.
    Logs by ``site_id`` only — never the payload (PII/secrets stay out of logs).
    """
    from apps.sites.services import client_for_site

    if masters is None:
        masters = list(MasterProduct.objects.all())
    else:
        masters = list(masters)

    category_id_by_name = _category_id_map(site)
    create, update, delete, grouped_unresolved = _plan_site_push(site, masters, category_id_by_name)
    total = len(create) + len(update) + len(delete)
    if total == 0:
        return {
            "site_id": site.id,
            "created": 0,
            "updated": 0,
            "deleted": 0,
            "error": None,
        }

    client = client_for_site(site)
    limit = _item_limit()
    throttle = _throttle_seconds()

    # One flat work list so a chunk never exceeds the item cap regardless of how
    # create/update/delete are distributed.
    work = (
        [("create", x) for x in create]
        + [("update", x) for x in update]
        + [("delete", x) for x in delete]
    )

    created = updated = deleted = 0
    variations = {}
    try:
        for index, chunk in enumerate(_chunked(work, limit)):
            if index and throttle:
                time.sleep(throttle)
            c = [x for kind, x in chunk if kind == "create"]
            u = [x for kind, x in chunk if kind == "update"]
            d = [x for kind, x in chunk if kind == "delete"]
            resp = client.batch_products(create=c, update=u, delete=d)
            _save_mappings(site, (resp.get("create") or []) + (resp.get("update") or []))
            created += len(resp.get("create") or [])
            updated += len(resp.get("update") or [])
            deleted += len(resp.get("delete") or [])

        # Variations ride on the parent push (parent ids now mapped above).
        variable_masters = [
            m for m in masters if m.type == MasterProduct.Type.VARIABLE and not m.is_deleted
        ]
        if variable_masters:
            variations = _push_variations(site, client, variable_masters)
    except httpx.HTTPError as exc:
        logger.error("push_products failed site_id=%s: %s", site.id, exc.__class__.__name__)
        SyncLog.objects.create(
            site=site,
            operation=OPERATION,
            status=SyncLog.Status.ERROR,
            created_count=created,
            updated_count=updated,
            deleted_count=deleted,
            error=exc.__class__.__name__,
            detail={"planned": total},
        )
        return {
            "site_id": site.id,
            "created": created,
            "updated": updated,
            "deleted": deleted,
            "error": exc.__class__.__name__,
        }

    # Deletes succeeded → drop those mappings so the next plan does not re-delete.
    if delete:
        ProductVariationMapping.objects.filter(site=site, woo_parent_id__in=delete).delete()
        ProductMapping.objects.filter(site=site, woo_product_id__in=delete).delete()

    SyncLog.objects.create(
        site=site,
        operation=OPERATION,
        status=SyncLog.Status.SUCCESS,
        created_count=created,
        updated_count=updated,
        deleted_count=deleted,
        detail={
            "planned": total,
            "variations": variations,
            "grouped_unresolved": grouped_unresolved,
        },
    )
    return {
        "site_id": site.id,
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "error": None,
    }


# --- Querying / aggregation (API) --------------------------------------------


def list_products_qs(qs, params):
    """Apply the list-screen filters (status / stock_status)."""
    status = params.get("status")
    if status:
        qs = qs.filter(status=status)
    stock = params.get("stock_status")
    if stock:
        qs = qs.filter(stock_status=stock)
    return qs


def product_stats(qs) -> dict:
    """Counts for the filtered range (cards), independent of paging.

    ``mapped`` = products with at least one ``ProductMapping`` (pushed to some
    site); ``unmapped`` = never pushed anywhere.
    """
    mapped_expr = Exists(ProductMapping.objects.filter(master=OuterRef("pk")))
    total = qs.count()
    mapped = qs.filter(mapped_expr).count()
    by_status = {
        row["status"]: row["n"] for row in qs.order_by().values("status").annotate(n=Count("id"))
    }
    return {
        "total": total,
        "mapped": mapped,
        "unmapped": total - mapped,
        "by_status": by_status,
    }


def product_sync_status(master: MasterProduct) -> list[dict]:
    """For one product, list every active site annotated with its sync state.

    Powers the per-product "đã đồng bộ domain nào / chưa" panel: ``synced`` is
    True when a ``ProductMapping`` exists for that site, with the ``last_synced_at``
    timestamp and the site's ``woo_product_id``.
    """
    from apps.sites.models import Site

    mapping_by_site = {m.site_id: m for m in master.mappings.all()}
    rows = []
    for site in Site.objects.filter(is_deleted=False).order_by("name"):
        mapping = mapping_by_site.get(site.id)
        rows.append(
            {
                "site_id": site.id,
                "site_name": site.name,
                "synced": mapping is not None,
                "woo_product_id": mapping.woo_product_id if mapping else None,
                "last_synced_at": mapping.last_synced_at if mapping else None,
            }
        )
    return rows


# --- Category pull (two-way sync: pull existing categories from each site) ----


def pull_categories_for_site(site) -> dict:
    """Pull one site's product categories into the Hub catalog.

    Mirrors ``apps.orders.services.poll_site``: builds the client, fetches every
    category page, upserts ``Category`` (by normalized name — equivalent names
    across sites converge to one row) and ``CategoryMapping`` (by
    ``(site, woo_category_id)``). Network errors are caught and returned (never
    raised) so one bad site does not abort the fan-out; a ``SyncLog`` row records
    the outcome. Logs by ``site_id`` only.
    """
    from apps.sites.services import client_for_site

    try:
        cats = client_for_site(site).list_categories()
    except httpx.HTTPError as exc:
        logger.error("pull_categories failed site_id=%s: %s", site.id, exc.__class__.__name__)
        SyncLog.objects.create(
            site=site,
            operation=CATEGORY_OPERATION,
            status=SyncLog.Status.ERROR,
            error=exc.__class__.__name__,
            detail={},
        )
        return {"site_id": site.id, "pulled": 0, "error": exc.__class__.__name__}

    name_by_id = {c.get("id"): normalize_category_name(c.get("name", "")) for c in cats}
    now = timezone.now()
    pulled = 0
    for c in cats:
        name = normalize_category_name(c.get("name", ""))
        woo_id = c.get("id")
        if not name or not woo_id:
            continue
        parent_id = c.get("parent") or 0
        category, _ = Category.objects.update_or_create(
            name=name,
            defaults={
                "slug": c.get("slug", "") or "",
                "parent_name": name_by_id.get(parent_id, "") if parent_id else "",
            },
        )
        CategoryMapping.objects.update_or_create(
            site=site,
            woo_category_id=woo_id,
            defaults={"category": category, "last_synced_at": now},
        )
        pulled += 1

    SyncLog.objects.create(
        site=site,
        operation=CATEGORY_OPERATION,
        status=SyncLog.Status.SUCCESS,
        detail={"pulled": pulled},
    )
    return {"site_id": site.id, "pulled": pulled, "error": None}
