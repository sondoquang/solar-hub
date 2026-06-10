import pytest

from apps.sites.tests.factories import HostingFactory, SiteFactory

from .factories import OrderFactory


@pytest.mark.django_db
def test_list_returns_flattened_site(client):
    site = SiteFactory(name="solarhub.com.vn")
    OrderFactory(site=site)
    resp = client.get("/api/orders/")
    assert resp.status_code == 200
    rows = resp.data["results"]
    assert rows[0]["site_name"] == "solarhub.com.vn"
    assert "raw" not in rows[0]  # internal payload not exposed in the list


@pytest.mark.django_db
def test_filter_by_status_site_hosting(client):
    hosting = HostingFactory()
    s1 = SiteFactory(hosting=hosting)
    s2 = SiteFactory(hosting=None)
    OrderFactory(site=s1, status="processing")
    OrderFactory(site=s2, status="completed")
    assert client.get("/api/orders/", {"status": "processing"}).data["count"] == 1
    assert client.get("/api/orders/", {"site": s1.id}).data["count"] == 1
    assert client.get("/api/orders/", {"hosting": hosting.id}).data["count"] == 1
    assert client.get("/api/orders/", {"hosting": "none"}).data["count"] == 1


@pytest.mark.django_db
def test_filter_by_forwarded(client):
    OrderFactory(forwarded=True)
    OrderFactory(forwarded=False)
    assert client.get("/api/orders/", {"forwarded": "true"}).data["count"] == 1
    assert client.get("/api/orders/", {"forwarded": "false"}).data["count"] == 1


@pytest.mark.django_db
def test_search_matches_number_and_customer(client):
    OrderFactory(number="A-999", customer_name="Phạm Văn C")
    OrderFactory(number="B-111", customer_name="Lê Thị D")
    resp = client.get("/api/orders/", {"search": "A-999"})
    assert resp.data["count"] == 1
    resp = client.get("/api/orders/", {"search": "Phạm"})
    assert resp.data["count"] == 1


@pytest.mark.django_db
def test_ordering_by_total(client):
    OrderFactory(total="100000.00")
    OrderFactory(total="300000.00")
    resp = client.get("/api/orders/", {"ordering": "total"})
    totals = [r["total"] for r in resp.data["results"]]
    assert totals == ["100000.00", "300000.00"]


@pytest.mark.django_db
def test_stats_endpoint(client):
    OrderFactory(status="processing", total="100000.00", forwarded=False)
    OrderFactory(status="completed", total="50000.00", forwarded=True)
    resp = client.get("/api/orders/stats/")
    assert resp.status_code == 200
    assert resp.data["total"] == 2
    assert str(resp.data["revenue"]) == "150000.00"
    assert resp.data["not_forwarded"] == 1
    assert resp.data["by_status"] == {"processing": 1, "completed": 1}


@pytest.mark.django_db
def test_export_pdf_returns_pdf(client):
    OrderFactory(number="A-1")
    OrderFactory(number="A-2")
    resp = client.get("/api/orders/export_pdf/")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/pdf"
    body = b"".join(resp.streaming_content) if resp.streaming else resp.content
    assert body[:5] == b"%PDF-"  # valid PDF magic bytes
    assert "attachment" in resp["Content-Disposition"]


@pytest.mark.django_db
def test_export_pdf_restricts_to_ids(client):
    o1 = OrderFactory(number="KEEP")
    OrderFactory(number="DROP")
    resp = client.get("/api/orders/export_pdf/", {"ids": str(o1.id)})
    assert resp.status_code == 200
    # A single id names the file after that order's number.
    assert "don-hang-KEEP.pdf" in resp["Content-Disposition"]


@pytest.mark.django_db
def test_export_pdf_honours_filters(client):
    """Without ids, the export follows the active list filters."""
    OrderFactory(status="processing")
    OrderFactory(status="completed")
    # filtered to one order → multi-order filename rule does not apply
    resp = client.get("/api/orders/export_pdf/", {"status": "completed"})
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/pdf"


