"""Service layer for the catalog app: view/task → service → model/WooClient.

Owns SKU normalization, the WooCommerce product payload, the per-site push (the
core of the "Sync all"), and the list/stats queries for the API. All WooCommerce
traffic goes through ``WooClient`` (built by ``apps.sites.services.client_for_site``).
"""

import logging
import re
import time
import unicodedata
from decimal import Decimal, InvalidOperation

import httpx
from django.conf import settings
from django.db.models import Count, Exists, OuterRef, Q
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
IMPORT_OPERATION = "import_products"

_WS = re.compile(r"\s+")

# v1 imports only "simple" products as ready-to-sync masters. variable/grouped/
# external are reported as skipped (not imported): pushing a half-defined master
# of those types would degrade the site product (empty attributes / unsupported
# type), so they are handled manually for now — see import_products_from_site.
_IMPORTABLE_TYPES = {MasterProduct.Type.SIMPLE}


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


def _fold_diacritics(value: str) -> str:
    """Strip Vietnamese diacritics so accented/unaccented names converge.

    ``đ``/``Đ`` decompose to nothing under NFD, so they are mapped to ``d``
    explicitly before dropping the remaining combining marks.
    """
    value = value.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", value) if not unicodedata.combining(c))


def normalize_match_name(value: str) -> str:
    """Normalize a product name for the cross-site *name* matching key.

    Unlike ``normalize_sku`` (upper) and ``normalize_category_name`` (case kept),
    this is for adoption: trim + collapse whitespace + lowercase, and — unless
    ``settings.PRODUCT_MATCH_FOLD_DIACRITICS`` is False — fold Vietnamese
    diacritics so ``"Tấm pin Mặt Trời"`` matches a site product named
    ``"tam pin mat troi"``. Diacritic folding is a flag because it can merge
    genuinely different names that differ only by accent; turning it off makes
    matching stricter without a code change.
    """
    out = _WS.sub(" ", (value or "").strip()).lower()
    if getattr(settings, "PRODUCT_MATCH_FOLD_DIACRITICS", True):
        out = _fold_diacritics(out)
    return out


def _category_refs(names, category_id_by_name: dict) -> list[dict]:
    """Map category names to Woo refs: ``{"id": woo_id}`` when the name is mapped
    on this site, else ``{"name": name}``.

    Woo's REST products endpoint only honours ``id`` refs — a name-only ref is
    silently IGNORED (it does NOT create the category; only the CSV importer
    does). The push therefore pre-creates unmapped categories on the site
    (``_ensure_site_categories``) before payloads are built; a name-only ref
    survives here only when that create failed, and the gap is reported in the
    SyncLog instead of silently dropping the category."""
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
    else ``{"name"}`` — which Woo ignores, so the push creates missing
    categories on the site first (see ``_ensure_site_categories``); images as
    ``[{"src"}]``. Branches on
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
    # Always send these (empty string clears the value in Woo); omitting them
    # would leave a stale sale_price/weight on the site after an update.
    payload["sale_price"] = "" if master.sale_price is None else str(master.sale_price)
    payload["weight"] = "" if master.weight is None else str(master.weight)

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
    # Always send these (empty string clears the value in Woo) so removing a
    # sale price/weight on the master propagates to already-synced variations.
    payload["sale_price"] = (
        "" if variation.get("sale_price") is None else str(variation["sale_price"])
    )
    payload["weight"] = "" if variation.get("weight") is None else str(variation["weight"])
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


def _save_category_mapping(site, category, woo_id, woo_name, now) -> None:
    """Upsert one ``CategoryMapping`` from a push-side create/link.

    Idempotent on ``(category, site)``. If another Hub category already claims
    this ``woo_category_id`` on the site, the existing row is left alone — the
    id is still used for this run's payloads, and the next category pull
    reconciles the rows wholesale.
    """
    if (
        CategoryMapping.objects.filter(site=site, woo_category_id=woo_id)
        .exclude(category=category)
        .exists()
    ):
        return
    CategoryMapping.objects.update_or_create(
        category=category,
        site=site,
        defaults={
            "woo_category_id": woo_id,
            "woo_name": (woo_name or "")[:255],
            "last_synced_at": now,
        },
    )


