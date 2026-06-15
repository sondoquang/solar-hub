"""Service layer for the orders app: view/task → service → model/WooClient.

Owns order normalization, the idempotent upsert, the per-site poll, and the
list/stats queries for the API. All WooCommerce traffic goes through
``WooClient`` (built by ``apps.sites.services.client_for_site``).
"""

import datetime
import logging
import re

import httpx
from django.db.models import Count, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from .models import GENUINE, SPAM, SUSPICIOUS, Order

logger = logging.getLogger(__name__)

# Default status the periodic poll fetches (new orders worth forwarding to
# marketing). Other statuses are synced on demand from the UI.
POLL_STATUS = "processing"

# SyncLog.operation written for a manual order poll, so the progress banner can
# group this run's per-site rows. Must match apps.sync.services.PROGRESS_OPERATIONS.
POLL_OPERATION = "poll_orders"

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

# Status an order is pushed to when an admin cancels it, and the source statuses
# from which cancelling is allowed — terminal states (completed/cancelled/
# refunded/failed) cannot be cancelled.
CANCELLED_STATUS = "cancelled"
CANCELLABLE_STATUSES = ("pending", "processing", "on-hold")

# Sapo payment statuses (Order.payment_status, from Sapo's financial_status).
# An order in one of UNPAID_PAYMENT_STATUSES is "chưa thanh toán" — the set the
# Sapo poll fetches (financial_status=unpaid) and the dedicated page lists.
# PAID_PAYMENT_STATUS is the terminal state ``mark_order_paid`` drives to.
UNPAID_PAYMENT_STATUSES = ("pending", "authorized", "partially_paid")
PAID_PAYMENT_STATUS = "paid"

# Payment status the Sapo poll asks for (Sapo's "unpaid" filter group). Passed
# to SapoClient.list_orders for Sapo sites only (WooClient has no such param).
UNPAID_POLL_FILTER = "unpaid"


class InvalidStatusTransition(Exception):
    """Raised when an order cannot move to the requested status (maps to 409)."""


def sites_for_order_poll(site_ids=None, platform=None) -> list[int]:
    """The site ids the order poll should actually hit (the single source of
    truth for both the periodic task and the manual ``poll_now`` count).

    WooCommerce sites are independent → all are polled. Sapo is special:

    - **Gated by ``SAPO_ORDER_POLL_ENABLED``** (OFF by default). While off, Sapo
      sites are excluded entirely — the pause switch.
    - **Deduplicated by store** when on. Several Sapo Site records can be
      storefront domains of ONE Sapo backend store — different domains, even
      different API keys, can resolve to the same ``*.mysapo.net`` host; polling
      each would pull the same orders once per site and inflate order/revenue
      counts. So Sapo sites are grouped by ``sapo_store_host`` (the canonical
      host discovered during health-check) and only the lowest-id site of each
      store is polled. A site whose host is not resolved yet (blank) is treated
      as its own store so it is never silently merged with another.

    ``site_ids`` (when given) scopes the candidate set first, so a manual run can
    still target a subset. ``platform`` (``woocommerce`` | ``sapo``) restricts
    the run to one platform — the per-platform "Đồng bộ ngay" screens pass it so
    the WooCommerce screen never pulls Sapo orders and vice versa; ``None`` polls
    both (the periodic beat).
    """
    from django.conf import settings

    from apps.sites.models import Site

    qs = Site.objects.filter(is_deleted=False)
    if site_ids is not None:
        qs = qs.filter(id__in=site_ids)

    ids = []
    if platform in (None, Site.Platform.WOOCOMMERCE):
        ids = list(
            qs.filter(platform=Site.Platform.WOOCOMMERCE).values_list("id", flat=True)
        )
    include_sapo = platform in (None, Site.Platform.SAPO)
    if include_sapo and getattr(settings, "SAPO_ORDER_POLL_ENABLED", False):
        seen_stores: set = set()
        for row in (
            qs.filter(platform=Site.Platform.SAPO)
            .order_by("id")
            .values("id", "sapo_store_host")
        ):
            # Unresolved host → unique key per site (never merge unknowns).
            store = row["sapo_store_host"] or f"site:{row['id']}"
            if store in seen_stores:
                continue
            seen_stores.add(store)
            ids.append(row["id"])
    return ids


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
        # Sapo payment status (``financial_status``, mapped through
        # ``_sapo_order_to_woo``); absent for Woo payloads → "".
        "payment_status": raw.get("financial_status", ""),
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


