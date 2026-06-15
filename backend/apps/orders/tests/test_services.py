import httpx
import pytest

from apps.integrations import sapo
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


def test_normalize_order_consumes_sapo_mapped_payload():
    """Cross-module contract: a Sapo order mapped to the Woo shape by
    ``SapoClient._sapo_order_to_woo`` must be fully consumable here, so the poll
    and spam classifier work on Sapo sites with no Sapo-specific branch."""
    site = SiteFactory.build()
    raw = sapo._sapo_order_to_woo(
        {
            "id": 9001,
            "name": "#SP-9001",
            "status": "open",
            "currency": "VND",
            "total_price": "500000.00",
            "created_on": "2026-06-01T03:00:00Z",
            "modified_on": "2026-06-02T05:00:00Z",
            "email": "khach@example.com",
            "note": "Gọi trước khi giao",
            "customer": {"first_name": "Văn", "last_name": "An", "phone": "0911222333"},
            "billing_address": {"address1": "12 Lê Lợi", "province": "Đà Nẵng"},
            "line_items": [
                {"sku": "PIN-100", "title": "Pin 100W", "quantity": 2, "price": "150000"}
            ],
        }
    )
    data = services.normalize_order(site, raw)
    assert data["status"] == "processing"  # open → processing
    assert data["customer_name"] == "Văn An"
    assert data["customer_phone"] == "0911222333"
    assert data["customer_email"] == "khach@example.com"
    assert "Lê Lợi" in data["shipping_address"]
    assert data["customer_note"] == "Gọi trước khi giao"
    assert data["line_items"] == [
        {"sku": "PIN-100", "name": "Pin 100W", "quantity": 2, "total": "300000.0"}
    ]
    assert data["date_created_woo"].year == 2026
    assert data["date_modified_woo"].day == 2


@pytest.mark.django_db
def test_sites_for_order_poll_excludes_sapo_when_disabled(settings):
    from apps.sites.models import Site

    settings.SAPO_ORDER_POLL_ENABLED = False
    woo = SiteFactory()
    SiteFactory(platform=Site.Platform.SAPO, sapo_store_host="a.mysapo.net")
    assert services.sites_for_order_poll() == [woo.id]


@pytest.mark.django_db
def test_sites_for_order_poll_dedupes_sapo_by_store_host(settings):
    """Several Sapo storefront domains resolving to one mysapo host = one store
    (even with different API keys) → only the lowest-id site is polled."""
    from apps.sites.models import Site

    settings.SAPO_ORDER_POLL_ENABLED = True
    woo = SiteFactory()
    # store A: two domains, DIFFERENT keys, same resolved host → polled once.
    a1 = SiteFactory(
        platform=Site.Platform.SAPO, consumer_key="k1", sapo_store_host="a.mysapo.net"
    )
    SiteFactory(
        platform=Site.Platform.SAPO, consumer_key="k2", sapo_store_host="a.mysapo.net"
    )
    # store B: a distinct host → its own representative.
    b1 = SiteFactory(platform=Site.Platform.SAPO, sapo_store_host="b.mysapo.net")

    result = services.sites_for_order_poll()
    assert woo.id in result
    assert a1.id in result  # lowest-id of store A
    assert b1.id in result
    assert len([i for i in result if i in {a1.id, b1.id}]) == 2
    assert len(result) == 3


@pytest.mark.django_db
def test_sites_for_order_poll_platform_woocommerce_excludes_sapo(settings):
    """``platform="woocommerce"`` polls only Woo sites even when the Sapo gate is
    on — the WooCommerce "Đồng bộ ngay" screen must never cross-pull Sapo."""
    from apps.sites.models import Site

    settings.SAPO_ORDER_POLL_ENABLED = True
    woo = SiteFactory()
    SiteFactory(platform=Site.Platform.SAPO, sapo_store_host="a.mysapo.net")
    assert services.sites_for_order_poll(platform="woocommerce") == [woo.id]


@pytest.mark.django_db
def test_sites_for_order_poll_platform_sapo_excludes_woo(settings):
    """``platform="sapo"`` polls only Sapo sites (still gated + deduped)."""
    from apps.sites.models import Site

    settings.SAPO_ORDER_POLL_ENABLED = True
    SiteFactory()  # woo — must not appear
    sapo = SiteFactory(platform=Site.Platform.SAPO, sapo_store_host="a.mysapo.net")
    assert services.sites_for_order_poll(platform="sapo") == [sapo.id]