def _ensure_site_categories(site, client, masters, category_id_by_name: dict) -> dict:
    """Create on the site every category a live master references that has no
    ``CategoryMapping`` yet — BEFORE product payloads are built.

    Woo's REST products endpoint only honours ``{"id"}`` category refs;
    ``{"name"}`` refs are silently ignored (no auto-create). Without this step a
    product assigned an unmapped category keeps its OLD categories on the site
    while the batch still reports success. Unmapped Hub ancestors are created
    too, parents first in waves, so the site's tree matches the Hub's; a
    ``term_exists`` reject means the site already has the term (never pulled) —
    its ``error.data.resource_id`` is mapped instead of creating a duplicate.

    Mutates ``category_id_by_name`` in place with the new ids, persists the
    ``CategoryMapping`` rows, and returns a report for the SyncLog:
    ``{"created": [names], "linked": [names], "failed": [{name, code,
    message}]}``. Network errors propagate to the caller (logged per-site
    there, like the product batch itself).
    """
    report: dict = {"created": [], "linked": [], "failed": []}
    missing: list[str] = []
    for master in masters:
        if master.is_deleted:
            continue
        for raw in master.categories or []:
            name = normalize_category_name(raw)
            if name and name not in category_id_by_name and name not in missing:
                missing.append(name)
    if not missing:
        return report

    # Hub rows for the missing names (a product can carry a hand-typed name no
    # pull has seen yet), plus any unmapped ancestors so a child is created
    # under the right parent instead of as a root.
    pending: dict = {}
    for name in missing:
        category, _ = Category.objects.get_or_create(name=name)
        pending[name] = category
    queue = list(pending.values())
    while queue:
        parent = queue.pop().parent
        if (
            parent is not None
            and not parent.is_deleted
            and parent.name not in pending
            and parent.name not in category_id_by_name
        ):
            pending[parent.name] = parent
            queue.append(parent)

    limit = _item_limit()
    throttle = _throttle_seconds()
    now = timezone.now()
    call_index = 0
    while pending:
        # One wave = everything whose parent is already resolvable. A parent
        # whose own create failed has left ``pending``, so its children are
        # then created as roots (better than not existing at all; the next
        # pull restores the tree once someone fixes the site).
        wave = [c for c in pending.values() if c.parent is None or c.parent.name not in pending]
        if not wave:  # defensive: a parent cycle would spin forever
            report["failed"] += [
                {"name": name, "code": "hub_parent_cycle", "message": ""} for name in pending
            ]
            break
        for chunk in _chunked(wave, limit):
            if call_index and throttle:
                time.sleep(throttle)
            call_index += 1
            sent = []
            for category in chunk:
                item = {"name": category.name}
                parent_woo_id = category.parent and category_id_by_name.get(category.parent.name)
                if parent_woo_id:
                    item["parent"] = parent_woo_id
                sent.append(item)
            resp = client.batch_categories(create=sent)
            for category, got in zip(chunk, resp.get("create") or [], strict=False):
                err = got.get("error") or {}
                woo_id = None
                if got.get("id") and not err:
                    woo_id = got["id"]
                    report["created"].append(category.name)
                elif err.get("code") == "term_exists" and (err.get("data") or {}).get(
                    "resource_id"
                ):
                    woo_id = err["data"]["resource_id"]
                    report["linked"].append(category.name)
                else:
                    report["failed"].append(
                        {
                            "name": category.name,
                            "code": err.get("code", ""),
                            "message": err.get("message", ""),
                        }
                    )
                if woo_id:
                    category_id_by_name[category.name] = woo_id
                    _save_category_mapping(
                        site, category, woo_id, got.get("name") or category.name, now
                    )
        for category in wave:
            pending.pop(category.name, None)
    return report


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


