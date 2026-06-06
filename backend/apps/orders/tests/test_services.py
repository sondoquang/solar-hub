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
def test_order_stats_totals_and_by_status():
    from apps.orders.tests.factories import OrderFactory

    site = SiteFactory()
    OrderFactory.create_batch(3, site=site, status="processing", total="100000.00")
    OrderFactory.create_batch(2, site=site, status="completed", total="50000.00")
    stats = services.order_stats(Order.objects.all())
    assert stats["total"] == 5
    assert str(stats["revenue"]) == "400000.00"
    assert stats["by_status"] == {"processing": 3, "completed": 2}
