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


def _collect_batch_failures(sent: list, returned: list, op: str) -> list:
    """Per-item errors from a ``/products/batch`` response.

    WooCommerce returns HTTP 200 for the batch even when individual items are
    rejected (e.g. a duplicate SKU): each reject comes back as
    ``{"error": {"code", "message"}}`` with no ``id``, in request order. Without
    this the caller counts the reject as "created" and logs a false success while
    no ``ProductMapping`` is saved. Correlate by position to recover the SKU (the
    error item itself may omit it). Only the SKU + Woo error code/message are
    kept — product data, no PII.
    """
    failures = []
    for sent_item, got in zip(sent, returned):
        if got.get("id"):
            continue
        err = got.get("error") or {}
        failures.append(
            {
                "sku": sent_item.get("sku") or got.get("sku", ""),
                "op": op,
                "code": err.get("code", ""),
                "message": err.get("message", ""),
            }
        )
    return failures


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
    failures: list = []
    variations = {}
    try:
        for index, chunk in enumerate(_chunked(work, limit)):
            if index and throttle:
                time.sleep(throttle)
            c = [x for kind, x in chunk if kind == "create"]
            u = [x for kind, x in chunk if kind == "update"]
            d = [x for kind, x in chunk if kind == "delete"]
            resp = client.batch_products(create=c, update=u, delete=d)
            resp_create = resp.get("create") or []
            resp_update = resp.get("update") or []
            _save_mappings(site, resp_create + resp_update)
            # Woo's batch returns HTTP 200 even when items fail, so count only
            # the items that actually got an id (a mapping) and collect the
            # rejects — otherwise a duplicate-SKU reject reads as a false success.
            created += sum(1 for it in resp_create if it.get("id"))
            updated += sum(1 for it in resp_update if it.get("id"))
            deleted += len(resp.get("delete") or [])
            failures += _collect_batch_failures(c, resp_create, "create")
            failures += _collect_batch_failures(u, resp_update, "update")

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

    # Per-item Woo rejects → not a clean success: PARTIAL if anything landed,
    # ERROR if the whole batch was rejected. ``failed`` lists the rejected SKUs
    # + Woo's error code so the cause (e.g. duplicate SKU) is visible.
    if failures:
        status = (
            SyncLog.Status.PARTIAL if (created or updated or deleted) else SyncLog.Status.ERROR
        )
    else:
        status = SyncLog.Status.SUCCESS
    SyncLog.objects.create(
        site=site,
        operation=OPERATION,
        status=status,
        created_count=created,
        updated_count=updated,
        deleted_count=deleted,
        detail={
            "planned": total,
            "variations": variations,
            "grouped_unresolved": grouped_unresolved,
            "failed": failures,
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

    # Single-pass: build lookup maps for the bulk upsert below.
    name_by_woo_id: dict = {}   # woo_id → normalized name
    slug_by_name: dict = {}     # name → slug
    parent_id_by_name: dict = {}  # name → parent woo_id (0 = root)
    for c in cats:
        name = normalize_category_name(c.get("name", ""))
        woo_id = c.get("id")
        if not name or not woo_id:
            continue
        name_by_woo_id[woo_id] = name
        slug_by_name[name] = c.get("slug", "") or ""
        parent_id_by_name[name] = c.get("parent") or 0

    if not name_by_woo_id:
        SyncLog.objects.create(
            site=site,
            operation=CATEGORY_OPERATION,
            status=SyncLog.Status.SUCCESS,
            detail={"pulled": 0},
        )
        return {"site_id": site.id, "pulled": 0, "error": None}

    # dict.fromkeys preserves insertion order and removes duplicate names.
    unique_names = dict.fromkeys(name_by_woo_id.values())
    now = timezone.now()

    from django.db import transaction

    with transaction.atomic():
        # ON CONFLICT (name) DO UPDATE — atomic at the DB level, race-safe
        # when multiple threads pull the same category name from different sites.
        Category.objects.bulk_create(
            [
                Category(name=name, slug=slug_by_name.get(name, ""))
                for name in unique_names
            ],
            update_conflicts=True,
            update_fields=["slug"],
            unique_fields=["name"],
        )
        categories_by_name = {
            c.name: c
            for c in Category.objects.filter(name__in=unique_names)
        }

        # Rebuild the category TREE for this site: resolve each category's woo
        # parent id → parent name → parent Category, then set the self-FK. The
        # parent always belongs to the same site's pull, so it is present in
        # categories_by_name. Cha–con là **last-pull-wins** (xem Category model):
        # ta chỉ đụng các category của site này, ghi đè parent kể cả về None khi
        # site này coi nó là gốc. Bỏ qua self-parent (woo đôi khi trả về chính nó).
        tree_updates = []
        for name, cat in categories_by_name.items():
            parent_name = name_by_woo_id.get(parent_id_by_name.get(name, 0), "")
            parent_cat = categories_by_name.get(parent_name) if parent_name else None
            new_parent_id = parent_cat.id if (parent_cat and parent_cat.id != cat.id) else None
            if cat.parent_id != new_parent_id:
                cat.parent_id = new_parent_id
                tree_updates.append(cat)
        if tree_updates:
            Category.objects.bulk_update(tree_updates, ["parent"])
        # One site can expose several WooCommerce categories whose names
        # normalize to the same Hub Category (case/whitespace, or genuine
        # duplicates). They all collapse to one (category, site) row, so an
        # upsert keyed only on (site, woo_category_id) treats the extras as new
        # inserts and trips ``catmap_unique_category_site``. Collapse to one woo
        # id per category first (smallest id wins — deterministic across
        # re-pulls), then replace the site's mappings wholesale so BOTH unique
        # constraints hold without an ambiguous ON CONFLICT.
        woo_id_by_category: dict = {}
        for woo_id, name in name_by_woo_id.items():
            category = categories_by_name.get(name)
            if category is None:
                continue
            existing = woo_id_by_category.get(category.id)
            if existing is None or woo_id < existing:
                woo_id_by_category[category.id] = woo_id

        CategoryMapping.objects.filter(site=site).delete()
        CategoryMapping.objects.bulk_create(
            [
                CategoryMapping(
                    site=site,
                    category_id=category_id,
                    woo_category_id=woo_id,
                    last_synced_at=now,
                )
                for category_id, woo_id in woo_id_by_category.items()
            ]
        )

    pulled = len(name_by_woo_id)
    SyncLog.objects.create(
        site=site,
        operation=CATEGORY_OPERATION,
        status=SyncLog.Status.SUCCESS,
        detail={"pulled": pulled, "mapped": len(woo_id_by_category)},
    )
    return {"site_id": site.id, "pulled": pulled, "error": None}
