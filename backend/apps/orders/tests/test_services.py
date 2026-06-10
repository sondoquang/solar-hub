import httpx
import pytest

from apps.orders import services
from apps.orders.models import Order
from apps.sites.tests.factories import SiteFactory


def _woo_order(order_id=101, status="processing", total="250000.00"):
    """A minimal WooCommerce order payload (the fields normalize_order reads)."""
    return {
        "id": order_id,
        "number": str(order_id),
        "status": status,
        "currency": "VND",
        "total": total,
        "date_created_gmt": "2026-06-01T03:00:00",
        "date_modified_gmt": "2026-06-02T05:00:00",
        "customer_note": "Giao giờ hành chính",
        "billing": {
            "first_name": "Văn A",
            "last_name": "Nguyễn",
            "phone": "0911222333",
            "email": "a@example.com",
            "address_1": "12 Lê Lợi",
            "city": "Đà Nẵng",
        },
        "line_items": [
            {"sku": "PIN-100", "name": "Pin 100W", "quantity": 2, "total": "200000.00"},
        ],
    }


def test_normalize_order_maps_fields():
    site = SiteFactory.build()
    data = services.normalize_order(site, _woo_order())
    assert data["number"] == "101"
    assert data["status"] == "processing"
    assert data["currency"] == "VND"
    assert str(data["total"]) == "250000.00"
    assert data["customer_name"] == "Văn A Nguyễn"
    assert data["customer_phone"] == "0911222333"
    assert "Lê Lợi" in data["shipping_address"]
    assert data["customer_note"] == "Giao giờ hành chính"
    assert data["line_items"] == [
        {"sku": "PIN-100", "name": "Pin 100W", "quantity": 2, "total": "200000.00"}
    ]
    assert data["date_created_woo"].year == 2026
    # Modified watermark prefers date_modified_gmt over date_created_gmt.
    assert data["date_modified_woo"].day == 2


@pytest.mark.django_db
def test_upsert_order_is_idempotent():
    site = SiteFactory()
    order1, created1 = services.upsert_order(site, _woo_order(order_id=55))
    order2, created2 = services.upsert_order(
        site, _woo_order(order_id=55, status="completed")
    )
    assert created1 is True
    assert created2 is False
    assert order1.pk == order2.pk
    assert Order.objects.filter(site=site, woo_order_id=55).count() == 1
    order2.refresh_from_db()
    assert order2.status == "completed"  # second call updated in place


class _FakeClient:
    def __init__(self, orders, *, capture=None):
        self._orders = orders
        self._capture = capture

    def list_orders(
        self,
        status="processing",
        per_page=100,
        after=None,
        before=None,
        modified_after=None,
    ):
        if self._capture is not None:
            self._capture["status"] = status
            self._capture["after"] = after
            self._capture["before"] = before
            self._capture["modified_after"] = modified_after
        return self._orders


@pytest.mark.django_db
def test_poll_site_creates_orders_and_sets_watermark(monkeypatch):
    site = SiteFactory()
    capture = {}
    payloads = [_woo_order(order_id=1), _woo_order(order_id=2)]
    monkeypatch.setattr(
        "apps.sites.services.client_for_site",
        lambda s: _FakeClient(payloads, capture=capture),
    )

    result = services.poll_site(site)
    assert result["fetched"] == 2
    assert result["created"] == 2
    assert result["updated"] == 0
    assert result["status"] == "processing"
    assert result["error"] is None
    assert Order.objects.filter(site=site).count() == 2
    # First poll has no prior orders of this status → no watermark.
    assert capture["modified_after"] is None
    assert capture["status"] == "processing"

    # Second poll: watermark = newest stored date_modified_woo, no new orders.
    capture.clear()
    monkeypatch.setattr(
        "apps.sites.services.client_for_site",
        lambda s: _FakeClient([], capture=capture),
    )
    result2 = services.poll_site(site)
    assert result2["fetched"] == 0
    assert capture["modified_after"] is not None  # watermark sent on later polls


@pytest.mark.django_db
def test_poll_site_watermark_is_per_status(monkeypatch):
    """Polling 'completed' must not be gated by the 'processing' watermark."""
    site = SiteFactory()
    capture = {}
    monkeypatch.setattr(
        "apps.sites.services.client_for_site",
        lambda s: _FakeClient([_woo_order(order_id=7)], capture=capture),
    )
    # Store a processing order (sets the processing watermark only).
    services.poll_site(site, "processing")

    capture.clear()
    monkeypatch.setattr(
        "apps.sites.services.client_for_site",
        lambda s: _FakeClient([], capture=capture),
    )
    services.poll_site(site, "completed")
    # No completed orders yet → full fetch for that status.
    assert capture["status"] == "completed"
    assert capture["modified_after"] is None


