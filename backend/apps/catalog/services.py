"""Service layer for the catalog app: view/task → service → model/WooClient.

Owns SKU normalization, the WooCommerce product payload, the per-site push (the
core of the "Sync all"), and the list/stats queries for the API. All WooCommerce
traffic goes through ``WooClient`` (built by ``apps.sites.services.client_for_site``).
"""

import io
import logging
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation

import httpx
from django.conf import settings
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.sync.models import SyncLog

from .models import (
    Category,
    CategoryMapping,
    MasterProduct,
    ProductAdoptionScan,
    ProductImage,
    ProductMapping,
    ProductVariationMapping,
    SiteMediaAsset,
)

logger = logging.getLogger(__name__)

# Connection-pooled client for import-time image downloads (gallery + images
# embedded in description HTML). Reuses keep-alive connections to the source
# site instead of a fresh TCP+TLS handshake per image — the dominant cost when a
# product carries many images. Follows redirects (image CDNs commonly 301/302).
# Tests monkeypatch ``_fetch_image_bytes`` (or this object's ``get``).
_IMG_POOL = httpx.Client(
    follow_redirects=True,
    limits=httpx.Limits(
        max_connections=getattr(settings, "HTTP_POOL_MAX_CONNECTIONS", 100),
        max_keepalive_connections=getattr(settings, "HTTP_POOL_MAX_KEEPALIVE", 20),
        keepalive_expiry=getattr(settings, "HTTP_POOL_KEEPALIVE_EXPIRY", 30.0),
    ),
)

OPERATION = "push_products"
CATEGORY_OPERATION = "pull_categories"
IMPORT_OPERATION = "import_products"

# WooCommerce per-item batch error codes the push self-heals instead of failing:
#  - stale id: mapping points at a woo id deleted on the site → drop + re-create.
#  - image upload: Woo could not sideload a product image (URL unreachable from the
#    site) and rejects the WHOLE write → retry the write WITHOUT images so price/
#    text/stock still land (the site keeps its existing image; the product is
#    flagged in SyncLog.detail["image_skipped"] so the image can be re-hosted).
_STALE_ID_ERROR = "woocommerce_rest_product_invalid_id"
_IMAGE_UPLOAD_ERROR = "woocommerce_product_image_upload_error"

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


def _sideload_description_enabled() -> bool:
    """Whether the push sideloads Hub images embedded in description HTML."""
    return bool(getattr(settings, "PRODUCT_SIDELOAD_DESCRIPTION_IMAGES", True))


def _internalize_imported_images_enabled() -> bool:
    """Whether import downloads a site's product images into the Hub media library.

    A product imported from one site stores that site's image URLs; pushing it to
    OTHER sites tells them to fetch the files from the source site, which often
    fails (dev sandbox not public, hotlink protection, source down) — Woo then
    rejects the image and the push self-heals by dropping it. Internalizing the
    images on import (download → ProductImage → Hub URL) makes an imported product
    behave like a Hub-created one: every site downloads from the Hub's public host.
    """
    return bool(getattr(settings, "PRODUCT_INTERNALIZE_IMPORTED_IMAGES", True))


# Matches an <img> tag's src attribute (both quote styles); ``src`` group is the
# bare URL between the quotes, so it can be string-replaced verbatim in the HTML.
_IMG_SRC_RE = re.compile(
    r"""<img\b[^>]*?\bsrc\s*=\s*(["'])(?P<src>.*?)\1""", re.IGNORECASE | re.DOTALL
)
# The host-independent Hub-media path inside an src ("/media/..."), used as the
# cache key so a change of the Hub's public host does not invalidate the cache.
_MEDIA_PATH_RE = re.compile(r"(/media/[^\s\"'?#>]+)")


def _media_path(src: str) -> str | None:
    """Return the host-independent ``/media/...`` path of a Hub-media ``src``.

    Both an absolute Hub URL (``https://hub/media/x.png``) and a root-relative
    ``/media/x.png`` reduce to ``/media/x.png``; an src with no ``/media/``
    segment (external/CDN image) returns None and is left untouched by the push.
    """
    if not src:
        return None
    match = _MEDIA_PATH_RE.search(src)
    return match.group(1) if match else None


def _extract_description_media(*html_parts: str) -> dict:
    """Map every Hub-media ``<img src>`` across the given HTML to its media path.

    Returns ``{original_src: media_path}`` — ``original_src`` is the exact URL
    string in the HTML so it can be replaced verbatim; external images (no
    ``/media/``) are skipped. Used to decide which images to sideload and which
    ``src`` to rewrite afterwards.
    """
    found: dict = {}
    for html in html_parts:
        for match in _IMG_SRC_RE.finditer(html or ""):
            src = match.group("src")
            path = _media_path(src)
            if path and src not in found:
                found[src] = path
    return found


def _apply_media_map(html: str, media_map: dict) -> str:
    """Rewrite Hub-media ``src`` in ``html`` to site URLs via ``{path: site_url}``.

    Only images whose path is present in ``media_map`` (already sideloaded to the
    site) are rewritten; the rest are left for a later push to resolve.
    """
    if not html or not media_map:
        return html or ""
    replacements = {
        src: media_map[path]
        for src, path in _extract_description_media(html).items()
        if path in media_map
    }
    if not replacements:
        return html
    for original, site_url in replacements.items():
        html = html.replace(original, site_url)
    return html


def _absolute_media_url(src: str) -> str | None:
    """Absolute, site-downloadable URL for a Hub-media ``src`` (for sideloading).

    An already-absolute ``http(s)`` src is used as-is; a root-relative
    ``/media/...`` src is prefixed with ``MEDIA_PUBLIC_BASE_URL`` so the remote
    site can fetch it. Returns None when it cannot be made absolute (relative src
    with no public base configured) — that image is then skipped, not sideloaded.
    """
    if not src:
        return None
    if src.startswith(("http://", "https://")):
        return src
    base = getattr(settings, "MEDIA_PUBLIC_BASE_URL", "") or ""
    if src.startswith("/") and base:
        return f"{base}{src}"
    return None