@pytest.mark.django_db
def test_sites_for_order_poll_platform_sapo_respects_gate(settings):
    """``platform="sapo"`` while the gate is off yields nothing (the pause switch
    still wins over an explicit platform scope)."""
    from apps.sites.models import Site

    settings.SAPO_ORDER_POLL_ENABLED = False
    SiteFactory()
    SiteFactory(platform=Site.Platform.SAPO, sapo_store_host="a.mysapo.net")
    assert services.sites_for_order_poll(platform="sapo") == []


@pytest.mark.django_db
def test_sites_for_order_poll_unresolved_host_not_merged(settings):
    """Sapo sites with no resolved host yet must each be polled (never merged on
    a shared empty host) so orders aren't silently dropped before health-check."""
    from apps.sites.models import Site

    settings.SAPO_ORDER_POLL_ENABLED = True
    s1 = SiteFactory(platform=Site.Platform.SAPO, sapo_store_host="")
    s2 = SiteFactory(platform=Site.Platform.SAPO, sapo_store_host="")
    result = services.sites_for_order_poll()
    assert s1.id in result and s2.id in result
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
        financial_status=None,
    ):
        if self._capture is not None:
            self._capture["status"] = status
            self._capture["after"] = after
            self._capture["before"] = before
            self._capture["modified_after"] = modified_after
            self._capture["financial_status"] = financial_status
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


@pytest.mark.django_db
def test_poll_site_logs_only_when_run_id_set(monkeypatch):
    """The periodic poll (run_id=None) writes no SyncLog — a row every ~3 min per
    site would bloat the audit table — but a manual run (run_id set) records each
    site's outcome for the progress banner."""
    import uuid

    from apps.sync.models import SyncLog

    site = SiteFactory()
    monkeypatch.setattr(
        "apps.sites.services.client_for_site",
        lambda s: _FakeClient([_woo_order(order_id=1)]),
    )

    # Periodic poll: no run_id → no audit row.
    services.poll_site(site, "processing")
    assert not SyncLog.objects.filter(operation=services.POLL_OPERATION).exists()

    # Manual run: one SUCCESS row stamped with the run.
    run_id = uuid.uuid4()
    services.poll_site(site, "processing", run_id=run_id, triggered_by_id=None)
    log = SyncLog.objects.get(operation=services.POLL_OPERATION, run_id=run_id)
    assert log.status == SyncLog.Status.SUCCESS
    assert log.started_at is not None
    assert log.detail["status_polled"] == "processing"


@pytest.mark.django_db
def test_poll_site_logs_error_row_for_tracked_run(monkeypatch):
    """A failed site in a tracked run still writes a row (ERROR) so the banner
    counts it as finished and the run can complete."""
    import uuid

    from apps.sync.models import SyncLog

    site = SiteFactory()

    def _boom(s):
        class _C:
            def list_orders(self, **kw):
                raise httpx.ConnectError("down")

        return _C()

    monkeypatch.setattr("apps.sites.services.client_for_site", _boom)
    run_id = uuid.uuid4()
    services.poll_site(site, "processing", run_id=run_id)

    log = SyncLog.objects.get(operation=services.POLL_OPERATION, run_id=run_id)
    assert log.status == SyncLog.Status.ERROR
    assert log.error == "ConnectError"


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


# --- Payment status (Sapo) ---------------------------------------------------


def test_normalize_order_maps_financial_status_to_payment_status():
    site = SiteFactory.build()
    raw = sapo._sapo_order_to_woo(
        {"id": 1, "status": "open", "financial_status": "pending", "total_price": "1"}
    )
    assert services.normalize_order(site, raw)["payment_status"] == "pending"


def test_normalize_order_payment_status_blank_for_woo():
    # A WooCommerce payload has no financial_status → payment_status stays "".
    site = SiteFactory.build()
    assert services.normalize_order(site, _woo_order())["payment_status"] == ""


@pytest.mark.django_db
def test_poll_site_filters_unpaid_for_sapo(monkeypatch):
    from apps.sites.models import Site

    site = SiteFactory(platform=Site.Platform.SAPO, sapo_store_host="a.mysapo.net")
    capture = {}
    monkeypatch.setattr(
        "apps.sites.services.client_for_site",
        lambda s: _FakeClient([], capture=capture),
    )
    services.poll_site(site, "processing")
    assert capture["financial_status"] == "unpaid"


