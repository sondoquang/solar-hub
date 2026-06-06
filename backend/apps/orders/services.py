"""Service layer for the orders app: view/task → service → model/WooClient.

Owns order normalization, the idempotent upsert, the per-site poll, and the
list/stats queries for the API. All WooCommerce traffic goes through
``WooClient`` (built by ``apps.sites.services.client_for_site``).
"""

import datetime
import logging

import httpx
from django.db.models import Count, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from .models import Order

logger = logging.getLogger(__name__)

# Default status the periodic poll fetches (new orders worth forwarding to
# marketing). Other statuses are synced on demand from the UI.
POLL_STATUS = "processing"

# Every WooCommerce order status the Hub is allowed to sync. One sync run pulls
# exactly one status; the API validates the requested status against this set.
ALLOWED_POLL_STATUSES = (
    "pending",
    "processing",
    "on-hold",
    "completed",
    "cancelled",
    "refunded",
    "failed",
)

# Status an order is pushed to when an admin marks it done.
COMPLETED_STATUS = "completed"


class InvalidStatusTransition(Exception):
    """Raised when an order cannot move to the requested status (maps to 409)."""


def _to_aware(value) -> datetime.datetime | None:
    """Parse a WooCommerce ISO timestamp into an aware datetime (assume UTC)."""
    if not value:
        return None
    dt = parse_datetime(value)
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, datetime.UTC)
    return dt


def _full_name(party: dict) -> str:
    parts = [party.get("first_name", ""), party.get("last_name", "")]
    return " ".join(p for p in parts if p).strip()


def _address(party: dict) -> str:
    fields = ["address_1", "address_2", "city", "state", "postcode", "country"]
    return ", ".join(str(party[f]).strip() for f in fields if party.get(f)).strip()


def _line_items(raw: dict) -> list[dict]:
    """Trim Woo line items down to what the dashboard shows."""
    return [
        {
            "sku": item.get("sku", ""),
            "name": item.get("name", ""),
            "quantity": item.get("quantity", 0),
            "total": item.get("total", "0"),
        }
        for item in raw.get("line_items", [])
    ]


def normalize_order(site, raw: dict) -> dict:
    """Map a WooCommerce order payload to ``Order`` field defaults.

    Prefers the GMT creation time (``date_created_gmt``) so the per-site
    watermark is comparable across timezones. Kept separate from the upsert so
    it can be unit-tested without a DB.
    """
    billing = raw.get("billing") or {}
    shipping = raw.get("shipping") or {}
    created = _to_aware(raw.get("date_created_gmt")) or _to_aware(
        raw.get("date_created")
    )
    modified = _to_aware(raw.get("date_modified_gmt")) or _to_aware(
        raw.get("date_modified")
    )
    return {
        "number": str(raw.get("number") or raw.get("id") or ""),
        "status": raw.get("status", ""),
        "currency": raw.get("currency", ""),
        "total": raw.get("total") or 0,
        "customer_name": _full_name(billing),
        "customer_phone": billing.get("phone", ""),
        "customer_email": billing.get("email", ""),
        "shipping_address": _address(shipping) or _address(billing),
        "customer_note": raw.get("customer_note", ""),
        "line_items": _line_items(raw),
        "date_created_woo": created or timezone.now(),
        "date_modified_woo": modified or created or timezone.now(),
        "raw": raw,
    }


def upsert_order(site, raw: dict) -> tuple[Order, bool]:
    """Idempotent upsert keyed on ``(site, woo_order_id)``.

    Safe to call repeatedly (the poll re-fetches, and a future webhook may race
    the poll): the second call updates the existing row instead of duplicating
    it.
    """
    return Order.objects.update_or_create(
        site=site,
        woo_order_id=raw["id"],
        defaults=normalize_order(site, raw),
    )


def mark_order_completed(order: Order) -> Order:
    """Push an order to ``completed`` on its WooCommerce site, then sync the Hub.

    Only allowed from ``processing`` (business rule). Writes to WooCommerce
    first (the order's source of truth lives on the site), then upserts from the
    returned payload so the Hub row matches what the site now reports — and so
    the advanced ``date_modified_woo`` keeps the next poll from reverting it.

    Raises ``InvalidStatusTransition`` for a disallowed source status; lets
    ``httpx.HTTPError`` propagate so the caller can map it to a 502.
    """
    from apps.sites.services import client_for_site

    if order.status != "processing":
        raise InvalidStatusTransition(
            f"Chỉ đơn đang xử lý mới được hoàn thành (hiện tại: {order.status})."
        )

    raw = client_for_site(order.site).update_order(
        order.woo_order_id, status=COMPLETED_STATUS
    )
    obj, _ = upsert_order(order.site, raw)
    return obj