def _adopt_by_name(site, client, masters) -> dict:
    """Bootstrap ``ProductMapping`` by NAME for masters not yet mapped on a site.

    The sites are not unified on SKU/id, so a product imported into the Hub may
    already exist on a target site under a (possibly hand-typed) name. Before the
    push plans a CREATE for an unmapped master, this lists the site's products,
    indexes them by normalized name, and on a UNIQUE match against the master's
    frozen ``match_name`` (falling back to ``name``) creates the mapping — so the
    master falls into ``_plan_site_push``'s UPDATE branch instead of duplicating
    the product. The match runs ONCE per ``(master, site)``: the moment a mapping
    exists it is never re-run, so a rename on the Hub afterwards never breaks the
    link, and stable runs that have nothing to adopt never even call the API
    (the candidate list is empty → early return).

    Ambiguous matches (two site products share the normalized name) are NOT
    adopted AND NOT created — adopting either could clobber the wrong product and
    creating would duplicate. Their master ids are returned so the caller drops
    them from this run and the SyncLog reports them for a human to resolve.
    Returns ``{"adopted": [sku], "ambiguous": [sku], "ambiguous_master_ids": set}``.
    """
    report: dict = {"adopted": [], "ambiguous": [], "ambiguous_master_ids": set()}
    mapped_ids = set(
        ProductMapping.objects.filter(site=site, master__in=masters).values_list(
            "master_id", flat=True
        )
    )
    candidates = [m for m in masters if not m.is_deleted and m.id not in mapped_ids]
    if not candidates:
        return report

    index: dict = {}
    for p in client.list_products():
        woo_id = p.get("id")
        if not woo_id:
            continue
        index.setdefault(normalize_match_name(p.get("name", "")), []).append(woo_id)

    # Woo ids already owned by a mapping on this site must never be adopted again
    # (the ``(site, woo_product_id)`` unique constraint; another master owns it).
    claimed = set(
        ProductMapping.objects.filter(site=site).values_list("woo_product_id", flat=True)
    )
    for master in candidates:
        key = normalize_match_name(master.match_name or master.name)
        if not key:
            continue
        ids = [i for i in index.get(key, []) if i not in claimed]
        if len(ids) == 1:
            ProductMapping.objects.update_or_create(
                master=master,
                site=site,
                defaults={"woo_product_id": ids[0], "last_synced_at": None},
            )
            claimed.add(ids[0])
            report["adopted"].append(master.sku)
        elif len(ids) > 1:
            report["ambiguous"].append(master.sku)
            report["ambiguous_master_ids"].add(master.id)
    return report


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
    ``{"error": {"code", "message"}}``, in request order. Create rejects carry
    no ``id``; **update/delete rejects DO echo the requested ``id``** (e.g.
    ``woocommerce_rest_product_invalid_id`` when the product was deleted on the
    site outside the Hub) — so the success test is "id and no error", never
    just "has id". Correlate by position to recover the SKU (the error item
    itself may omit it). Only the SKU + Woo error code/message are kept —
    product data, no PII.
    """
    failures = []
    for sent_item, got in zip(sent, returned, strict=False):
        if got.get("id") and not got.get("error"):
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


def push_products_to_site(site, *, masters=None, run_id=None, triggered_by_id=None) -> dict:
    """Push products to one WooCommerce site; the core of the "Sync all".

    First ensures every referenced category exists on the site
    (``_ensure_site_categories`` — Woo ignores name-only category refs, so an
    unmapped category would otherwise silently never change on the site). Then
    plans create/update/delete from the site's mappings, sends them in batches of
    at most ``PRODUCT_BATCH_ITEM_LIMIT`` (throttled between chunks), then saves the
    returned ``woo_product_id`` back onto ``ProductMapping`` and drops mappings for
    deleted products. Network errors are caught and returned (never raised) so one
    bad site does not abort the fan-out; a ``SyncLog`` row records the outcome.
    Logs by ``site_id`` only — never the payload (PII/secrets stay out of logs).

    ``run_id``/``triggered_by_id`` (set by the "Đồng bộ ngay" view) are stamped
    onto every ``SyncLog`` row this call writes so the progress banner can group
    the run and poll completion; ``started`` is captured up front so
    ``created_at - started_at`` is this site's push duration. When ``run_id`` is
    set, even the no-op (nothing to push) case writes a SUCCESS row so every
    targeted site reports and the banner's ``done`` count reaches ``expected``.
    """
    from apps.sites.models import Site
    from apps.sites.services import client_for_site

    started = timezone.now()
    # Stamped onto every SyncLog this call writes (any branch) so the run report
    # and progress banner have the who/duration regardless of outcome.
    audit = {"run_id": run_id, "triggered_by_id": triggered_by_id, "started_at": started}

    if masters is None:
        masters = list(MasterProduct.objects.all())
    else:
        masters = list(masters)

    client = client_for_site(site)
    category_id_by_name = _category_id_map(site)
    try:
        category_report = _ensure_site_categories(site, client, masters, category_id_by_name)
    except httpx.HTTPError as exc:
        logger.error(
            "push_products ensure_categories failed site_id=%s: %s",
            site.id,
            exc.__class__.__name__,
        )
        SyncLog.objects.create(
            site=site,
            operation=OPERATION,
            status=SyncLog.Status.ERROR,
            error=exc.__class__.__name__,
            detail={"stage": "ensure_categories", **_site_snapshot(site)},
            **audit,
        )
        return {
            "site_id": site.id,
            "created": 0,
            "updated": 0,
            "deleted": 0,
            "error": exc.__class__.__name__,
        }

    # Adopt existing site products by name BEFORE planning, so a matched master
    # becomes an update (not a duplicate create). Wrapped like ensure_categories:
    # a network failure here aborts only this site (the fan-out continues).
    # v1: name adoption runs for WooCommerce only — Sapo (shared-DB, different
    # field model) is handled separately later, and its push keeps the existing
    # SKU/mapping behaviour (no extra list_products call per store).
    adopt_report = {"adopted": [], "ambiguous": [], "ambiguous_master_ids": set()}
    if site.platform == Site.Platform.WOOCOMMERCE:
        try:
            adopt_report = _adopt_by_name(site, client, masters)
        except httpx.HTTPError as exc:
            logger.error(
                "push_products adopt_by_name failed site_id=%s: %s",
                site.id,
                exc.__class__.__name__,
            )
            SyncLog.objects.create(
                site=site,
                operation=OPERATION,
                status=SyncLog.Status.ERROR,
                error=exc.__class__.__name__,
                detail={"stage": "adopt_products", **_site_snapshot(site)},
                **audit,
            )
            return {
                "site_id": site.id,
                "created": 0,
                "updated": 0,
                "deleted": 0,
                "error": exc.__class__.__name__,
            }

    # Ambiguous masters are neither adopted nor created this run — drop them so
    # _plan_site_push does not queue a duplicate create.
    plan_masters = (
        [m for m in masters if m.id not in adopt_report["ambiguous_master_ids"]]
        if adopt_report["ambiguous_master_ids"]
        else masters
    )
    # Surfaced in every SyncLog this call writes (the set is not JSON-serializable).
    adopt_detail = {
        "adopted": adopt_report["adopted"],
        "adopted_count": len(adopt_report["adopted"]),
        "ambiguous": adopt_report["ambiguous"],
    }

    create, update, delete, grouped_unresolved = _plan_site_push(
        site, plan_masters, category_id_by_name
    )
    total = len(create) + len(update) + len(delete)
    if total == 0:
        # Nothing to push (site already in sync). A periodic/admin push logs
        # nothing here, but a tracked run must record this site so the progress
        # banner sees it finish — write a no-op row only when grouped. Ambiguous
        # matches mean some products were deliberately left untouched, so flag
        # PARTIAL (not a clean SUCCESS) so the report nudges a human to resolve.
        if run_id:
            SyncLog.objects.create(
                site=site,
                operation=OPERATION,
                status=(
                    SyncLog.Status.PARTIAL
                    if adopt_report["ambiguous"]
                    else SyncLog.Status.SUCCESS
                ),
                detail={
                    "planned": 0,
                    "categories": category_report,
                    **adopt_detail,
                    **_site_snapshot(site),
                },
                **audit,
            )
        return {
            "site_id": site.id,
            "created": 0,
            "updated": 0,
            "deleted": 0,
            "error": None,
        }

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
    # Updates rejected because the woo id no longer exists (product deleted on
    # the site outside the Hub, e.g. via wp-admin): the mapping is stale. Heal
    # in this same run — drop the mapping and re-push the item as a create.
    stale_creates: list = []
    stale_woo_ids: list = []
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
            # Woo's batch returns HTTP 200 even when items fail (and update
            # rejects still echo the requested id), so success = id AND no
            # per-item error — otherwise a reject reads as a false success.
            created += sum(1 for it in resp_create if it.get("id") and not it.get("error"))
            updated += sum(1 for it in resp_update if it.get("id") and not it.get("error"))
            deleted += sum(1 for it in (resp.get("delete") or []) if not it.get("error"))
            failures += _collect_batch_failures(c, resp_create, "create")
            for sent_item, got in zip(u, resp_update, strict=False):
                if (got.get("error") or {}).get("code") == "woocommerce_rest_product_invalid_id":
                    stale_woo_ids.append(sent_item["id"])
                    stale_creates.append({k: v for k, v in sent_item.items() if k != "id"})
            # Stale-id updates are retried below as creates — only the other
            # update rejects are real failures.
            failures += [
                f
                for f in _collect_batch_failures(u, resp_update, "update")
                if f["code"] != "woocommerce_rest_product_invalid_id"
            ]

        if stale_creates:
            logger.warning(
                "push_products site_id=%s: %s stale mapping(s), re-creating",
                site.id,
                len(stale_creates),
            )
            ProductVariationMapping.objects.filter(
                site=site, woo_parent_id__in=stale_woo_ids
            ).delete()
            ProductMapping.objects.filter(site=site, woo_product_id__in=stale_woo_ids).delete()
            for chunk in _chunked(stale_creates, limit):
                if throttle:
                    time.sleep(throttle)
                resp = client.batch_products(create=chunk)
                resp_create = resp.get("create") or []
                _save_mappings(site, resp_create)
                created += sum(1 for it in resp_create if it.get("id") and not it.get("error"))
                failures += _collect_batch_failures(chunk, resp_create, "create")

        # Variations ride on the parent push (parent ids now mapped above —
        # including parents just re-created from stale mappings).
        variable_masters = [
            m for m in plan_masters if m.type == MasterProduct.Type.VARIABLE and not m.is_deleted
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
            detail={
                "planned": total,
                "categories": category_report,
                **adopt_detail,
                **_site_snapshot(site),
            },
            **audit,
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
        status = SyncLog.Status.PARTIAL if (created or updated or deleted) else SyncLog.Status.ERROR
    elif category_report["failed"] or adopt_report["ambiguous"]:
        # Products landed but the run is not clean: either a category could not be
        # created (its name-only ref is ignored by Woo) or some products matched
        # more than one site product by name and were left untouched — both are
        # flagged PARTIAL so the report surfaces the gap.
        status = SyncLog.Status.PARTIAL
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
            # Categories created/linked on the site before this push (Woo
            # ignores name-only refs, so unmapped ones must be created first).
            "categories": category_report,
            # Products re-created because their mapping pointed at a woo id
            # that no longer exists (deleted on the site outside the Hub).
            "recreated_stale": len(stale_creates),
            **adopt_detail,
            **_site_snapshot(site),
        },
        **audit,
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
    timestamp and the site's ``woo_product_id``. ``site_status`` (up/down/unknown),
    ``site_url`` and ``is_primary`` let the panel filter (status / domain search /
    trang chính) before pushing.
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
                "site_url": site.base_url,
                "site_status": site.status,
                "platform": site.platform,
                "is_primary": site.is_primary,
                "synced": mapping is not None,
                "woo_product_id": mapping.woo_product_id if mapping else None,
                "last_synced_at": mapping.last_synced_at if mapping else None,
            }
        )
    return rows


# --- Category pull (two-way sync: pull existing categories from each site) ----


def _site_snapshot(site) -> dict:
    """SyncLog.detail keys naming the site at pull time, so the category-run
    report survives a later site delete (``SyncLog.site`` is SET_NULL)."""
    hosting = site.hosting
    return {
        "site_name": site.name,
        "site_url": site.base_url,
        "hosting": (hosting.provider or hosting.name) if hosting else "",
    }


def _category_snapshot(raw_name_by_woo_id, name_by_woo_id, categories_by_name) -> list[dict]:
    """One ``detail["categories"]`` entry per Woo category pulled: the raw Woo
    name plus the Hub ``Category`` it converged to. Duplicates that collapse
    onto one Hub category each keep their own entry — the report's point is
    "what does the site have, and where did each land"."""
    snapshot = []
    for woo_id, name in name_by_woo_id.items():
        cat = categories_by_name.get(name)
        if cat is None:
            continue
        snapshot.append(
            {
                "woo_id": woo_id,
                "woo_name": raw_name_by_woo_id.get(woo_id, ""),
                "hub_id": cat.id,
                "hub_name": cat.name,
            }
        )
    return snapshot


_MAPPING_ORDERINGS = {"woo_category_id", "woo_name", "category__name", "last_synced_at"}


def list_category_mappings_qs(site_id: int, params):
    """Queryset cho màn "site này có categories nào → map về Hub category nào".

    Search khớp tên trên site (raw), tên Hub, hoặc đúng woo_category_id khi
    nhập số. Ordering chỉ nhận field trong whitelist; tie-break theo ``id`` để
    pagination ổn định.
    """
    qs = CategoryMapping.objects.filter(site_id=site_id, category__is_deleted=False).select_related(
        "category", "category__parent"
    )
    search = (params.get("search") or "").strip()
    if search:
        q = Q(woo_name__icontains=search) | Q(category__name__icontains=search)
        if search.isdigit():
            q |= Q(woo_category_id=int(search))
        qs = qs.filter(q)
    ordering = params.get("ordering") or "category__name"
    if ordering.lstrip("-") not in _MAPPING_ORDERINGS:
        ordering = "category__name"
    return qs.order_by(ordering, "id")


# --- Category overview / matrix (the "Danh mục" dashboard tabs) ---------------


def category_overview() -> dict:
    """Counts for the Tổng quan + Cây danh mục Hub stat cards.

    ``hub_used`` = live (non-deleted) Hub categories; ``hub_total`` includes the
    soft-deleted ones. ``linked`` = live categories present on ≥1 (live) site;
    the tree cards split live categories into root/child and report the
    soft-deleted count. Mirrors ``product_stats`` (Exists subquery, one query
    each — independent of any paging).
    """
    from apps.sites.models import Site

    live = Category.objects.filter(is_deleted=False)
    linked_expr = Exists(
        CategoryMapping.objects.filter(category=OuterRef("pk"), site__is_deleted=False)
    )
    hub_used = live.count()
    linked = live.filter(linked_expr).count()
    return {
        "hub_used": hub_used,
        "hub_total": Category.objects.count(),
        "linked": linked,
        "unlinked": hub_used - linked,
        "linked_pct": round(linked / hub_used * 100, 1) if hub_used else 0.0,
        "site_count": Site.objects.filter(is_deleted=False).count(),
        "root_count": live.filter(parent__isnull=True).count(),
        "child_count": live.filter(parent__isnull=False).count(),
        "deleted_count": Category.objects.filter(is_deleted=True).count(),
    }


def active_sites_columns() -> list[dict]:
    """Column headers for the cross-site matrix: every live site, trang chính
    first then by name (the order the matrix renders its per-site columns)."""
    from apps.sites.models import Site

    return list(
        Site.objects.filter(is_deleted=False)
        .order_by("-is_primary", "name")
        .values("id", "name", "base_url", "platform")
    )


_MATRIX_ORDERINGS = {"name", "linked_site_count"}


def category_matrix_qs(params):
    """Queryset for the cross-site matrix: one row per live Hub category, with
    its live-site mappings prefetched (the serializer pivots them into per-site
    cells) and ``linked_site_count`` annotated for sort/display.

    Search matches the Hub name or its parent's name; ordering is whitelisted to
    ``name``/``linked_site_count`` with an ``id`` tie-break for stable paging.
    """
    qs = (
        Category.objects.filter(is_deleted=False)
        .select_related("parent")
        .prefetch_related("mappings__site")
        .annotate(
            linked_site_count=Count(
                "mappings",
                filter=Q(mappings__site__is_deleted=False),
                distinct=True,
            )
        )
    )
    search = (params.get("search") or "").strip()
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(parent__name__icontains=search))
    ordering = params.get("ordering") or "name"
    if ordering.lstrip("-") not in _MATRIX_ORDERINGS:
        ordering = "name"
    return qs.order_by(ordering, "id")


def category_site_links(category) -> list[dict]:
    """For one Hub category, every live site annotated with its link state.

    Powers the tree-tab detail panel ("Liên kết với website"): ``linked`` is True
    when a ``CategoryMapping`` exists for that site, carrying the per-site
    ``woo_category_id`` + raw ``woo_name`` + ``last_synced_at``. Mirrors
    ``product_sync_status``; trang chính first then by name.
    """
    from apps.sites.models import Site

    mapping_by_site = {m.site_id: m for m in category.mappings.all()}
    rows = []
    for site in Site.objects.filter(is_deleted=False).order_by("-is_primary", "name"):
        mapping = mapping_by_site.get(site.id)
        rows.append(
            {
                "site_id": site.id,
                "site_name": site.name,
                "site_url": site.base_url,
                "site_status": site.status,
                "platform": site.platform,
                "is_primary": site.is_primary,
                "linked": mapping is not None,
                "woo_category_id": mapping.woo_category_id if mapping else None,
                "woo_name": mapping.woo_name if mapping else "",
                "last_synced_at": mapping.last_synced_at if mapping else None,
            }
        )
    return rows


def clear_category_sync_data() -> dict:
    """Global reset of the category catalog so it can be re-pulled from scratch.

    Soft-deletes the Hub ``Category`` rows and clears their per-site
    ``CategoryMapping`` + the ``pull_categories`` history, EXCEPT categories a
    live product still references by name (and their ancestors, so the kept tree
    stays connected). After this the user re-pulls — primary sites first — to
    make their tree the canonical base; ``pull_categories_for_site`` revives a
    soft-deleted Category by name (see its bulk_create ``update_fields``).

    Soft-delete (``is_deleted=True``) keeps everything recoverable; the kept
    categories' mappings are left intact (a re-pull rebuilds them wholesale per
    site anyway). Returns the counts for the UI toast.
    """
    from django.db import transaction

    # 1. Categories a live product references (matched by normalized name, the
    #    same key the catalog stores). One pass over live products' name lists.
    used_names: set[str] = set()
    for names in MasterProduct.objects.filter(is_deleted=False).values_list(
        "categories", flat=True
    ):
        for name in names or []:
            used_names.add(normalize_category_name(name))

    # 2. Protect the in-use categories AND their ancestors so the kept tree does
    #    not lose a parent. Walk parents in Python over a {id: parent_id} map.
    live = list(Category.objects.filter(is_deleted=False).values("id", "name", "parent_id"))
    parent_by_id = {row["id"]: row["parent_id"] for row in live}
    protected_ids: set[int] = set()
    for row in live:
        if row["name"] not in used_names:
            continue
        node = row["id"]
        while node is not None and node not in protected_ids:
            protected_ids.add(node)
            node = parent_by_id.get(node)

    cleared_ids = [row["id"] for row in live if row["id"] not in protected_ids]

    with transaction.atomic():
        # 3. Soft-delete every live category not protected.
        categories_cleared = (
            Category.objects.filter(id__in=cleared_ids, is_deleted=False).update(
                is_deleted=True
            )
        )
        # 4. Drop the cleared categories' mappings (no soft-delete flag on the
        #    mapping; a re-pull rebuilds mappings wholesale per site). Kept
        #    categories keep their mappings.
        mappings_cleared, _ = CategoryMapping.objects.filter(
            category_id__in=cleared_ids
        ).delete()
        # 5. Soft-delete the category pull history so the report starts fresh.
        history_cleared = SyncLog.objects.filter(
            operation=CATEGORY_OPERATION, is_deleted=False
        ).update(is_deleted=True)

    return {
        "categories_cleared": categories_cleared,
        "categories_kept": len(protected_ids),
        "mappings_cleared": mappings_cleared,
        "history_cleared": history_cleared,
    }


def pull_categories_for_site(site, run_id=None, triggered_by_id=None) -> dict:
    """Pull one site's product categories into the Hub catalog.

    Mirrors ``apps.orders.services.poll_site``: builds the client, fetches every
    category page, upserts ``Category`` (by normalized name — equivalent names
    across sites converge to one row) and ``CategoryMapping`` (by
    ``(site, woo_category_id)``). Network errors are caught and returned (never
    raised) so one bad site does not abort the fan-out; a ``SyncLog`` row records
    the outcome — stamped with ``run_id`` and carrying the site + per-category
    snapshot in ``detail`` so the run is reportable later. ``triggered_by_id`` is
    the admin who clicked sync (threaded from the view), ``started`` is captured
    up front so ``created_at - started_at`` is this site's pull duration. Logs by
    ``site_id`` only.
    """
    from apps.sites.services import client_for_site

    started = timezone.now()
    # Stamped onto every SyncLog this call writes (any branch) so the report has
    # the who/duration regardless of outcome.
    audit = {"run_id": run_id, "triggered_by_id": triggered_by_id, "started_at": started}

    try:
        cats = client_for_site(site).list_categories()
    except httpx.HTTPError as exc:
        logger.error("pull_categories failed site_id=%s: %s", site.id, exc.__class__.__name__)
        SyncLog.objects.create(
            site=site,
            operation=CATEGORY_OPERATION,
            status=SyncLog.Status.ERROR,
            error=exc.__class__.__name__,
            detail=_site_snapshot(site),
            **audit,
        )
        return {"site_id": site.id, "pulled": 0, "error": exc.__class__.__name__}

    # Single-pass: build lookup maps for the bulk upsert below.
    name_by_woo_id: dict = {}  # woo_id → normalized name
    raw_name_by_woo_id: dict = {}  # woo_id → raw Woo name (report snapshot)
    slug_by_name: dict = {}  # name → slug
    parent_id_by_name: dict = {}  # name → parent woo_id (0 = root)
    for c in cats:
        name = normalize_category_name(c.get("name", ""))
        woo_id = c.get("id")
        if not name or not woo_id:
            continue
        name_by_woo_id[woo_id] = name
        raw_name_by_woo_id[woo_id] = c.get("name", "")
        slug_by_name[name] = c.get("slug", "") or ""
        parent_id_by_name[name] = c.get("parent") or 0

    if not name_by_woo_id:
        SyncLog.objects.create(
            site=site,
            operation=CATEGORY_OPERATION,
            status=SyncLog.Status.SUCCESS,
            detail={"pulled": 0, **_site_snapshot(site)},
            **audit,
        )
        return {"site_id": site.id, "pulled": 0, "error": None}

    # dict.fromkeys preserves insertion order and removes duplicate names.
    unique_names = dict.fromkeys(name_by_woo_id.values())
    now = timezone.now()

    from django.db import transaction

    with transaction.atomic():
        # ON CONFLICT (name) DO UPDATE — atomic at the DB level, race-safe
        # when multiple threads pull the same category name from different sites.
        # update_fields includes is_deleted so a re-pull REVIVES a category that
        # was soft-deleted by "clear category sync data" — the Category() default
        # is_deleted=False overwrites the stale True on conflict. Without this the
        # reset-then-pull workflow would leave the category hidden forever.
        Category.objects.bulk_create(
            [Category(name=name, slug=slug_by_name.get(name, "")) for name in unique_names],
            update_conflicts=True,
            update_fields=["slug", "is_deleted"],
            unique_fields=["name"],
        )
        categories_by_name = {c.name: c for c in Category.objects.filter(name__in=unique_names)}

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
                    woo_name=raw_name_by_woo_id.get(woo_id, "")[:255],
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
        detail={
            "pulled": pulled,
            "mapped": len(woo_id_by_category),
            **_site_snapshot(site),
            "categories": _category_snapshot(
                raw_name_by_woo_id, name_by_woo_id, categories_by_name
            ),
        },
        **audit,
    )
    return {"site_id": site.id, "pulled": pulled, "error": None}


def _to_decimal(value):
    """Parse a Woo price/weight (string, '' = unset) into Decimal or None."""
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _master_fields_from_remote(item: dict, sku: str, site, now) -> dict:
    """Map a remote (Woo-shaped) product dict to ``MasterProduct`` kwargs.

    Defensive about missing fields: WooCommerce's product list carries the full
    object, but Sapo's slim list only has name/sku/type — the rest fall back to
    sensible defaults. ``match_name`` freezes the import-time name as the
    name-match key; ``source_site``/``imported_at`` are audit only.
    """
    name = (item.get("name") or "").strip()
    status = item.get("status")
    if status not in MasterProduct.Status.values:
        status = MasterProduct.Status.DRAFT
    stock = item.get("stock_status")
    if stock not in MasterProduct.StockStatus.values:
        stock = MasterProduct.StockStatus.INSTOCK
    regular = _to_decimal(item.get("regular_price"))
    images = [
        img["src"]
        for img in (item.get("images") or [])
        if isinstance(img, dict) and img.get("src")
    ]
    categories = [
        c["name"]
        for c in (item.get("categories") or [])
        if isinstance(c, dict) and c.get("name")
    ]
    return {
        "sku": sku,
        "name": name,
        "match_name": normalize_match_name(name),
        "type": MasterProduct.Type.SIMPLE,
        "description": item.get("description") or "",
        "short_description": item.get("short_description") or "",
        "regular_price": regular if regular is not None else Decimal("0"),
        "sale_price": _to_decimal(item.get("sale_price")),
        "status": status,
        "stock_status": stock,
        "weight": _to_decimal(item.get("weight")),
        "images": images,
        "categories": categories,
        "source_site": site,
        "imported_at": now,
    }


def import_products_from_site(site, *, run_id=None, triggered_by_id=None) -> dict:
    """Import one site's products into the Hub catalog (the "lấy data chuẩn từ
    website chính về" bootstrap).

    Mirrors ``pull_categories_for_site``: builds the client, lists every product,
    and for each SIMPLE product either LINKS it to an existing master with the
    same SKU (create the mapping only) or CREATES a new master — freezing the
    site name into ``match_name`` (the name-match key a later push adopts by) and
    stamping ``source_site``/``imported_at``. The new/linked master is mapped to
    the site so a later push UPDATEs it instead of duplicating. ``variable`` /
    ``grouped`` / ``external`` products are NOT imported (v1: pushing a
    half-defined master of those types would degrade the site product) — they are
    counted in ``skipped`` / ``skipped_types`` so the report names what needs
    manual handling. Idempotent: a product already mapped on the site is skipped,
    so re-importing is safe. Network errors are caught and returned (never
    raised); a ``SyncLog`` row records the outcome. Logs by ``site_id`` only.
    """
    from django.db import transaction

    from apps.sites.services import client_for_site

    started = timezone.now()
    audit = {"run_id": run_id, "triggered_by_id": triggered_by_id, "started_at": started}

    try:
        products = client_for_site(site).list_products()
    except httpx.HTTPError as exc:
        logger.error("import_products failed site_id=%s: %s", site.id, exc.__class__.__name__)
        SyncLog.objects.create(
            site=site,
            operation=IMPORT_OPERATION,
            status=SyncLog.Status.ERROR,
            error=exc.__class__.__name__,
            detail=_site_snapshot(site),
            **audit,
        )
        return {"site_id": site.id, "imported": 0, "error": exc.__class__.__name__}

    created = linked = skipped = 0
    skipped_types: dict = {}
    # woo ids already mapped on this site → idempotent skip on re-import.
    mapped_woo_ids = set(
        ProductMapping.objects.filter(site=site).values_list("woo_product_id", flat=True)
    )
    now = timezone.now()
    with transaction.atomic():
        for item in products:
            woo_id = item.get("id")
            if not woo_id:
                continue
            ptype = item.get("type") or MasterProduct.Type.SIMPLE
            if ptype not in _IMPORTABLE_TYPES:
                skipped += 1
                skipped_types[ptype] = skipped_types.get(ptype, 0) + 1
                continue
            if woo_id in mapped_woo_ids:
                skipped += 1
                continue
            sku = normalize_sku(item.get("sku", "")) or f"IMPORT-{site.id}-{woo_id}"
            master = MasterProduct.objects.filter(sku=sku, is_deleted=False).first()
            if master is None:
                master = MasterProduct.objects.create(
                    **_master_fields_from_remote(item, sku, site, now)
                )
                created += 1
            else:
                linked += 1
            ProductMapping.objects.update_or_create(
                master=master,
                site=site,
                defaults={"woo_product_id": woo_id, "last_synced_at": now},
            )
            mapped_woo_ids.add(woo_id)

    SyncLog.objects.create(
        site=site,
        operation=IMPORT_OPERATION,
        status=SyncLog.Status.SUCCESS,
        created_count=created,
        updated_count=linked,
        detail={
            "imported": created + linked,
            "created": created,
            "linked": linked,
            "skipped": skipped,
            "skipped_types": skipped_types,
            **_site_snapshot(site),
        },
        **audit,
    )
    return {
        "site_id": site.id,
        "imported": created + linked,
        "created": created,
        "linked": linked,
        "skipped": skipped,
        "error": None,
    }
