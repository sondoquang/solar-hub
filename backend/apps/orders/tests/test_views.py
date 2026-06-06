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
def test_orders_are_read_only(client):
    """Orders are pulled in, not created by hand — no write endpoint."""
    resp = client.post("/api/orders/", {}, format="json")
    assert resp.status_code == 405


@pytest.mark.django_db
def test_poll_now_dispatches(client, monkeypatch):
    class _Result:
        id = "task-123"

    called = {}

    def _delay():
        called["hit"] = True
        return _Result()

    monkeypatch.setattr("apps.sync.tasks.poll_all_orders.delay", _delay)
    resp = client.post("/api/orders/poll_now/")
    assert resp.status_code == 200
    assert resp.data["task_id"] == "task-123"
    assert called.get("hit") is True