def _site_media_map(site) -> dict:
    """``{source_path: site_url}`` of every Hub image already sideloaded to a site."""
    return {a.source_path: a.site_url for a in SiteMediaAsset.objects.filter(site=site)}


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
    media_map: dict | None = None,
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

    ``media_map`` (``{hub_media_path: site_url}``, per site) rewrites Hub images
    embedded in the description HTML to the site's own copy. Only images already
    sideloaded to the site are rewritten here; newly-seen ones are handled after
    the push by ``_sideload_description_images``.
    """
    category_id_by_name = category_id_by_name or {}
    payload = {
        "name": master.name,
        "sku": master.sku,
        "type": master.type,
        "description": _apply_media_map(master.description, media_map or {}),
        "short_description": _apply_media_map(master.short_description, media_map or {}),
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
    the product.

    Listing a site's whole catalog is expensive, so it is done at most ONCE per
    ``(master, site)``: every considered master gets a ``ProductAdoptionScan``
    row (adopted, ambiguous, or no-match), and a later push only calls
    ``list_products`` when at least one candidate has NEVER been scanned here. A
    stable re-push (all masters mapped or already scanned) never touches the API.

    Ambiguous matches (two site products share the normalized name) are NOT
    adopted AND NOT created — adopting either could clobber the wrong product and
    creating would duplicate. Their ambiguity is persisted on the scan row, so
    later pushes keep excluding them from create (via the returned
    ``ambiguous_master_ids``) without re-listing the site, until someone resolves
    the duplicate and clears the scan data. Returns
    ``{"adopted": [sku], "ambiguous": [sku], "ambiguous_master_ids": set}``.
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

    # Outcomes of any prior scan for these candidates on this site.
    prior_scan = {
        row["master_id"]: row["ambiguous"]
        for row in ProductAdoptionScan.objects.filter(
            site=site, master_id__in=[m.id for m in candidates]
        ).values("master_id", "ambiguous")
    }
    # Keep excluding masters flagged ambiguous by a prior scan (never re-create),
    # without re-listing the site — until scan data is cleared for a re-scan.
    for master in candidates:
        if prior_scan.get(master.id):
            report["ambiguous"].append(master.sku)
            report["ambiguous_master_ids"].add(master.id)
    to_scan = [m for m in candidates if m.id not in prior_scan]
    if not to_scan:
        return report  # nothing new to scan → skip the whole-catalog list call

    index: dict = {}
    for p in client.list_products():
        woo_id = p.get("id")
        if not woo_id:
            continue
        index.setdefault(normalize_match_name(p.get("name", "")), []).append(woo_id)

    # Woo ids already owned by a mapping on this site must never be adopted again
    # (the ``(site, woo_product_id)`` unique constraint; another master owns it).
    claimed = set(ProductMapping.objects.filter(site=site).values_list("woo_product_id", flat=True))
    scans: list = []
    for master in to_scan:
        key = normalize_match_name(master.match_name or master.name)
        ambiguous = False
        ids = [i for i in index.get(key, []) if i not in claimed] if key else []
        if len(ids) == 1:
            ProductMapping.objects.update_or_create(
                master=master,
                site=site,
                defaults={"woo_product_id": ids[0], "last_synced_at": None},
            )
            claimed.add(ids[0])
            report["adopted"].append(master.sku)
        elif len(ids) > 1:
            ambiguous = True
            report["ambiguous"].append(master.sku)
            report["ambiguous_master_ids"].add(master.id)
        # Record the scan (adopted / ambiguous / no-match) so it is not re-listed.
        scans.append(ProductAdoptionScan(master=master, site=site, ambiguous=ambiguous))
    ProductAdoptionScan.objects.bulk_create(scans, ignore_conflicts=True)
    return report


def _plan_site_push(
    site, masters, category_id_by_name, media_map=None
) -> tuple[list, list, list, dict]:
    """Split masters into Woo create/update/delete work for one site.

    Uses the site's existing ``ProductMapping`` rows: unmapped & live → create;
    mapped & live → update (keyed by ``woo_product_id``); mapped & soft-deleted →
    delete. Unmapped & deleted products are skipped (nothing to remove remotely).
    Grouped products are ordered last (leaf-first) so their children tend to be
    mapped before they are referenced; unresolved children are returned in
    ``grouped_unresolved`` ({sku: [missing_child_sku, ...]}) for the SyncLog.
    ``media_map`` rewrites already-sideloaded description images (see
    ``build_product_payload``).
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
            media_map=media_map,
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


def _without_images(item: dict) -> dict:
    """A copy of a batch item with the ``images`` key dropped (for image-less retry)."""
    return {k: v for k, v in item.items() if k != "images"}


def _collect_image_ids(into: dict, returned_items: list[dict]) -> None:
    """Record each successful product's current gallery image ids from a batch.

    ``into`` is ``{woo_product_id: [image_id, ...]}`` — fed to the description-
    image sideload so it can keep the existing gallery by id and only append the
    new images. Per-item errors (no id, or an ``error``) are skipped.
    """
    for item in returned_items:
        woo_id = item.get("id")
        if not woo_id or item.get("error"):
            continue
        into[woo_id] = [img.get("id") for img in (item.get("images") or []) if img.get("id")]


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


