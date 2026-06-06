import pytest

from apps.monitoring.models import HealthCheck
from apps.sites.tests.factories import HostingFactory, SiteFactory

from .factories import HealthCheckFactory


@pytest.mark.django_db
def test_list_returns_flattened_site_and_actor(client, user):
    site = SiteFactory(name="solarhub.com.vn")
    HealthCheckFactory(site=site, performed_by=None)
    HealthCheckFactory(site=site, performed_by=user, check_type="manual")
    resp = client.get("/api/healthchecks/")
    assert resp.status_code == 200
    rows = resp.data["results"]
    assert {r["performed_by_name"] for r in rows} == {"Hệ thống", "Nguyễn Văn A"}
    assert all(r["site_name"] == "solarhub.com.vn" for r in rows)


@pytest.mark.django_db
def test_filter_by_status(client):
    HealthCheckFactory(status=HealthCheck.Status.HEALTHY)
    HealthCheckFactory(status=HealthCheck.Status.CRITICAL)
    resp = client.get("/api/healthchecks/", {"status": "critical"})
    assert resp.data["count"] == 1
    assert resp.data["results"][0]["status"] == "critical"


@pytest.mark.django_db
def test_filter_by_site_and_hosting(client):
    hosting = HostingFactory()
    s1 = SiteFactory(hosting=hosting)
    s2 = SiteFactory(hosting=None)
    HealthCheckFactory(site=s1)
    HealthCheckFactory(site=s2)
    resp = client.get("/api/healthchecks/", {"site": s1.id})
    assert resp.data["count"] == 1
    resp = client.get("/api/healthchecks/", {"hosting": hosting.id})
    assert resp.data["count"] == 1
    resp = client.get("/api/healthchecks/", {"hosting": "none"})
    assert resp.data["count"] == 1


@pytest.mark.django_db
def test_search_matches_site_name(client):
    HealthCheckFactory(site=SiteFactory(name="Alpha"))
    HealthCheckFactory(site=SiteFactory(name="Bravo"))
    resp = client.get("/api/healthchecks/", {"search": "alph"})
    assert resp.data["count"] == 1
    assert resp.data["results"][0]["site_name"] == "Alpha"


@pytest.mark.django_db
def test_ordering_by_response_time(client):
    HealthCheckFactory(response_time_ms=500)
    HealthCheckFactory(response_time_ms=3000)
    resp = client.get("/api/healthchecks/", {"ordering": "response_time_ms"})
    times = [r["response_time_ms"] for r in resp.data["results"]]
    assert times == [500, 3000]


@pytest.mark.django_db
def test_stats_endpoint(client):
    HealthCheckFactory(status=HealthCheck.Status.HEALTHY)
    HealthCheckFactory(status=HealthCheck.Status.WARNING)
    HealthCheckFactory(status=HealthCheck.Status.CRITICAL)
    resp = client.get("/api/healthchecks/stats/")
    assert resp.status_code == 200
    assert resp.data["total"] == 3
    assert resp.data["healthy"] == 1
    assert resp.data["warning"] == 1
    assert resp.data["critical"] == 1


@pytest.mark.django_db
def test_export_returns_csv(client):
    HealthCheckFactory(site=SiteFactory(name="solarhub.com.vn"))
    resp = client.get("/api/healthchecks/export/")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    body = b"".join(resp.streaming_content).decode("utf-8-sig")
    assert "Website" in body  # header
    assert "solarhub.com.vn" in body


@pytest.mark.django_db
def test_history_is_read_only(client):
    """No create/delete endpoint — the history is append-only audit data."""
    resp = client.post("/api/healthchecks/", {}, format="json")
    assert resp.status_code == 405
