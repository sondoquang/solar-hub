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

from .models import MasterProduct, ProductMapping

logger = logging.getLogger(__name__)

OPERATION = "push_products"

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


def build_product_payload(master: MasterProduct) -> dict:
    """Map a ``MasterProduct`` to a WooCommerce product payload.

    Prices/weight are sent as strings (Woo's API expects strings). Categories are
    sent by **name** (v1) so Woo matches or creates them; images as ``[{"src"}]``.
    Kept separate from the push so it can be unit-tested without a DB.
    """
    payload = {
        "name": master.name,
        "sku": master.sku,
        "type": master.type,
        "description": master.description,
        "short_description": master.short_description,
        "regular_price": str(master.regular_price),
        "status": master.status,
        "stock_status": master.stock_status,
        "categories": [{"name": c} for c in (master.categories or [])],
        "images": [{"src": url} for url in (master.images or [])],
    }
    if master.sale_price is not None:
        payload["sale_price"] = str(master.sale_price)
    if master.weight is not None:
        payload["weight"] = str(master.weight)
    return payload


def _chunked(items: list, size: int):
    """Yield ``items`` in chunks of at most ``size`` (size >= 1)."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _plan_site_push(site, masters: list[MasterProduct]) -> tuple[list, list, list]:
    """Split masters into Woo create/update/delete work for one site.

    Uses the site's existing ``ProductMapping`` rows: unmapped & live → create;
    mapped & live → update (keyed by ``woo_product_id``); mapped & soft-deleted →
    delete. Unmapped & deleted products are skipped (nothing to remove remotely).
    """
    mapping_by_master = {
        m.master_id: m for m in ProductMapping.objects.filter(site=site, master__in=masters)
    }
    create, update, delete = [], [], []
    for master in masters:
        mapping = mapping_by_master.get(master.id)
        if master.is_deleted:
            if mapping:
                delete.append(mapping.woo_product_id)
        elif mapping:
            update.append({"id": mapping.woo_product_id, **build_product_payload(master)})
        else:
            create.append(build_product_payload(master))
    return create, update, delete


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

    create, update, delete = _plan_site_push(site, masters)
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
        ProductMapping.objects.filter(site=site, woo_product_id__in=delete).delete()

    SyncLog.objects.create(
        site=site,
        operation=OPERATION,
        status=SyncLog.Status.SUCCESS,
        created_count=created,
        updated_count=updated,
        deleted_count=deleted,
        detail={"planned": total},
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