def _sideload_description_images(site, client, masters, image_ids_by_woo_id, media_map) -> dict:
    """Sideload Hub images embedded in description HTML into the SITE's media.

    Runs AFTER the main product batch (so every live master is mapped). For each
    master whose ``description``/``short_description`` embeds Hub ``/media/``
    images NOT yet in ``media_map``:

      Round 1 — one batch ``update`` sending the product's existing gallery images
        (by ``id``, so Woo keeps them) plus the new Hub images (by ``src``, so Woo
        downloads them into the site's media library). The site URLs Woo returns
        for the appended images are cached in ``SiteMediaAsset`` and added to
        ``media_map``.
      Round 2 — one batch ``update`` restoring the clean gallery (existing ids
        only; the uploaded images stay in the library but leave the product
        gallery) and shipping the description rewritten to the new site URLs.

    A product's existing gallery image ids come from this run's batch response
    (``image_ids_by_woo_id``); for an already-synced product not in the batch
    (nothing planned for it), they are fetched with ``get_product``. Already-
    cached images need no round-trip — ``build_product_payload`` rewrote them in
    the main push. Returns a SyncLog report ``{"uploaded", "products", "skipped",
    "error"}``; network errors are caught and surfaced in ``error`` (the push is
    already done), never raised.

    v1: WooCommerce only. Sapo has no batch image-sideload semantics, so its push
    keeps description images as hot-links until a Sapo-specific pass is added.
    """
    from apps.sites.models import Site

    if not _sideload_description_enabled() or site.platform != Site.Platform.WOOCOMMERCE:
        return {}

    mapping_by_master = {
        pm.master_id: pm.woo_product_id
        for pm in ProductMapping.objects.filter(site=site, master__in=masters)
    }

    # A master is "pending" if its description still embeds a Hub image not yet on
    # this site (not in media_map) — it then needs a round-2 rewrite. ``upload``
    # is the subset of those images THIS master sideloads in round 1; a path
    # shared across products is uploaded once (``claimed``), and every pending
    # master's round-2 rewrite picks it up from the full media_map afterwards.
    pending: list = []
    claimed: set = set()
    skipped = 0
    for master in masters:
        if master.is_deleted:
            continue
        woo_id = mapping_by_master.get(master.id)
        if not woo_id:
            continue
        unresolved = {
            path: src
            for src, path in _extract_description_media(
                master.description, master.short_description
            ).items()
            if path not in media_map
        }
        if not unresolved:
            continue  # all description images already on the site (main push rewrote them)
        upload = []
        for path, src in unresolved.items():
            if path in claimed:
                continue
            fetch_url = _absolute_media_url(src)
            if not fetch_url:
                skipped += 1  # relative src with no public base → cannot sideload
                continue
            claimed.add(path)
            upload.append((path, fetch_url))
        pending.append({"master": master, "woo_id": woo_id, "upload": upload})

    if not pending:
        return {"uploaded": 0, "products": 0, "skipped": skipped}

    limit = _item_limit()
    throttle = _throttle_seconds()
    uploaded = 0
    try:
        # Existing gallery ids: from this run's batch response when available,
        # else a per-product GET (already-synced product, not in the batch).
        for entry in pending:
            ids = image_ids_by_woo_id.get(entry["woo_id"])
            if ids is None:
                product = client.get_product(entry["woo_id"])
                ids = [img.get("id") for img in (product.get("images") or []) if img.get("id")]
            entry["existing_ids"] = list(ids)

        # --- Round 1: append new images by src so Woo downloads them ------------
        uploaders = [e for e in pending if e["upload"]]
        for index, chunk in enumerate(_chunked(uploaders, limit)):
            if index and throttle:
                time.sleep(throttle)
            update = [
                {
                    "id": entry["woo_id"],
                    "images": [{"id": iid} for iid in entry["existing_ids"]]
                    + [{"src": fetch_url} for (_path, fetch_url) in entry["upload"]],
                }
                for entry in chunk
            ]
            resp = client.batch_products(update=update)
            by_id = {it.get("id"): it for it in (resp.get("update") or []) if it.get("id")}
            for entry in chunk:
                got = by_id.get(entry["woo_id"]) or {}
                existing = set(entry["existing_ids"])
                # The appended images are those whose id is NOT a pre-existing
                # gallery id, in response order = the order we sent ``upload``.
                fresh = [img for img in (got.get("images") or []) if img.get("id") not in existing]
                for (path, _fetch), img in zip(entry["upload"], fresh, strict=False):
                    site_url = img.get("src")
                    if not site_url:
                        continue
                    SiteMediaAsset.objects.update_or_create(
                        site=site,
                        source_path=path,
                        defaults={"site_url": site_url, "woo_media_id": img.get("id")},
                    )
                    media_map[path] = site_url
                    uploaded += 1
                # New images we could not match back stay uncached → retried next run.
                skipped += max(0, len(entry["upload"]) - len(fresh))

        # --- Round 2: clean gallery + rewrite description to the site URLs ------
        for index, chunk in enumerate(_chunked(pending, limit)):
            if index and throttle:
                time.sleep(throttle)
            update = [
                {
                    "id": entry["woo_id"],
                    "images": [{"id": iid} for iid in entry["existing_ids"]],
                    "description": _apply_media_map(entry["master"].description, media_map),
                    "short_description": _apply_media_map(
                        entry["master"].short_description, media_map
                    ),
                }
                for entry in chunk
            ]
            client.batch_products(update=update)
    except httpx.HTTPError as exc:
        logger.error(
            "push_products description-image sideload failed site_id=%s: %s",
            site.id,
            exc.__class__.__name__,
        )
        return {
            "uploaded": uploaded,
            "products": len(pending),
            "skipped": skipped,
            "error": exc.__class__.__name__,
        }
    return {"uploaded": uploaded, "products": len(pending), "skipped": skipped}