# --- Order classification (genuine / suspicious / spam) ----------------------
#
# A rule-based risk score distinguishes a real customer order from a bot / spam
# / "vào phá chọn đại" one. Rules are hardcoded here (v1) so they unit-test
# without a DB; ``classify_velocity`` is the one rule that needs the DB. Tune the
# weights/thresholds below as real spam patterns emerge — re-run the
# ``reclassify_orders`` management command afterwards to re-score stored orders.

# Label thresholds on the 0–100 score.
SPAM_THRESHOLD = 70
SUSPICIOUS_THRESHOLD = 35

# How each rule code contributes to the score.
RULE_WEIGHTS = {
    "phone_missing": 40,
    "phone_invalid": 35,
    "phone_fake": 35,
    "email_invalid": 20,
    "email_disposable": 30,
    "name_missing": 25,
    "name_gibberish": 25,
    "address_missing": 25,
    "address_short": 15,
    "velocity_phone": 40,
    "velocity_email": 35,
    "velocity_ip": 30,
}

# Human-readable (Vietnamese) reason per rule code — surfaced in the API/UI.
REASON_LABELS = {
    "phone_missing": "Thiếu số điện thoại",
    "phone_invalid": "SĐT không đúng định dạng Việt Nam",
    "phone_fake": "SĐT giả (dãy số lặp/liên tiếp)",
    "email_invalid": "Email sai định dạng",
    "email_disposable": "Email dùng một lần (disposable)",
    "name_missing": "Thiếu tên khách",
    "name_gibberish": "Tên khách vô nghĩa",
    "address_missing": "Thiếu địa chỉ giao hàng",
    "address_short": "Địa chỉ giao hàng quá ngắn",
    "velocity_phone": "Nhiều đơn cùng SĐT trong thời gian ngắn",
    "velocity_email": "Nhiều đơn cùng email trong thời gian ngắn",
    "velocity_ip": "Nhiều đơn cùng IP trong thời gian ngắn",
}