def _date_bounds(date_from, date_to) -> tuple[str | None, str | None]:
    """Turn ``YYYY-MM-DD`` strings into Woo ``after`` / ``before`` ISO bounds.

    Mirrors the list-screen filter (``date_created_woo__date`` between the two
    days, both inclusive): ``after`` is exclusive on Woo's side so we step back
    a second to include all of ``date_from``, and ``before`` uses end-of-day to
    include all of ``date_to``. Bounds are naive (GMT) to match
    ``dates_are_gmt=true`` and the stored ``*_gmt`` watermark.
    """
    after = before = None
    d_from = parse_date(date_from) if date_from else None
    d_to = parse_date(date_to) if date_to else None
    if d_from:
        start = datetime.datetime.combine(d_from, datetime.time.min)
        after = (start - datetime.timedelta(seconds=1)).isoformat()
    if d_to:
        before = datetime.datetime.combine(d_to, datetime.time.max).isoformat()
    return after, before


def poll_site(site, status: str = POLL_STATUS, *, date_from=None, date_to=None) -> dict:
    """Fetch orders of one ``status`` for one site and upsert them.

    Two modes, mutually exclusive:

    - **Watermark (default, periodic poll):** ``modified_after`` = the newest
      ``date_modified_woo`` already stored for this ``(site, status)`` so each
      poll only asks WooCommerce for orders touched since the last one. Keying
      on *modified* (not created) means a status transition on an older order is
      caught too: when it flips into ``status`` its ``date_modified`` jumps past
      the watermark and the next poll for that status re-fetches it.
    - **Date range (on-demand backfill):** when ``date_from``/``date_to`` is
      given the watermark is skipped and the fetch is bounded by ``after`` /
      ``before`` on ``date_created`` instead, so the whole requested window is
      re-pulled regardless of when each order was last modified.

    Network errors are caught and returned (never raised) so one bad site does
    not abort the whole fan-out; the site id is logged but never the payload
    (PII / secrets stay out of logs).
    """
    from apps.sites.services import client_for_site

    after, before = _date_bounds(date_from, date_to)
    if after or before:
        modified_after = None
    else:
        latest = (
            Order.objects.filter(site=site, status=status)
            .order_by("-date_modified_woo")
            .values_list("date_modified_woo", flat=True)
            .first()
        )
        modified_after = latest.isoformat() if latest else None

    created = updated = 0
    try:
        orders = client_for_site(site).list_orders(
            status=status,
            after=after,
            before=before,
            modified_after=modified_after,
        )
    except httpx.HTTPError as exc:
        logger.error(
            "poll_site failed site_id=%s status=%s: %s",
            site.id,
            status,
            exc.__class__.__name__,
        )
        return {
            "site_id": site.id,
            "status": status,
            "fetched": 0,
            "created": 0,
            "updated": 0,
            "error": exc.__class__.__name__,
        }

    for raw in orders:
        _, was_created = upsert_order(site, raw)
        if was_created:
            created += 1
        else:
            updated += 1

    return {
        "site_id": site.id,
        "status": status,
        "fetched": len(orders),
        "created": created,
        "updated": updated,
        "error": None,
    }


# --- Querying / aggregation (API) --------------------------------------------


def list_orders_qs(qs, params):
    """Apply the list-screen filters (site / hosting / status / forwarded / dates)."""
    site = params.get("site")
    if site:
        qs = qs.filter(site_id=site)

    hosting = params.get("hosting")
    if hosting == "none":
        qs = qs.filter(site__hosting__isnull=True)
    elif hosting:
        qs = qs.filter(site__hosting_id=hosting)

    status = params.get("status")
    if status:
        qs = qs.filter(status=status)

    forwarded = params.get("forwarded")
    if forwarded in ("true", "false"):
        qs = qs.filter(forwarded=(forwarded == "true"))

    date_from = parse_date(params.get("date_from") or "")
    if date_from:
        qs = qs.filter(date_created_woo__date__gte=date_from)
    date_to = parse_date(params.get("date_to") or "")
    if date_to:
        qs = qs.filter(date_created_woo__date__lte=date_to)

    return qs


def order_stats(qs) -> dict:
    """Totals for the filtered range (cards), independent of paging."""
    # Alias must not be "total" — that would shadow the ``total`` field and
    # break the Sum("total") in the same aggregate() call.
    agg = qs.aggregate(order_count=Count("id"), revenue=Sum("total"))
    not_forwarded = qs.filter(forwarded=False).count()
    by_status = {
        row["status"]: row["n"]
        for row in qs.order_by().values("status").annotate(n=Count("id"))
    }
    return {
        "total": agg["order_count"] or 0,
        "revenue": agg["revenue"] or 0,
        "not_forwarded": not_forwarded,
        "by_status": by_status,
    }