@pytest.mark.django_db
def test_poll_site_no_payment_filter_for_woo(monkeypatch):
    site = SiteFactory()  # platform defaults to WooCommerce
    capture = {}
    monkeypatch.setattr(
        "apps.sites.services.client_for_site",
        lambda s: _FakeClient([], capture=capture),
    )
    services.poll_site(site, "processing")
    assert capture["financial_status"] is None


class _FakePaidClient:
    """A SapoClient stand-in for mark_order_paid: records the call and returns
    the order Woo-shaped with financial_status=paid."""

    def __init__(self, raw, *, capture=None):
        self._raw = raw
        self._capture = capture

    def mark_order_paid(self, woo_order_id, *, amount):
        if self._capture is not None:
            self._capture["woo_order_id"] = woo_order_id
            self._capture["amount"] = amount
        return {**self._raw, "financial_status": "paid"}


@pytest.mark.django_db
def test_mark_order_paid_records_transaction_and_syncs(monkeypatch):
    from apps.orders.tests.factories import OrderFactory
    from apps.sites.models import Site

    site = SiteFactory(platform=Site.Platform.SAPO)
    order = OrderFactory(
        site=site, woo_order_id=44, status="processing",
        payment_status="pending", total="409.94",
    )
    capture = {}
    raw = sapo._sapo_order_to_woo(
        {"id": 44, "status": "open", "total_price": "409.94", "financial_status": "paid"}
    )
    monkeypatch.setattr(
        "apps.sites.services.client_for_site",
        lambda s: _FakePaidClient(raw, capture=capture),
    )

    result = services.mark_order_paid(order)
    assert result.payment_status == "paid"
    # Amount sent to Sapo is the order total as a string.
    assert capture == {"woo_order_id": 44, "amount": "409.94"}
    result.refresh_from_db()
    assert result.payment_status == "paid"


@pytest.mark.django_db
def test_mark_order_paid_rejects_non_sapo(monkeypatch):
    from apps.orders.tests.factories import OrderFactory

    order = OrderFactory(payment_status="pending")  # WooCommerce site

    def _boom(s):  # pragma: no cover - must not be reached
        raise AssertionError("client must not be built for a non-Sapo order")

    monkeypatch.setattr("apps.sites.services.client_for_site", _boom)
    with pytest.raises(services.InvalidStatusTransition):
        services.mark_order_paid(order)


@pytest.mark.django_db
def test_mark_order_paid_rejects_cancelled(monkeypatch):
    from apps.orders.tests.factories import OrderFactory
    from apps.sites.models import Site

    site = SiteFactory(platform=Site.Platform.SAPO)
    order = OrderFactory(site=site, status="cancelled", payment_status="pending")

    def _boom(s):  # pragma: no cover - must not be reached
        raise AssertionError("client must not be built for a cancelled order")

    monkeypatch.setattr("apps.sites.services.client_for_site", _boom)
    with pytest.raises(services.InvalidStatusTransition):
        services.mark_order_paid(order)


@pytest.mark.django_db
def test_mark_order_paid_rejects_already_paid(monkeypatch):
    from apps.orders.tests.factories import OrderFactory
    from apps.sites.models import Site

    site = SiteFactory(platform=Site.Platform.SAPO)
    order = OrderFactory(site=site, status="processing", payment_status="paid")

    def _boom(s):  # pragma: no cover - must not be reached
        raise AssertionError("client must not be built for an already-paid order")

    monkeypatch.setattr("apps.sites.services.client_for_site", _boom)
    with pytest.raises(services.InvalidStatusTransition):
        services.mark_order_paid(order)


@pytest.mark.django_db
def test_list_orders_qs_filters_by_platform_and_payment_status():
    from apps.orders.tests.factories import OrderFactory
    from apps.sites.models import Site

    woo = SiteFactory()
    sapo_site = SiteFactory(platform=Site.Platform.SAPO)
    OrderFactory(site=woo, payment_status="")
    unpaid = OrderFactory(site=sapo_site, payment_status="pending")
    OrderFactory(site=sapo_site, payment_status="paid")

    qs = services.list_orders_qs(
        Order.objects.all(), {"platform": "sapo", "payment_status": "unpaid"}
    )
    assert list(qs.values_list("id", flat=True)) == [unpaid.id]


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
