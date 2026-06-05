import pytest

from apps.integrations.woocommerce import WooClient
from apps.sites.crypto import decrypt_secret
from apps.sites.models import Site

from .factories import SiteFactory


@pytest.mark.django_db
def test_create_site_does_not_echo_secret(client):
    resp = client.post(
        "/api/sites/",
        {
            "name": "Shop",
            "base_url": "https://shop.example.com",
            "consumer_key": "ck_x",
            "consumer_secret": "cs_secret",
        },
        format="json",
    )
    assert resp.status_code == 201
    assert "consumer_secret" not in resp.data
    assert "consumer_secret_enc" not in resp.data
    site = Site.objects.get(name="Shop")
    assert decrypt_secret(site.consumer_secret_enc) == "cs_secret"


@pytest.mark.django_db
def test_list_excludes_secret(client):
    SiteFactory()
    resp = client.get("/api/sites/")
    assert resp.status_code == 200
    row = resp.data["results"][0]
    assert "consumer_secret" not in row
    assert "consumer_secret_enc" not in row


@pytest.mark.django_db
def test_list_supports_page_size_param(client):
    SiteFactory.create_batch(3)
    resp = client.get("/api/sites/", {"page_size": 2})
    assert resp.status_code == 200
    assert resp.data["count"] == 3
    assert len(resp.data["results"]) == 2  # client-controlled page size


@pytest.mark.django_db
def test_list_orders_by_name(client):
    SiteFactory(name="Bravo")
    SiteFactory(name="Alpha")
    resp = client.get("/api/sites/", {"ordering": "name"})
    names = [row["name"] for row in resp.data["results"]]
    assert names == ["Alpha", "Bravo"]
    resp = client.get("/api/sites/", {"ordering": "-name"})
    names = [row["name"] for row in resp.data["results"]]
    assert names == ["Bravo", "Alpha"]


@pytest.mark.django_db
def test_list_search_matches_name_and_url(client):
    SiteFactory(name="Alpha Shop", base_url="https://alpha.example.com")
    SiteFactory(name="Bravo Store", base_url="https://bravo.example.com")
    # Match on name (case-insensitive contains).
    resp = client.get("/api/sites/", {"search": "alpha"})
    names = [row["name"] for row in resp.data["results"]]
    assert names == ["Alpha Shop"]
    # Match on base_url too.
    resp = client.get("/api/sites/", {"search": "bravo.example"})
    names = [row["name"] for row in resp.data["results"]]
    assert names == ["Bravo Store"]
    # No match → empty page, not an error.
    resp = client.get("/api/sites/", {"search": "nonexistent"})
    assert resp.data["count"] == 0


@pytest.mark.django_db
def test_stats_returns_global_counts(client):
    SiteFactory(status=Site.Status.UP)
    SiteFactory(status=Site.Status.UP)
    SiteFactory(status=Site.Status.DOWN)
    SiteFactory(status=Site.Status.UNKNOWN)
    resp = client.get("/api/sites/stats/")
    assert resp.status_code == 200
    assert resp.data == {"total": 4, "up": 2, "down": 1, "unknown": 1}


@pytest.mark.django_db
def test_test_connection_action(client, monkeypatch):
    monkeypatch.setattr(WooClient, "system_status", lambda self: {"environment": {}})
    site = SiteFactory()
    resp = client.post(f"/api/sites/{site.id}/test_connection/")
    assert resp.status_code == 200
    assert resp.data["ok"] is True
    assert resp.data["status"] == "up"