def test_date_bounds_inclusive_of_both_days():
    """date_from/date_to map to after (exclusive, stepped back) / before (EOD)."""
    after, before = services._date_bounds("2026-06-01", "2026-06-03")
    # after is exclusive on Woo's side → step back a second to include all of 06-01.
    assert after == "2026-05-31T23:59:59"
    # before uses end-of-day so all of 06-03 is included.
    assert before.startswith("2026-06-03T23:59:59")
    # Each bound is independent / optional.
    assert services._date_bounds(None, None) == (None, None)
    assert services._date_bounds("2026-06-01", None)[1] is None
    assert services._date_bounds(None, "2026-06-03")[0] is None


@pytest.mark.django_db
def test_poll_site_date_range_skips_watermark(monkeypatch):
    """A date-range sync bounds on after/before and ignores the watermark."""
    site = SiteFactory()
    capture = {}
    # Store an order first so a watermark WOULD exist for this (site, status).
    monkeypatch.setattr(
        "apps.sites.services.client_for_site",
        lambda s: _FakeClient([_woo_order(order_id=9)], capture=capture),
    )
    services.poll_site(site, "processing")

    capture.clear()
    monkeypatch.setattr(
        "apps.sites.services.client_for_site",
        lambda s: _FakeClient([], capture=capture),
    )
    services.poll_site(site, "processing", date_from="2026-06-01", date_to="2026-06-03")
    # Range mode: watermark is skipped, after/before drive the fetch instead.
    assert capture["modified_after"] is None
    assert capture["after"] == "2026-05-31T23:59:59"
    assert capture["before"].startswith("2026-06-03T23:59:59")


@pytest.mark.django_db
def test_poll_site_swallows_network_error(monkeypatch):
    site = SiteFactory()

    def _boom(s):
        class _C:
            def list_orders(self, **kw):
                raise httpx.ConnectError("down")

        return _C()

    monkeypatch.setattr("apps.sites.services.client_for_site", _boom)
    result = services.poll_site(site)
    assert result["error"] == "ConnectError"
    assert result["fetched"] == 0
    assert Order.objects.filter(site=site).count() == 0


class _FakeWriteClient:
    """Fake client whose update_order echoes a payload with the new status."""

    def __init__(self, raw, *, capture=None):
        self._raw = raw
        self._capture = capture

    def update_order(self, woo_order_id, *, status):
        if self._capture is not None:
            self._capture["woo_order_id"] = woo_order_id
            self._capture["status"] = status
        return {**self._raw, "status": status}


@pytest.mark.django_db
def test_mark_order_completed_pushes_and_syncs(monkeypatch):
    from apps.orders.tests.factories import OrderFactory

    site = SiteFactory()
    order = OrderFactory(site=site, woo_order_id=77, status="processing")
    capture = {}
    monkeypatch.setattr(
        "apps.sites.services.client_for_site",
        lambda s: _FakeWriteClient(_woo_order(order_id=77), capture=capture),
    )

    result = services.mark_order_completed(order)
    assert result.status == "completed"
    assert capture == {"woo_order_id": 77, "status": "completed"}
    # Upsert is idempotent on (site, woo_order_id): same row, now completed.
    assert Order.objects.filter(site=site, woo_order_id=77).count() == 1
    result.refresh_from_db()
    assert result.status == "completed"


@pytest.mark.django_db
def test_mark_order_completed_rejects_non_processing(monkeypatch):
    from apps.orders.tests.factories import OrderFactory

    order = OrderFactory(status="pending")

    def _boom(s):  # pragma: no cover - must not be reached
        raise AssertionError("WooCommerce must not be called for a bad transition")

    monkeypatch.setattr("apps.sites.services.client_for_site", _boom)
    with pytest.raises(services.InvalidStatusTransition):
        services.mark_order_completed(order)


@pytest.mark.django_db
def test_mark_order_completed_propagates_network_error(monkeypatch):
    from apps.orders.tests.factories import OrderFactory

    order = OrderFactory(status="processing")

    def _client(s):
        class _C:
            def update_order(self, woo_order_id, *, status):
                raise httpx.ConnectError("down")

        return _C()

    monkeypatch.setattr("apps.sites.services.client_for_site", _client)
    with pytest.raises(httpx.HTTPError):
        services.mark_order_completed(order)