def _reresolve_stale_products(site, client, stale_items) -> tuple[list, list]:
    """Re-match stale-update items to a still-existing site product before create.

    A mapping's ``woo_product_id`` came back ``woocommerce_rest_product_invalid_id``
    on update, so the mapping was dropped. RE-CREATING blindly duplicates a product
    that in fact still exists on the site under a *different* (or again-valid) id —
    e.g. the product was deleted+re-added on the site (new id) but the Hub's edit
    (rename / new sale price) still targets the old id. To avoid the duplicate,
    list the site ONCE and match each item to a live product:

      1. by normalized **SKU** (unique per site) — survives a rename; then
      2. by the master's frozen **match_name** (import-time name, falling back to
         the current name) — survives an edit when the product carries no SKU.

    A unique, unclaimed match becomes an UPDATE against that id (and is remapped by
    ``_save_mappings``); everything unmatched is a create (the product is genuinely
    gone — the original self-heal). Returns ``(updates, creates)`` where ``updates``
    are ``{"id": found_id, **item}``. A network error listing the site propagates
    to the caller's ``httpx.HTTPError`` handler, like the rest of the push.
    """
    # Map each stale item to its master (by SKU) so the name match can use the
    # frozen match_name — the site product still shows the pre-rename name.
    skus = [normalize_sku(it.get("sku", "")) for it in stale_items if it.get("sku")]
    master_by_sku = {m.sku: m for m in MasterProduct.objects.filter(sku__in=skus)}

    by_sku: dict = {}
    by_name: dict = {}
    for p in client.list_products():
        woo_id = p.get("id")
        if not woo_id:
            continue
        site_sku = normalize_sku(p.get("sku", ""))
        if site_sku:
            by_sku.setdefault(site_sku, []).append(woo_id)
        site_name = normalize_match_name(p.get("name", ""))
        if site_name:
            by_name.setdefault(site_name, []).append(woo_id)

    # Woo ids already owned by a mapping on this site must not be re-adopted (the
    # (site, woo_product_id) unique constraint; another master owns them).
    claimed = set(ProductMapping.objects.filter(site=site).values_list("woo_product_id", flat=True))
    updates, creates = [], []
    for item in stale_items:
        sku = normalize_sku(item.get("sku", ""))
        ids = [i for i in by_sku.get(sku, []) if i not in claimed] if sku else []
        if len(ids) != 1:
            master = master_by_sku.get(sku)
            key = normalize_match_name(
                (master.match_name or master.name) if master else item.get("name", "")
            )
            ids = [i for i in by_name.get(key, []) if i not in claimed] if key else []
        if len(ids) == 1:
            claimed.add(ids[0])
            updates.append({"id": ids[0], **item})
        else:
            creates.append(item)
    return updates, creates


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
    # Hub images already sideloaded to this site: build_product_payload rewrites
    # those description ``src`` in the main push (zero extra calls); newly-seen
    # ones are sideloaded afterwards by _sideload_description_images. Sapo skips
    # this — v1 description-image sideload is WooCommerce only.
    media_map = (
        _site_media_map(site)
        if _sideload_description_enabled() and site.platform == Site.Platform.WOOCOMMERCE
        else {}
    )
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
        site, plan_masters, category_id_by_name, media_map=media_map
    )
    total = len(create) + len(update) + len(delete)
    if total == 0:
        # Nothing to push (site already in sync). A periodic/admin push logs
        # nothing here, but a tracked run must record this site so the progress
        # banner sees it finish — write a no-op row only when grouped. Ambiguous
        # matches mean some products were deliberately left untouched, so flag
        # PARTIAL (not a clean SUCCESS) so the report nudges a human to resolve.
        # Even with nothing to push, an already-synced product may have new Hub
        # images in its description (e.g. the feature was just turned on) — those
        # are still sideloaded (existing gallery ids fetched per product).
        description_images = _sideload_description_images(site, client, plan_masters, {}, media_map)
        if run_id:
            SyncLog.objects.create(
                site=site,
                operation=OPERATION,
                status=(
                    SyncLog.Status.PARTIAL
                    if adopt_report["ambiguous"] or description_images.get("error")
                    else SyncLog.Status.SUCCESS
                ),
                detail={
                    "planned": 0,
                    "categories": category_report,
                    "description_images": description_images,
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
    description_images: dict = {}
    # woo_product_id → its current gallery image ids (from the batch response), so
    # the description-image sideload can keep those images by id and only append
    # the new ones. Saves a GET per product for everything pushed this run.
    image_ids_by_woo_id: dict = {}
    # Updates rejected because the woo id no longer resolves (product deleted or
    # re-added on the site outside the Hub): the mapping is stale. Heal in this
    # same run — drop the mapping, RE-RESOLVE the product on the site by SKU/name
    # (so an edit does not duplicate a product that merely got a new id), and only
    # re-create the ones truly gone. ``stale_reresolved`` counts the re-matched.
    stale_creates: list = []
    stale_woo_ids: list = []
    stale_reresolved = 0
    # Items Woo rejected because it could not sideload a product image: re-pushed
    # WITHOUT images so the rest of the write lands. ``image_skipped`` = their SKUs.
    image_retry: list = []  # [("create"|"update", payload-without-images)]
    image_skipped: list = []
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
            _collect_image_ids(image_ids_by_woo_id, resp_create + resp_update)
            # Woo's batch returns HTTP 200 even when items fail (and update
            # rejects still echo the requested id), so success = id AND no
            # per-item error — otherwise a reject reads as a false success.
            created += sum(1 for it in resp_create if it.get("id") and not it.get("error"))
            updated += sum(1 for it in resp_update if it.get("id") and not it.get("error"))
            deleted += sum(1 for it in (resp.get("delete") or []) if not it.get("error"))
            # Create rejects: an image-upload reject is retried below without
            # images (not a hard failure); the rest are real failures.
            for sent_item, got in zip(c, resp_create, strict=False):
                if (got.get("error") or {}).get("code") == _IMAGE_UPLOAD_ERROR:
                    image_retry.append(("create", _without_images(sent_item)))
                    image_skipped.append(sent_item.get("sku", ""))
            failures += [
                f
                for f in _collect_batch_failures(c, resp_create, "create")
                if f["code"] != _IMAGE_UPLOAD_ERROR
            ]
            # Update rejects: stale-id → re-create; image-upload → re-update
            # without images; the rest are real failures.
            for sent_item, got in zip(u, resp_update, strict=False):
                code = (got.get("error") or {}).get("code")
                if code == _STALE_ID_ERROR:
                    stale_woo_ids.append(sent_item["id"])
                    stale_creates.append({k: v for k, v in sent_item.items() if k != "id"})
                elif code == _IMAGE_UPLOAD_ERROR:
                    image_retry.append(("update", _without_images(sent_item)))
                    image_skipped.append(sent_item.get("sku", ""))
            failures += [
                f
                for f in _collect_batch_failures(u, resp_update, "update")
                if f["code"] not in (_STALE_ID_ERROR, _IMAGE_UPLOAD_ERROR)
            ]

        if image_retry:
            logger.warning(
                "push_products site_id=%s: %s product(s) rejected for image upload, "
                "retrying without images",
                site.id,
                len(image_retry),
            )
            for chunk in _chunked(image_retry, limit):
                if throttle:
                    time.sleep(throttle)
                rc_in = [x for kind, x in chunk if kind == "create"]
                ru_in = [x for kind, x in chunk if kind == "update"]
                resp = client.batch_products(create=rc_in, update=ru_in)
                rc = resp.get("create") or []
                ru = resp.get("update") or []
                _save_mappings(site, rc + ru)
                _collect_image_ids(image_ids_by_woo_id, rc + ru)
                created += sum(1 for it in rc if it.get("id") and not it.get("error"))
                updated += sum(1 for it in ru if it.get("id") and not it.get("error"))
                failures += _collect_batch_failures(rc_in, rc, "create")
                failures += _collect_batch_failures(ru_in, ru, "update")

        if stale_creates:
            logger.warning(
                "push_products site_id=%s: %s stale mapping(s), re-resolving",
                site.id,
                len(stale_creates),
            )
            ProductVariationMapping.objects.filter(
                site=site, woo_parent_id__in=stale_woo_ids
            ).delete()
            ProductMapping.objects.filter(site=site, woo_product_id__in=stale_woo_ids).delete()
            # Re-match to a still-existing site product first (by SKU, then the
            # frozen match_name) so an edit does not duplicate a product that
            # merely got a new id; only the genuinely-gone ones are re-created.
            stale_updates, stale_creates = _reresolve_stale_products(site, client, stale_creates)
            stale_reresolved = len(stale_updates)
            for chunk in _chunked(stale_updates, limit):
                if throttle:
                    time.sleep(throttle)
                resp = client.batch_products(update=chunk)
                resp_update = resp.get("update") or []
                _save_mappings(site, resp_update)
                _collect_image_ids(image_ids_by_woo_id, resp_update)
                updated += sum(1 for it in resp_update if it.get("id") and not it.get("error"))
                failures += _collect_batch_failures(chunk, resp_update, "update")
            for chunk in _chunked(stale_creates, limit):
                if throttle:
                    time.sleep(throttle)
                resp = client.batch_products(create=chunk)
                resp_create = resp.get("create") or []
                _save_mappings(site, resp_create)
                _collect_image_ids(image_ids_by_woo_id, resp_create)
                created += sum(1 for it in resp_create if it.get("id") and not it.get("error"))
                failures += _collect_batch_failures(chunk, resp_create, "create")

        # Variations ride on the parent push (parent ids now mapped above —
        # including parents just re-created from stale mappings).
        variable_masters = [
            m for m in plan_masters if m.type == MasterProduct.Type.VARIABLE and not m.is_deleted
        ]
        if variable_masters:
            variations = _push_variations(site, client, variable_masters)

        # Sideload Hub images embedded in description HTML into the site's media
        # (WooCommerce only) and rewrite the description to the site URLs. Runs
        # last so every live master is mapped; never raises (own error handling).
        description_images = _sideload_description_images(
            site, client, plan_masters, image_ids_by_woo_id, media_map
        )
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
    elif (
        category_report["failed"]
        or adopt_report["ambiguous"]
        or description_images.get("error")
        or image_skipped
    ):
        # Products landed but the run is not clean: a category could not be
        # created (its name-only ref is ignored by Woo), some products matched
        # more than one site product by name and were left untouched, the
        # description-image sideload hit a network error, or a product's image
        # could not be uploaded so it was pushed without its image — all flagged
        # PARTIAL so the report surfaces the gap.
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
            # Hub images embedded in descriptions that were sideloaded into the
            # site's media + the description rewritten (WooCommerce only).
            "description_images": description_images,
            # Products re-created because their mapping pointed at a woo id
            # that no longer exists (deleted on the site outside the Hub).
            "recreated_stale": len(stale_creates),
            # Stale mappings re-matched to a still-existing site product (by SKU
            # or frozen match_name) and UPDATED in place instead of duplicated.
            "stale_reresolved": stale_reresolved,
            # SKUs pushed WITHOUT their image because Woo could not sideload it
            # (URL unreachable from the site) — re-host the image to fix.
            "image_skipped": image_skipped,
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
    for site in Site.objects.filter(is_deleted=False).select_related("hosting").order_by("name"):
        mapping = mapping_by_site.get(site.id)
        hosting = site.hosting
        rows.append(
            {
                "site_id": site.id,
                "site_name": site.name,
                "site_url": site.base_url,
                "site_status": site.status,
                "platform": site.platform,
                "is_primary": site.is_primary,
                # Hosting account the site lives on: many hostings share a name,
                # so the panel filters/labels by account_username (fall back to
                # the hosting name only when the username is blank).
                "hosting_id": site.hosting_id,
                "hosting_username": ((hosting.account_username or hosting.name) if hosting else ""),
                "synced": mapping is not None,
                "woo_product_id": mapping.woo_product_id if mapping else None,
                "last_synced_at": mapping.last_synced_at if mapping else None,
            }
        )
    return rows


# --- Category pull (two-way sync: pull existing categories from each site) ----


def _site_snapshot(site) -> dict:
    """SyncLog.detail keys naming the site at pull time, so the category-/product-run
    report survives a later site delete (``SyncLog.site`` is SET_NULL).

    ``hosting_name``/``hosting_username`` are snapshotted separately (not just the
    combined ``hosting`` label) so the product-sync report can group sites by
    hosting and show the account username even after the site/hosting is gone."""
    hosting = site.hosting
    return {
        "site_name": site.name,
        "site_url": site.base_url,
        "hosting": (hosting.provider or hosting.name) if hosting else "",
        "hosting_name": hosting.name if hosting else "",
        "hosting_username": (hosting.account_username or "") if hosting else "",
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
        categories_cleared = Category.objects.filter(id__in=cleared_ids, is_deleted=False).update(
            is_deleted=True
        )
        # 4. Drop the cleared categories' mappings (no soft-delete flag on the
        #    mapping; a re-pull rebuilds mappings wholesale per site). Kept
        #    categories keep their mappings.
        mappings_cleared, _ = CategoryMapping.objects.filter(category_id__in=cleared_ids).delete()
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


# --- Hub-side category CRUD (the tree management surface) --------------------
# Categories used to enter the Hub only via a pull from the sites
# (``pull_categories_for_site``). These helpers let the Hub be the origin too:
# create/rename/move/soft-delete a category, building the parent–child tree by
# hand (like WooCommerce). A Hub-created category has no ``CategoryMapping`` yet;
# it flows down to a site lazily — ``_ensure_site_categories`` creates the term
# there the first time a product carrying that category name is pushed.


def _would_create_cycle(category_id: int, new_parent_id: int | None) -> bool:
    """True if making ``new_parent_id`` the parent of ``category_id`` would form
    a cycle (i.e. the proposed parent is the category itself or a descendant).

    Walks up the proposed parent's ancestor chain over a single {id: parent_id}
    map of the live tree; a category cannot be nested under its own subtree.
    """
    if new_parent_id is None:
        return False
    parent_by_id = dict(Category.objects.filter(is_deleted=False).values_list("id", "parent_id"))
    node = new_parent_id
    seen: set[int] = set()
    while node is not None and node not in seen:
        if node == category_id:
            return True
        seen.add(node)
        node = parent_by_id.get(node)
    return False


def create_category(name: str, parent=None, slug: str = "") -> Category:
    """Create a Hub category under ``parent`` (null = a root of the tree).

    ``name`` is normalized (``normalize_category_name``) and must be unique among
    LIVE categories. A name that only collides with a SOFT-DELETED row revives
    that row (instead of failing the DB-level UNIQUE, which spans soft-deleted
    rows) — mirroring the revive-by-name in ``pull_categories_for_site``.
    """
    clean = normalize_category_name(name)
    if not clean:
        raise ValidationError({"name": "Tên danh mục không được để trống."})
    if parent is not None and parent.is_deleted:
        raise ValidationError({"parent": "Danh mục cha không hợp lệ."})
    existing = Category.objects.filter(name=clean).first()
    if existing is not None:
        if not existing.is_deleted:
            raise ValidationError({"name": f"Danh mục đã tồn tại: {clean}"})
        existing.is_deleted = False
        existing.slug = slug or existing.slug
        existing.parent = parent
        existing.save(update_fields=["is_deleted", "slug", "parent", "updated_at"])
        return existing
    return Category.objects.create(name=clean, slug=slug, parent=parent)


def update_category(category, changes: dict) -> Category:
    """Apply a partial update to a category (rename / re-slug / move parent).

    Only the keys present in ``changes`` are touched (PATCH semantics). Renames
    re-check uniqueness (a collision with a soft-deleted row is reported rather
    than silently clobbering the UNIQUE); a parent change is guarded against
    cycles by ``_would_create_cycle``.
    """
    update_fields = ["updated_at"]
    if "name" in changes:
        clean = normalize_category_name(changes["name"])
        if not clean:
            raise ValidationError({"name": "Tên danh mục không được để trống."})
        clash = Category.objects.exclude(pk=category.pk).filter(name=clean).first()
        if clash is not None:
            if clash.is_deleted:
                raise ValidationError(
                    {"name": f"Tên trùng danh mục đã xóa: {clean}. Khôi phục hoặc chọn tên khác."}
                )
            raise ValidationError({"name": f"Danh mục đã tồn tại: {clean}"})
        category.name = clean
        update_fields.append("name")
    if "slug" in changes:
        category.slug = changes["slug"] or ""
        update_fields.append("slug")
    if "parent" in changes:
        new_parent = changes["parent"]
        if new_parent is not None:
            if new_parent.is_deleted:
                raise ValidationError({"parent": "Danh mục cha không hợp lệ."})
            if new_parent.id == category.id or _would_create_cycle(category.id, new_parent.id):
                raise ValidationError({"parent": "Không thể đặt danh mục làm con của chính nó."})
        category.parent = new_parent
        update_fields.append("parent")
    category.save(update_fields=update_fields)
    return category


def delete_category(category) -> None:
    """Soft-delete a category, promoting its direct children to its own parent.

    Like WooCommerce, a deleted category's children move UP (to the grandparent,
    or become roots when the deleted node was a root) instead of being orphaned —
    the FE tree drops any node whose parent is soft-deleted, so the children must
    be reparented to stay visible. Category has no ``deleted_at`` field (only the
    ``is_deleted`` flag, same as ``clear_category_sync_data``).
    """
    from django.db import transaction

    with transaction.atomic():
        Category.objects.filter(parent=category, is_deleted=False).update(parent=category.parent)
        category.is_deleted = True
        category.save(update_fields=["is_deleted", "updated_at"])


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
        img["src"] for img in (item.get("images") or []) if isinstance(img, dict) and img.get("src")
    ]
    categories = [
        c["name"] for c in (item.get("categories") or []) if isinstance(c, dict) and c.get("name")
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


# Extension to use when a downloaded image's URL carries no usable suffix.
_CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def _is_hub_media_url(url: str) -> bool:
    """True if ``url`` already points at THIS Hub's media (so import must not
    re-download it). Matches a root-relative ``/media/...`` or an absolute URL
    under ``MEDIA_PUBLIC_BASE_URL``; a remote site's ``/wp-content/...`` URL does
    not match and is internalized."""
    if not url:
        return False
    media_url = settings.MEDIA_URL
    if url.startswith(media_url):
        return True
    base = getattr(settings, "MEDIA_PUBLIC_BASE_URL", "") or ""
    return bool(base) and url.startswith(f"{base}{media_url}")


def _image_filename(url: str, content_type: str) -> str:
    """A safe storage filename for a downloaded image: the URL's basename,
    sanitized, with an extension inferred from ``content_type`` when missing."""
    from urllib.parse import unquote, urlsplit

    raw = unquote(urlsplit(url).path).rsplit("/", 1)[-1]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", raw).strip("._") or "image"
    if "." not in name:
        name += _CONTENT_TYPE_EXT.get(content_type, ".jpg")
    return name[:255]


def _fetch_image_bytes(url: str) -> tuple[bytes, str] | None:
    """Download a remote image → ``(bytes, content_type)``; ``None`` on failure.

    The single HTTP seam for import-time image internalization (unit tests
    monkeypatch this). Network/HTTP errors are swallowed and logged by host only
    (never the full URL — query strings can carry tokens); the image is then
    skipped and the import continues."""
    from urllib.parse import urlsplit

    try:
        resp = _IMG_POOL.get(url, timeout=30)
        resp.raise_for_status()
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        # InvalidURL ("URL too long", malformed) is NOT an httpx.HTTPError — catch
        # it too so one bad src never crashes the whole import task.
        logger.warning(
            "import image download failed host=%s: %s",
            urlsplit(url).netloc,
            exc.__class__.__name__,
        )
        return None
    content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    return resp.content, content_type


def _webp_bytes_to_png(data: bytes, filename: str) -> tuple[bytes, str]:
    """Re-encode webp bytes to PNG (mirrors serializers._webp_to_png — many WP
    sites reject webp sideload, which kills the whole product in the push batch).
    Falls back to the original bytes if PIL cannot decode them."""
    from PIL import Image

    try:
        buf = io.BytesIO()
        Image.open(io.BytesIO(data)).save(buf, format="PNG")
    except Exception as exc:  # noqa: BLE001 - any decode/encode error → keep original
        logger.warning("import webp→png failed: %s", exc.__class__.__name__)
        return data, filename
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return buf.getvalue(), f"{stem}.png"


def _store_hub_image(data: bytes, filename: str, content_type: str) -> str | None:
    """Save downloaded image ``data`` into the Hub media library (``ProductImage``)
    and return the URL to reference it by — absolute via ``MEDIA_PUBLIC_BASE_URL``,
    or root-relative when no public base is set (the same shape the upload
    serializer produces). Returns None if the file cannot be stored."""
    from django.core.files.base import ContentFile

    if content_type == "image/webp" or filename.lower().endswith(".webp"):
        data, filename = _webp_bytes_to_png(data, filename)
    try:
        image = ProductImage.objects.create(
            image=ContentFile(data, name=filename),
            original_name=filename[:255],
        )
    except (OSError, ValueError) as exc:
        logger.warning("import image store failed name=%s: %s", filename, exc.__class__.__name__)
        return None
    url = image.image.url
    base = getattr(settings, "MEDIA_PUBLIC_BASE_URL", "") or ""
    return f"{base}{url}" if base else url


def _normalize_remote_image_url(url: str) -> str:
    """Make a remote image src fetchable by httpx.

    Product galleries/descriptions often carry **protocol-relative** srcs
    (``//cdn.example/x.jpg``) — common from CDN-hosted images (e.g. bizweb/Sapo).
    httpx rejects a schemeless URL with ``UnsupportedProtocol``, so the download
    fails and the image is never internalized. Give such srcs an explicit
    ``https:`` scheme; everything else passes through unchanged."""
    if not url:
        return url
    url = url.strip()
    if url.startswith("//"):
        return f"https:{url}"
    return url


def _internalize_remote_image(url: str, cache: dict) -> str:
    """Pull one remote product image into the Hub media library, returning the Hub
    URL to use in its place. Idempotent within a run via ``cache`` (same src
    downloaded once). Already-Hub URLs are returned unchanged; a failed download
    falls back to the ORIGINAL url so the push still has something to try (a
    hot-link, the pre-fix behaviour) instead of dropping the image silently.

    ``cache`` only ever holds entries for remote srcs we attempted, so the caller
    reads it back as the per-run internalize stats (``dst != src`` = success)."""
    url = _normalize_remote_image_url(url)
    # Only http(s) images are worth (and safe to) internalize. Hub-media URLs are
    # already local; ``data:``/``blob:`` URIs are self-contained and can be tens of
    # KB long (httpx rejects them with InvalidURL "URL too long"); a relative src
    # has no host to fetch from. Leave all of these embedded as-is.
    if not url or _is_hub_media_url(url) or not url.startswith(("http://", "https://")):
        return url
    if url in cache:
        return cache[url]
    fetched = _fetch_image_bytes(url)
    hub_url = None
    if fetched is not None:
        data, content_type = fetched
        hub_url = _store_hub_image(data, _image_filename(url, content_type), content_type)
    result = hub_url or url
    cache[url] = result
    return result


def _internalize_html_images(html: str, cache: dict) -> str:
    """Rewrite every ``<img src>`` in ``html`` pointing at a remote site to its Hub
    copy (downloaded on demand), so the description is served from the Hub after
    import — matching a Hub-created product. Hub/relative srcs and failed
    downloads are left untouched."""
    if not html:
        return html or ""

    def _replace(match: re.Match) -> str:
        src = match.group("src")
        new = _internalize_remote_image(src, cache)
        return match.group(0).replace(src, new) if new != src else match.group(0)

    return _IMG_SRC_RE.sub(_replace, html)


def _internalize_imported_media(fields: dict, cache: dict) -> dict:
    """In-place: replace an imported master's remote image references (gallery +
    description HTML) with Hub-hosted copies, so a later push to OTHER sites
    serves them from the Hub instead of the (often unreachable) source site."""
    fields["images"] = [_internalize_remote_image(u, cache) for u in (fields.get("images") or [])]
    fields["description"] = _internalize_html_images(fields.get("description", ""), cache)
    fields["short_description"] = _internalize_html_images(
        fields.get("short_description", ""), cache
    )
    return fields


def _import_image_workers() -> int:
    """Max images downloaded concurrently during import (settings, default 4)."""
    return max(1, getattr(settings, "PRODUCT_IMPORT_IMAGE_WORKERS", 4))


def _import_match_by_name_enabled() -> bool:
    """Whether import LINKS a product to an existing master by normalized name when
    no SKU matches (SKUs are often inconsistent/missing across sites, so name is the
    only reliable cross-site key). See ``import_products_from_site``."""
    return bool(getattr(settings, "PRODUCT_IMPORT_MATCH_BY_NAME", True))


def _remote_image_urls(item: dict) -> list[str]:
    """Every image src a remote product references: gallery + description ``<img>``.

    Raw srcs (pre-normalization); the caller applies the same normalize/guard as
    ``_internalize_remote_image`` before deciding what to download."""
    urls = [
        img["src"] for img in (item.get("images") or []) if isinstance(img, dict) and img.get("src")
    ]
    for html in (item.get("description") or "", item.get("short_description") or ""):
        urls += [m.group("src") for m in _IMG_SRC_RE.finditer(html)]
    return urls


def _prefetch_import_images(
    site, products, mapped_woo_ids, media_cache, existing_names=None
) -> None:
    """Warm ``media_cache`` by downloading (CONCURRENTLY) every remote image a
    NEW master would internalize, so the per-item internalize in the import loop
    is a pure cache lookup instead of a serial network call.

    Only items that will CREATE a master are considered — importable type, not
    already mapped, no live master with the same SKU, and (when name matching is
    on) no live master with the same normalized NAME (those LINK and reuse the
    existing master's Hub images). ``existing_names`` is the set of normalized
    match-names of live masters (``None``/empty = name matching off). Unique remote
    http(s) srcs (Hub/relative/data URLs skipped, same guard as
    ``_internalize_remote_image``) are fetched with a bounded ``ThreadPoolExecutor``
    (network only — no ORM in the threads), then stored SEQUENTIALLY on the main
    thread so DB writes stay single-threaded. ``media_cache`` ends up
    ``{normalized_url: hub_url or original_url}``, the exact shape
    ``_internalize_remote_image`` reads back (it normalizes before the cache
    lookup), so a failed download stays a hot-link and is counted.
    """
    existing_names = existing_names or set()
    # SKUs that would CREATE a new master (skip the loop's non-create items).
    new_items: list[dict] = []
    real_skus: list[str] = []
    for item in products:
        woo_id = item.get("id")
        if not woo_id or woo_id in mapped_woo_ids:
            continue
        if (item.get("type") or MasterProduct.Type.SIMPLE) not in _IMPORTABLE_TYPES:
            continue
        sku = normalize_sku(item.get("sku", ""))
        new_items.append(item)
        if sku:
            real_skus.append(sku)
    existing_skus = (
        set(
            MasterProduct.objects.filter(sku__in=real_skus, is_deleted=False).values_list(
                "sku", flat=True
            )
        )
        if real_skus
        else set()
    )

    to_fetch: dict = {}  # normalized_url → None (ordered unique set)
    for item in new_items:
        sku = normalize_sku(item.get("sku", ""))
        if sku and sku in existing_skus:
            continue  # links to an existing master by SKU → reuses its Hub images
        if existing_names and normalize_match_name(item.get("name", "")) in existing_names:
            continue  # will likely LINK by name → reuses the existing master's images
        for raw in _remote_image_urls(item):
            url = _normalize_remote_image_url(raw)
            if not url or _is_hub_media_url(url) or not url.startswith(("http://", "https://")):
                continue
            to_fetch.setdefault(url, None)
    if not to_fetch:
        return

    urls = list(to_fetch)
    workers = min(_import_image_workers(), len(urls))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        fetched = list(executor.map(_fetch_image_bytes, urls))
    for url, result in zip(urls, fetched, strict=False):
        if url in media_cache:
            continue
        hub_url = None
        if result is not None:
            data, content_type = result
            hub_url = _store_hub_image(data, _image_filename(url, content_type), content_type)
        media_cache[url] = hub_url or url


def import_products_from_site(site, *, run_id=None, triggered_by_id=None) -> dict:
    """Import one site's products into the Hub catalog (the "lấy data chuẩn từ
    website chính về" bootstrap).

    Mirrors ``pull_categories_for_site``: builds the client, lists every product,
    and for each SIMPLE product either LINKS it to an existing master or CREATES a
    new one — freezing the site name into ``match_name`` and stamping
    ``source_site``/``imported_at``. **Matching is SKU-first, then NAME:** an exact
    normalized-SKU match links; otherwise (when ``PRODUCT_IMPORT_MATCH_BY_NAME``,
    default on) a UNIQUE normalized-name match links too — so two sites carrying the
    same products under inconsistent/missing SKUs converge onto ONE master instead
    of duplicating (``linked_by_name`` counts these). A master already mapped to
    THIS site is excluded from name matching, so two products of one site never
    collapse onto one master (which would clobber a ``(master, site)`` mapping);
    >1 candidate is ambiguous → a new master is created and ``name_ambiguous`` is
    reported (never a silent wrong merge). Linking never overwrites the master's
    data — only a mapping is added. The new/linked master is mapped to the site so
    a later push UPDATEs it instead of duplicating. ``variable`` /
    ``grouped`` / ``external`` products are NOT imported (v1: pushing a
    half-defined master of those types would degrade the site product) — they are
    counted in ``skipped`` / ``skipped_types`` so the report names what needs
    manual handling. Idempotent: a product already mapped on the site is skipped,
    so re-importing is safe. Network errors are caught and returned (never
    raised); a ``SyncLog`` row records the outcome. Logs by ``site_id`` only.

    A new master's images (gallery + those embedded in the description HTML) are
    INTERNALIZED — downloaded into the Hub media library and the references
    rewritten to Hub URLs (``_internalize_imported_media``, gated by
    ``PRODUCT_INTERNALIZE_IMPORTED_IMAGES``). Without this the master would keep
    the SOURCE site's image URLs, and a push to OTHER sites would fail to sideload
    them (the source is often unreachable from the target), dropping the images.
    The downloads run OUTSIDE the per-item transaction (network I/O must not hold
    one open) and are deduped across the run; a failed download keeps the original
    URL and is counted in ``image_download_failures``. They are prefetched
    CONCURRENTLY up front (``_prefetch_import_images``) so the per-item loop only
    reads the warmed cache instead of downloading images one at a time.
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
    linked_by_name = name_ambiguous = 0
    skipped_types: dict = {}
    # woo ids already mapped on this site → idempotent skip on re-import.
    mapped_woo_ids = set(
        ProductMapping.objects.filter(site=site).values_list("woo_product_id", flat=True)
    )
    now = timezone.now()

    # Name-match fallback: SKUs are often inconsistent/missing across sites, so a
    # product with no SKU match LINKs to an existing master by normalized name.
    # Index live masters by their match key (frozen import name, else name); track
    # masters already mapped to THIS site so two products of one site can never
    # collapse onto one master (which would clobber a (master, site) mapping).
    match_by_name = _import_match_by_name_enabled()
    name_index: dict = {}  # normalized name → [master_id, ...]
    if match_by_name:
        for m in MasterProduct.objects.filter(is_deleted=False).values("id", "match_name", "name"):
            key = normalize_match_name(m["match_name"] or m["name"])
            if key:
                name_index.setdefault(key, []).append(m["id"])
    existing_names = set(name_index)
    mapped_master_ids = set(
        ProductMapping.objects.filter(site=site).values_list("master_id", flat=True)
    )

    internalize = _internalize_imported_images_enabled()
    media_cache: dict = {}  # remote src → Hub url, deduped across this run
    # Download all new masters' images concurrently up front so the loop below
    # only reads the warmed cache (no serial per-image network call). Items that
    # will LINK (by SKU or name) are skipped — they reuse the master's Hub images.
    if internalize:
        _prefetch_import_images(site, products, mapped_woo_ids, media_cache, existing_names)
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
        matched_by_name = False
        # SKU is the primary cross-site key; when it does not match, fall back to
        # the normalized NAME. Only a UNIQUE match links; a master already mapped
        # to THIS site is excluded (no same-site collapse); >1 candidate is
        # ambiguous → create a new master and report it (never silently merge).
        if master is None and match_by_name:
            key = normalize_match_name(item.get("name", ""))
            candidates = [mid for mid in name_index.get(key, []) if mid not in mapped_master_ids]
            if len(candidates) == 1:
                master = MasterProduct.objects.filter(id=candidates[0]).first()
                matched_by_name = master is not None
            elif len(candidates) > 1:
                name_ambiguous += 1
        # Internalize images BEFORE opening the transaction — downloading remote
        # files must not hold a DB transaction open. Only a NEW master needs it;
        # linking (by SKU or name) reuses that master's (already-Hub) images.
        fields = None
        if master is None:
            fields = _master_fields_from_remote(item, sku, site, now)
            if internalize:
                _internalize_imported_media(fields, media_cache)
        with transaction.atomic():
            if master is None:
                master = MasterProduct.objects.create(**fields)
                created += 1
                new_key = normalize_match_name(master.match_name or master.name)
                if new_key:
                    name_index.setdefault(new_key, []).append(master.id)
            else:
                linked += 1
                if matched_by_name:
                    linked_by_name += 1
            ProductMapping.objects.update_or_create(
                master=master,
                site=site,
                defaults={"woo_product_id": woo_id, "last_synced_at": now},
            )
        mapped_master_ids.add(master.id)
        mapped_woo_ids.add(woo_id)

    # media_cache holds one entry per remote image we attempted (Hub URLs are not
    # cached): a rewritten value = a download that landed, an unchanged value = a
    # failure we left as a hot-link.
    images_internalized = sum(1 for src, dst in media_cache.items() if dst != src)
    image_download_failures = sum(1 for src, dst in media_cache.items() if dst == src)
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
            # Of ``linked``, how many matched by NAME (not SKU) — visibility into
            # the cross-site name-merge; ``name_ambiguous`` = products left as a
            # new master because >1 existing master shared the name (need a human).
            "linked_by_name": linked_by_name,
            "name_ambiguous": name_ambiguous,
            "skipped": skipped,
            "skipped_types": skipped_types,
            "images_internalized": images_internalized,
            "image_download_failures": image_download_failures,
            **_site_snapshot(site),
        },
        **audit,
    )
    return {
        "site_id": site.id,
        "imported": created + linked,
        "created": created,
        "linked": linked,
        "linked_by_name": linked_by_name,
        "name_ambiguous": name_ambiguous,
        "skipped": skipped,
        "images_internalized": images_internalized,
        "image_download_failures": image_download_failures,
        "error": None,
    }