@pytest.mark.django_db
def test_orders_are_read_only(client):
    """Orders are pulled in, not created by hand — no write endpoint."""
    resp = client.post("/api/orders/", {}, format="json")
    assert resp.status_code == 405


@pytest.mark.django_db
def test_poll_now_dispatches_default_status(client, monkeypatch):
    class _Result:
        id = "task-123"

    called = {}

    def _delay(**kwargs):
        called.update(kwargs)
        return _Result()

    monkeypatch.setattr("apps.sync.tasks.poll_all_orders.delay", _delay)
    resp = client.post("/api/orders/poll_now/")
    assert resp.status_code == 200
    assert resp.data["task_id"] == "task-123"
    assert resp.data["status"] == "processing"
    # No body → default status, whole fleet, no date window.
    assert called == {
        "status": "processing",
        "site_ids": None,
        "date_from": None,
        "date_to": None,
    }


@pytest.mark.django_db
def test_poll_now_passes_status_and_sites(client, monkeypatch):
    class _Result:
        id = "task-9"

    called = {}

    def _delay(**kwargs):
        called.update(kwargs)
        return _Result()

    monkeypatch.setattr("apps.sync.tasks.poll_all_orders.delay", _delay)
    resp = client.post(
        "/api/orders/poll_now/",
        {"status": "completed", "sites": [1, 2]},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["status"] == "completed"
    assert called == {
        "status": "completed",
        "site_ids": [1, 2],
        "date_from": None,
        "date_to": None,
    }


@pytest.mark.django_db
def test_poll_now_passes_date_range(client, monkeypatch):
    class _Result:
        id = "task-d"

    called = {}

    def _delay(**kwargs):
        called.update(kwargs)
        return _Result()

    monkeypatch.setattr("apps.sync.tasks.poll_all_orders.delay", _delay)
    resp = client.post(
        "/api/orders/poll_now/",
        {"status": "completed", "date_from": "2026-06-01", "date_to": "2026-06-03"},
        format="json",
    )
    assert resp.status_code == 200
    assert called == {
        "status": "completed",
        "site_ids": None,
        "date_from": "2026-06-01",
        "date_to": "2026-06-03",
    }


@pytest.mark.django_db
def test_poll_now_rejects_bad_date(client, monkeypatch):
    def _boom(**kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("delay should not be called for an invalid date")

    monkeypatch.setattr("apps.sync.tasks.poll_all_orders.delay", _boom)
    resp = client.post(
        "/api/orders/poll_now/",
        {"date_from": "01/06/2026"},
        format="json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_poll_now_rejects_unknown_status(client, monkeypatch):
    def _boom(**kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("delay should not be called for an invalid status")

    monkeypatch.setattr("apps.sync.tasks.poll_all_orders.delay", _boom)
    resp = client.post(
        "/api/orders/poll_now/", {"status": "bogus"}, format="json"
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_poll_now_rejects_bad_sites(client, monkeypatch):
    def _boom(**kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("delay should not be called for invalid sites")

    monkeypatch.setattr("apps.sync.tasks.poll_all_orders.delay", _boom)
    resp = client.post(
        "/api/orders/poll_now/",
        {"status": "processing", "sites": "not-a-list"},
        format="json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_complete_pushes_status_and_returns_order(client, monkeypatch):
    order = OrderFactory(woo_order_id=77, status="processing")

    class _Client:
        def update_order(self, woo_order_id, *, status):
            return {"id": woo_order_id, "number": "77", "status": status}

    monkeypatch.setattr("apps.sites.services.client_for_site", lambda s: _Client())
    resp = client.post(f"/api/orders/{order.id}/complete/")
    assert resp.status_code == 200
    assert resp.data["status"] == "completed"
    order.refresh_from_db()
    assert order.status == "completed"


@pytest.mark.django_db
def test_cancel_pushes_status_and_returns_order(client, monkeypatch):
    order = OrderFactory(woo_order_id=66, status="processing")

    class _Client:
        def update_order(self, woo_order_id, *, status):
            return {"id": woo_order_id, "number": "66", "status": status}

    monkeypatch.setattr("apps.sites.services.client_for_site", lambda s: _Client())
    resp = client.post(f"/api/orders/{order.id}/cancel/")
    assert resp.status_code == 200
    assert resp.data["status"] == "cancelled"
    order.refresh_from_db()
    assert order.status == "cancelled"


@pytest.mark.django_db
def test_cancel_rejects_terminal_status(client, monkeypatch):
    order = OrderFactory(status="completed")

    def _boom(s):  # pragma: no cover - must not be reached
        raise AssertionError("WooCommerce must not be called for a bad transition")

    monkeypatch.setattr("apps.sites.services.client_for_site", _boom)
    resp = client.post(f"/api/orders/{order.id}/cancel/")
    assert resp.status_code == 409
    order.refresh_from_db()
    assert order.status == "completed"


@pytest.mark.django_db
def test_forward_marks_order_and_is_one_way(client):
    order = OrderFactory(status="processing", forwarded=False)
    resp = client.post(f"/api/orders/{order.id}/forward/")
    assert resp.status_code == 200
    assert resp.data["forwarded"] is True
    assert resp.data["forwarded_at"] is not None
    order.refresh_from_db()
    assert order.forwarded is True
    # Idempotent: a second call still 200 and stays forwarded (no un-forward path).
    resp2 = client.post(f"/api/orders/{order.id}/forward/")
    assert resp2.status_code == 200
    assert resp2.data["forwarded"] is True


@pytest.mark.django_db
def test_forward_bulk_forwards_selected_only(client):
    a = OrderFactory(status="processing", forwarded=False)
    b = OrderFactory(status="processing", forwarded=False)
    untouched = OrderFactory(status="processing", forwarded=False)
    resp = client.post(
        "/api/orders/forward_bulk/", {"ids": [a.id, b.id]}, format="json"
    )
    assert resp.status_code == 200
    assert resp.data["forwarded"] == 2
    a.refresh_from_db()
    b.refresh_from_db()
    untouched.refresh_from_db()
    assert a.forwarded and b.forwarded
    assert untouched.forwarded is False


@pytest.mark.django_db
def test_forward_bulk_rejects_bad_ids(client):
    resp = client.post(
        "/api/orders/forward_bulk/", {"ids": "not-a-list"}, format="json"
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_complete_rejects_non_processing(client, monkeypatch):
    order = OrderFactory(status="pending")

    def _boom(s):  # pragma: no cover - must not be reached
        raise AssertionError("WooCommerce must not be called for a bad transition")

    monkeypatch.setattr("apps.sites.services.client_for_site", _boom)
    resp = client.post(f"/api/orders/{order.id}/complete/")
    assert resp.status_code == 409
    order.refresh_from_db()
    assert order.status == "pending"


@pytest.mark.django_db
def test_filter_by_classification(client):
    OrderFactory(classification="genuine")
    OrderFactory(classification="spam")
    assert client.get("/api/orders/", {"classification": "spam"}).data["count"] == 1
    assert client.get("/api/orders/", {"classification": "genuine"}).data["count"] == 1


@pytest.mark.django_db
def test_serializer_exposes_classification(client):
    OrderFactory(
        classification="suspicious",
        risk_score=40,
        risk_reasons=["phone_invalid", "velocity_phone"],
    )
    row = client.get("/api/orders/").data["results"][0]
    assert row["classification"] == "suspicious"
    assert row["classification_display"] == "Nghi ngờ"
    assert row["risk_score"] == 40
    assert row["risk_reasons"] == ["phone_invalid", "velocity_phone"]
    # Codes are mapped to Vietnamese labels for the UI.
    assert "SĐT không đúng định dạng Việt Nam" in row["risk_reasons_display"]


@pytest.mark.django_db
def test_stats_by_classification(client):
    OrderFactory(classification="genuine")
    OrderFactory(classification="spam")
    OrderFactory(classification="spam")
    resp = client.get("/api/orders/stats/")
    assert resp.data["by_classification"] == {"genuine": 1, "spam": 2}