@pytest.mark.django_db
def test_mark_order_cancelled_pushes_and_syncs(monkeypatch):
    from apps.orders.tests.factories import OrderFactory

    site = SiteFactory()
    order = OrderFactory(site=site, woo_order_id=66, status="processing")
    capture = {}
    monkeypatch.setattr(
        "apps.sites.services.client_for_site",
        lambda s: _FakeWriteClient(_woo_order(order_id=66), capture=capture),
    )

    result = services.mark_order_cancelled(order)
    assert result.status == "cancelled"
    assert capture == {"woo_order_id": 66, "status": "cancelled"}
    result.refresh_from_db()
    assert result.status == "cancelled"


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["pending", "processing", "on-hold"])
def test_mark_order_cancelled_allows_non_terminal(monkeypatch, status):
    from apps.orders.tests.factories import OrderFactory

    order = OrderFactory(status=status)
    monkeypatch.setattr(
        "apps.sites.services.client_for_site",
        lambda s: _FakeWriteClient(_woo_order(order_id=order.woo_order_id)),
    )
    result = services.mark_order_cancelled(order)
    assert result.status == "cancelled"


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["completed", "cancelled", "refunded", "failed"])
def test_mark_order_cancelled_rejects_terminal(monkeypatch, status):
    from apps.orders.tests.factories import OrderFactory

    order = OrderFactory(status=status)

    def _boom(s):  # pragma: no cover - must not be reached
        raise AssertionError("WooCommerce must not be called for a bad transition")

    monkeypatch.setattr("apps.sites.services.client_for_site", _boom)
    with pytest.raises(services.InvalidStatusTransition):
        services.mark_order_cancelled(order)


@pytest.mark.django_db
def test_forward_order_is_one_way_and_idempotent():
    from apps.orders.tests.factories import OrderFactory

    order = OrderFactory(status="processing", forwarded=False)
    forwarded = services.forward_order(order)
    assert forwarded.forwarded is True
    assert forwarded.forwarded_at is not None
    first_at = forwarded.forwarded_at

    # Second call is a no-op: still forwarded, timestamp unchanged.
    again = services.forward_order(forwarded)
    assert again.forwarded is True
    assert again.forwarded_at == first_at
    again.refresh_from_db()
    assert again.forwarded is True


@pytest.mark.django_db
def test_upsert_completed_order_auto_forwards():
    site = SiteFactory()
    # A processing order is not forwarded by the sync.
    order, _ = services.upsert_order(site, _woo_order(order_id=21, status="processing"))
    assert order.forwarded is False
    # When it flips to completed, the upsert marks it forwarded to marketing.
    order, _ = services.upsert_order(site, _woo_order(order_id=21, status="completed"))
    assert order.forwarded is True
    assert order.forwarded_at is not None


@pytest.mark.django_db
def test_poll_site_auto_forwards_completed_orders(monkeypatch):
    site = SiteFactory()
    monkeypatch.setattr(
        "apps.sites.services.client_for_site",
        lambda s: _FakeClient([_woo_order(order_id=33, status="completed")]),
    )
    services.poll_site(site, "completed")
    order = Order.objects.get(site=site, woo_order_id=33)
    assert order.forwarded is True
    assert order.forwarded_at is not None


@pytest.mark.django_db
def test_mark_order_completed_auto_forwards(monkeypatch):
    from apps.orders.tests.factories import OrderFactory

    site = SiteFactory()
    order = OrderFactory(site=site, woo_order_id=88, status="processing", forwarded=False)
    monkeypatch.setattr(
        "apps.sites.services.client_for_site",
        lambda s: _FakeWriteClient(_woo_order(order_id=88)),
    )
    result = services.mark_order_completed(order)
    assert result.status == "completed"
    assert result.forwarded is True  # completed ⇒ đã chuyển marketing


@pytest.mark.django_db
def test_forward_orders_bulk_respects_queryset_and_skips_forwarded():
    from apps.orders.tests.factories import OrderFactory

    site = SiteFactory()
    a = OrderFactory(site=site, status="processing", forwarded=False)
    b = OrderFactory(site=site, status="processing", forwarded=False)
    already = OrderFactory(site=site, status="processing", forwarded=True)

    count = services.forward_orders(Order.objects.all(), [a.id, b.id, already.id])
    assert count == 2  # only the two not-yet-forwarded flip
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.forwarded and b.forwarded


@pytest.mark.django_db
def test_order_stats_totals_and_by_status():
    from apps.orders.tests.factories import OrderFactory

    site = SiteFactory()
    OrderFactory.create_batch(3, site=site, status="processing", total="100000.00")
    OrderFactory.create_batch(2, site=site, status="completed", total="50000.00")
    stats = services.order_stats(Order.objects.all())
    assert stats["total"] == 5
    assert str(stats["revenue"]) == "400000.00"
    assert stats["by_status"] == {"processing": 3, "completed": 2}
    assert stats["by_classification"] == {"genuine": 5}


# --- Classification (genuine / suspicious / spam) ----------------------------