# Vietnamese mobile numbers: 10 digits, leading 0, second digit in {3,5,7,8,9}.
_VN_PHONE_RE = re.compile(r"^0[35789]\d{8}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_VOWELS = set("aeiouyàáảãạăâèéẹêìíóòôơùúýđ")

# Throwaway-inbox domains; an order using one is rarely a real buyer.
DISPOSABLE_EMAIL_DOMAINS = {
    "mailinator.com",
    "guerrillamail.com",
    "10minutemail.com",
    "yopmail.com",
    "tempmail.com",
    "temp-mail.org",
    "trashmail.com",
    "throwawaymail.com",
    "getnada.com",
    "sharklasers.com",
    "maildrop.cc",
    "dispostable.com",
}

# Velocity: this many orders sharing one phone/email/IP within the window looks
# like a burst, not a customer.
VELOCITY_WINDOW = datetime.timedelta(hours=24)
VELOCITY_MIN_ORDERS = 3


def _normalize_phone(phone: str) -> str:
    """Strip a phone down to digits, mapping a +84/84 country code to a 0."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits


def _is_fake_phone(digits: str) -> bool:
    """All-same digits (0000000000) or a simple run (0123456789 / 9876543210)."""
    if len(digits) < 7:
        return False
    if len(set(digits)) == 1:
        return True
    asc = "0123456789"
    return digits in asc or digits in asc[::-1]


def _looks_gibberish(name: str) -> bool:
    """A name with no vowels or a single repeated letter reads as junk."""
    letters = [c for c in name.lower() if c.isalpha()]
    if not letters:
        return True
    if len(set(letters)) == 1:  # "aaaa", "xxxx"
        return True
    return not any(c in _VOWELS for c in letters)


def classify_fields(data: dict) -> list[str]:
    """Per-order risk signals from the order's own fields — pure, no DB.

    ``data`` is the normalized order dict (or any object exposing the same keys)
    with ``customer_phone`` / ``customer_email`` / ``customer_name`` /
    ``shipping_address``. Returns the list of rule codes that fired.
    """
    reasons: list[str] = []

    phone_raw = (data.get("customer_phone") or "").strip()
    if not phone_raw:
        reasons.append("phone_missing")
    else:
        digits = _normalize_phone(phone_raw)
        if _is_fake_phone(digits):
            reasons.append("phone_fake")
        elif not _VN_PHONE_RE.match(digits):
            reasons.append("phone_invalid")

    email = (data.get("customer_email") or "").strip().lower()
    if email:
        if not _EMAIL_RE.match(email):
            reasons.append("email_invalid")
        elif email.rsplit("@", 1)[-1] in DISPOSABLE_EMAIL_DOMAINS:
            reasons.append("email_disposable")

    name = (data.get("customer_name") or "").strip()
    if len(name) <= 1:
        reasons.append("name_missing")
    elif _looks_gibberish(name):
        reasons.append("name_gibberish")

    address = (data.get("shipping_address") or "").strip()
    if not address:
        reasons.append("address_missing")
    elif len(address) < 10:
        reasons.append("address_short")

    return reasons


def classify_velocity(order: Order) -> list[str]:
    """Cross-order risk signals: bursts of orders sharing a phone/email/IP.

    Counts other orders (any site) created within ``VELOCITY_WINDOW`` of this
    one. The current order is already persisted when this runs (called from
    ``upsert_order`` after ``update_or_create``), so it is excluded by pk.
    """
    reasons: list[str] = []
    created = order.date_created_woo or timezone.now()
    lo, hi = created - VELOCITY_WINDOW, created + VELOCITY_WINDOW
    window = Order.objects.filter(
        date_created_woo__gte=lo, date_created_woo__lte=hi
    ).exclude(pk=order.pk)

    others_needed = VELOCITY_MIN_ORDERS - 1
    if order.customer_phone and (
        window.filter(customer_phone=order.customer_phone).count() >= others_needed
    ):
        reasons.append("velocity_phone")
    if order.customer_email and (
        window.filter(customer_email=order.customer_email).count() >= others_needed
    ):
        reasons.append("velocity_email")

    ip = (order.raw or {}).get("customer_ip_address")
    if ip and (
        window.filter(raw__customer_ip_address=ip).count() >= others_needed
    ):
        reasons.append("velocity_ip")

    return reasons


def _label_for_score(score: int) -> str:
    if score >= SPAM_THRESHOLD:
        return SPAM
    if score >= SUSPICIOUS_THRESHOLD:
        return SUSPICIOUS
    return GENUINE


def classify_order(order: Order) -> dict:
    """Score an order and map it to a label. Combines field + velocity rules."""
    reasons = classify_fields(
        {
            "customer_phone": order.customer_phone,
            "customer_email": order.customer_email,
            "customer_name": order.customer_name,
            "shipping_address": order.shipping_address,
        }
    )
    reasons += classify_velocity(order)
    score = min(100, sum(RULE_WEIGHTS.get(code, 0) for code in reasons))
    return {
        "classification": _label_for_score(score),
        "risk_score": score,
        "risk_reasons": reasons,
    }


def classify_and_save(order: Order) -> Order:
    """Compute the classification for ``order`` and persist the four fields."""
    result = classify_order(order)
    order.classification = result["classification"]
    order.risk_score = result["risk_score"]
    order.risk_reasons = result["risk_reasons"]
    order.classified_at = timezone.now()
    order.save(
        update_fields=[
            "classification",
            "risk_score",
            "risk_reasons",
            "classified_at",
            "updated_at",
        ]
    )
    return order


def _auto_forward_if_completed(order: Order) -> None:
    """A completed *genuine* order counts as forwarded to marketing.

    Central place for "completed ⇒ đã chuyển marketing" so it holds no matter
    how the order reached ``completed``: the periodic poll, a future webhook, or
    the manual ``complete`` action (all funnel through ``upsert_order``). One-way
    only — never clears ``forwarded``.

    Orders classified ``suspicious``/``spam`` are held back so an admin can vet
    them first (manual ``forward`` stays available as an override).
    """
    if (
        order.status == COMPLETED_STATUS
        and order.classification == GENUINE
        and not order.forwarded
    ):
        order.forwarded = True
        order.forwarded_at = timezone.now()
        order.save(update_fields=["forwarded", "forwarded_at", "updated_at"])


def upsert_order(site, raw: dict) -> tuple[Order, bool]:
    """Idempotent upsert keyed on ``(site, woo_order_id)``.

    Safe to call repeatedly (the poll re-fetches, and a future webhook may race
    the poll): the second call updates the existing row instead of duplicating
    it. ``normalize_order`` never touches ``forwarded``/``forwarded_at``, so a
    re-sync can only *add* the marketing flag (via the completed rule below),
    never revert it.
    """
    obj, created = Order.objects.update_or_create(
        site=site,
        woo_order_id=raw["id"],
        defaults=normalize_order(site, raw),
    )
    # Classify first so the auto-forward gate can read the fresh label.
    classify_and_save(obj)
    _auto_forward_if_completed(obj)
    return obj, created


def forward_order(order: Order) -> Order:
    """Mark an order as forwarded to the marketing department (one-way).

    Idempotent and irreversible: once forwarded, calling again is a no-op and
    there is no path back to ``forwarded=False``. Hub-internal only — does NOT
    touch WooCommerce (unlike ``mark_order_completed``).
    """
    if order.forwarded:
        return order
    order.forwarded = True
    order.forwarded_at = timezone.now()
    order.save(update_fields=["forwarded", "forwarded_at", "updated_at"])
    return order


# Cap how many orders one bulk "chuyển marketing" touches, so a careless
# "select all" on a huge filter cannot tie up the request.
MAX_FORWARD_ORDERS = 500


def forward_orders(qs, ids: list[int]) -> int:
    """Forward the given (already-permission-filtered) orders to marketing.

    ``ids`` is intersected with ``qs`` so the active filters/permissions still
    apply. Only orders not yet forwarded are updated; returns how many flipped.
    One-way, in a single bulk UPDATE (no WooCommerce traffic).
    """
    if not ids:
        return 0
    return (
        qs.filter(id__in=ids[:MAX_FORWARD_ORDERS], forwarded=False)
        .update(forwarded=True, forwarded_at=timezone.now())
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


def mark_order_cancelled(order: Order) -> Order:
    """Push an order to ``cancelled`` on its WooCommerce site, then sync the Hub.

    Allowed only from a non-terminal status (``CANCELLABLE_STATUSES``): an order
    already completed/cancelled/refunded/failed can't be cancelled. Writes to
    WooCommerce first (the order's source of truth lives on the site), then
    upserts from the returned payload so the Hub row matches the site and the
    advanced ``date_modified_woo`` keeps the next poll from reverting it.

    Raises ``InvalidStatusTransition`` for a disallowed source status; lets
    ``httpx.HTTPError`` propagate so the caller can map it to a 502.
    """
    from apps.sites.services import client_for_site

    if order.status not in CANCELLABLE_STATUSES:
        raise InvalidStatusTransition(
            f"Không thể hủy đơn ở trạng thái '{order.status}'."
        )

    raw = client_for_site(order.site).update_order(
        order.woo_order_id, status=CANCELLED_STATUS
    )
    obj, _ = upsert_order(order.site, raw)
    return obj


def mark_order_paid(order: Order) -> Order:
    """Mark a Sapo order paid (record a full ``sale`` transaction), then sync.

    Sapo-only: ``client_for_site`` returns a ``WooClient`` for Woo sites, which
    has no ``mark_order_paid`` — so a non-Sapo order is rejected up front rather
    than raising ``AttributeError``. Also rejected when the order is already paid
    or has been cancelled. Writes to Sapo first (the source of truth), then
    upserts the returned (re-fetched) order so the Hub row matches the site and
    the advanced ``date_modified_woo`` keeps the next poll coherent.

    Raises ``InvalidStatusTransition`` for a disallowed order; lets
    ``httpx.HTTPError`` propagate so the caller can map it to a 502.
    """
    from apps.sites.models import Site
    from apps.sites.services import client_for_site

    if order.site.platform != Site.Platform.SAPO:
        raise InvalidStatusTransition(
            "Chỉ đơn Sapo mới có thao tác đánh dấu đã thanh toán."
        )
    if order.status == CANCELLED_STATUS:
        raise InvalidStatusTransition("Không thể thanh toán đơn đã hủy.")
    if order.payment_status == PAID_PAYMENT_STATUS:
        raise InvalidStatusTransition("Đơn đã được thanh toán.")

    raw = client_for_site(order.site).mark_order_paid(
        order.woo_order_id, amount=str(order.total)
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


def _log_poll(
    site, status, *, started, run_id, triggered_by_id, ok, fetched, created, updated, error
):
    """One ``SyncLog`` row recording this site's poll outcome, for the progress
    banner. Only written when ``run_id`` is set (a manual "Đồng bộ ngay" run) —
    the periodic beat polls every site every ~3 min and logging each would bloat
    the audit table for no report. Logs counts only, never order payloads (PII)."""
    if not run_id:
        return
    from apps.sync.models import SyncLog

    hosting = site.hosting if site.hosting_id else None
    SyncLog.objects.create(
        site=site,
        operation=POLL_OPERATION,
        status=SyncLog.Status.SUCCESS if ok else SyncLog.Status.ERROR,
        created_count=created,
        updated_count=updated,
        error=error or "",
        run_id=run_id,
        triggered_by_id=triggered_by_id,
        started_at=started,
        detail={
            "site_name": site.name,
            "site_url": site.base_url,
            "hosting": (hosting.provider or hosting.name) if hosting else "",
            "status_polled": status,
            "fetched": fetched,
        },
    )


def poll_site(
    site,
    status: str = POLL_STATUS,
    *,
    date_from=None,
    date_to=None,
    run_id=None,
    triggered_by_id=None,
) -> dict:
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
    (PII / secrets stay out of logs). When ``run_id`` is set (manual run) the
    outcome is recorded as a ``SyncLog`` row for the progress banner.
    """
    from apps.sites.services import client_for_site

    started = timezone.now()
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

    # Sapo orders are tracked by payment status: the poll fetches only the
    # unpaid ones (financial_status=unpaid), layered on status=open via the
    # status arg. WooClient has no such param, so it is passed for Sapo only.
    from apps.sites.models import Site

    payment_kwargs = (
        {"financial_status": UNPAID_POLL_FILTER}
        if site.platform == Site.Platform.SAPO
        else {}
    )

    created = updated = 0
    try:
        orders = client_for_site(site).list_orders(
            status=status,
            after=after,
            before=before,
            modified_after=modified_after,
            **payment_kwargs,
        )
    except httpx.HTTPError as exc:
        logger.error(
            "poll_site failed site_id=%s status=%s: %s",
            site.id,
            status,
            exc.__class__.__name__,
        )
        _log_poll(
            site, status, started=started, run_id=run_id, triggered_by_id=triggered_by_id,
            ok=False, fetched=0, created=0, updated=0, error=exc.__class__.__name__,
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

    _log_poll(
        site, status, started=started, run_id=run_id, triggered_by_id=triggered_by_id,
        ok=True, fetched=len(orders), created=created, updated=updated, error=None,
    )
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

    platform = params.get("platform")
    if platform:
        qs = qs.filter(site__platform=platform)

    status = params.get("status")
    if status:
        qs = qs.filter(status=status)

    # Payment status (Sapo). "unpaid" is a group → match the not-yet-paid set;
    # any other value is matched exactly (e.g. "paid").
    payment_status = params.get("payment_status")
    if payment_status == UNPAID_POLL_FILTER:
        qs = qs.filter(payment_status__in=UNPAID_PAYMENT_STATUSES)
    elif payment_status:
        qs = qs.filter(payment_status=payment_status)

    classification = params.get("classification")
    if classification:
        qs = qs.filter(classification=classification)

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


# Cap how many orders one PDF export bundles, so a careless "select all" on a
# huge filter cannot build a giant document / tie up the request.
MAX_PDF_ORDERS = 200


def select_orders_for_pdf(qs, ids_param):
    """Pick the orders to render in the PDF, oldest first (reading order).

    ``ids_param`` is the raw ``?ids=1,2,3`` string: when present the export is
    restricted to those ids (intersected with the already-filtered queryset, so
    permissions/filters still apply); when absent the whole filtered selection
    is exported. Capped at ``MAX_PDF_ORDERS``.
    """
    if ids_param:
        ids = [int(p) for p in str(ids_param).split(",") if p.strip().isdigit()]
        qs = qs.filter(id__in=ids)
    return list(qs.order_by("date_created_woo")[:MAX_PDF_ORDERS])


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
    by_classification = {
        row["classification"]: row["n"]
        for row in qs.order_by().values("classification").annotate(n=Count("id"))
    }
    return {
        "total": agg["order_count"] or 0,
        "revenue": agg["revenue"] or 0,
        "not_forwarded": not_forwarded,
        "by_status": by_status,
        "by_classification": by_classification,
    }
