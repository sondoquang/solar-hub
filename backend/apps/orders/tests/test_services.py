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

    def list_orders(self, after=None, status="processing", per_page=100):
        if self._capture is not None:
            self._capture["after"] = after
            self._capture["status"] = status
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
    assert result["error"] is None
    assert Order.objects.filter(site=site).count() == 2
    # First poll has no prior orders → no watermark.
    assert capture["after"] is None

    # Second poll: watermark = newest stored date_created_woo, no new orders.
    capture.clear()
    monkeypatch.setattr(
        "apps.sites.services.client_for_site",
        lambda s: _FakeClient([], capture=capture),
    )
    result2 = services.poll_site(site)
    assert result2["fetched"] == 0
    assert capture["after"] is not None  # watermark sent on subsequent polls


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