def _clean_fields():
    return {
        "customer_phone": "0911222333",
        "customer_email": "a@example.com",
        "customer_name": "Nguyễn Văn A",
        "shipping_address": "12 Lê Lợi, Đà Nẵng",
    }


def test_classify_fields_clean_order_has_no_reasons():
    assert services.classify_fields(_clean_fields()) == []


def test_classify_fields_flags_missing_pii():
    reasons = services.classify_fields(
        {"customer_phone": "", "customer_email": "", "customer_name": "", "shipping_address": ""}
    )
    assert "phone_missing" in reasons
    assert "name_missing" in reasons
    assert "address_missing" in reasons


def test_classify_fields_phone_rules():
    invalid = services.classify_fields({**_clean_fields(), "customer_phone": "12345"})
    assert "phone_invalid" in invalid
    fake = services.classify_fields({**_clean_fields(), "customer_phone": "0000000000"})
    assert "phone_fake" in fake
    # +84 country code is normalized to a leading 0 and accepted.
    assert services.classify_fields(
        {**_clean_fields(), "customer_phone": "+84911222333"}
    ) == []


def test_classify_fields_email_rules():
    bad = services.classify_fields({**_clean_fields(), "customer_email": "not-an-email"})
    assert "email_invalid" in bad
    disposable = services.classify_fields(
        {**_clean_fields(), "customer_email": "bot@mailinator.com"}
    )
    assert "email_disposable" in disposable


def test_classify_fields_name_and_address_rules():
    gibberish = services.classify_fields({**_clean_fields(), "customer_name": "xzqwbk"})
    assert "name_gibberish" in gibberish
    short = services.classify_fields({**_clean_fields(), "shipping_address": "abc"})
    assert "address_short" in short


def test_label_for_score_thresholds():
    assert services._label_for_score(0) == services.GENUINE
    assert services._label_for_score(services.SUSPICIOUS_THRESHOLD) == services.SUSPICIOUS
    assert services._label_for_score(services.SPAM_THRESHOLD) == services.SPAM


@pytest.mark.django_db
def test_classify_velocity_detects_phone_burst():
    from apps.orders.tests.factories import OrderFactory

    site = SiteFactory()
    a = OrderFactory(site=site, customer_phone="0911222333")
    OrderFactory(site=site, customer_phone="0911222333")
    OrderFactory(site=site, customer_phone="0911222333")
    reasons = services.classify_velocity(a)
    assert "velocity_phone" in reasons


@pytest.mark.django_db
def test_classify_velocity_ignores_lone_order():
    from apps.orders.tests.factories import OrderFactory

    order = OrderFactory(customer_phone="0911222333", customer_email="solo@example.com")
    assert services.classify_velocity(order) == []


@pytest.mark.django_db
def test_upsert_classifies_clean_order_as_genuine():
    site = SiteFactory()
    order, _ = services.upsert_order(site, _woo_order(order_id=200))
    assert order.classification == services.GENUINE
    assert order.risk_score == 0
    assert order.classified_at is not None


@pytest.mark.django_db
def test_upsert_classifies_junk_order_as_spam():
    """A payload with no billing (no phone/name/address) scores as spam."""
    site = SiteFactory()
    junk = {
        "id": 300,
        "number": "300",
        "status": "processing",
        "total": "0",
        "date_created_gmt": "2026-06-01T03:00:00",
    }
    order, _ = services.upsert_order(site, junk)
    assert order.classification == services.SPAM
    assert "phone_missing" in order.risk_reasons


@pytest.mark.django_db
def test_completed_spam_order_is_not_auto_forwarded():
    """The auto-forward rule holds back suspicious/spam orders for manual review."""
    site = SiteFactory()
    junk = {
        "id": 301,
        "number": "301",
        "status": "completed",
        "total": "0",
        "date_created_gmt": "2026-06-01T03:00:00",
    }
    order, _ = services.upsert_order(site, junk)
    assert order.classification == services.SPAM
    assert order.forwarded is False  # gated despite being completed


@pytest.mark.django_db
def test_manual_forward_overrides_spam_classification():
    from apps.orders.tests.factories import OrderFactory

    order = OrderFactory(status="processing", forwarded=False, classification=services.SPAM)
    services.forward_order(order)
    assert order.forwarded is True  # manual forward is the admin override path


@pytest.mark.django_db
def test_reclassify_orders_command_rescore_existing(monkeypatch):
    from io import StringIO

    from django.core.management import call_command

    from apps.orders.tests.factories import OrderFactory

    # An order stored before classification existed (default genuine/0).
    order = OrderFactory(
        customer_phone="", customer_name="", shipping_address="", classification=services.GENUINE
    )
    call_command("reclassify_orders", stdout=StringIO())
    order.refresh_from_db()
    assert order.classification == services.SPAM
    assert order.risk_score > 0
