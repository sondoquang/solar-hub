import pytest

from apps.integrations.woocommerce import WooClient
from apps.sites.models import Hosting, Site

from .factories import HostingFactory, SiteFactory


@pytest.mark.django_db
def test_create_and_list_hosting(client):
    resp = client.post(
        "/api/hostings/",
        {"name": "Server A", "provider": "TenTen", "check_concurrency": 3},
        format="json",
    )
    assert resp.status_code == 201
    assert Hosting.objects.filter(name="Server A", check_concurrency=3).exists()

    resp = client.get("/api/hostings/")
    assert resp.status_code == 200
    row = resp.data["results"][0]
    assert row["site_count"] == 0
    assert row["status_counts"] == {"up": 0, "down": 0, "unknown": 0}


@pytest.mark.django_db
def test_hosting_search_matches_name_provider_account(client):
    HostingFactory(name="Server A", provider="TenTen", account_username="alpha")
    HostingFactory(name="Server B", provider="Mat Bao", account_username="bravo")
    # Match on provider.
    resp = client.get("/api/hostings/", {"search": "tenten"})
    assert [h["name"] for h in resp.data["results"]] == ["Server A"]
    # Match on account_username.
    resp = client.get("/api/hostings/", {"search": "bravo"})
    assert [h["name"] for h in resp.data["results"]] == ["Server B"]
    # No match → empty page.
    resp = client.get("/api/hostings/", {"search": "nonexistent"})
    assert resp.data["count"] == 0


@pytest.mark.django_db
def test_delete_hosting_is_soft(client):
    hosting = HostingFactory()
    resp = client.delete(f"/api/hostings/{hosting.id}/")
    assert resp.status_code == 204
    hosting.refresh_from_db()
    assert hosting.is_deleted is True
    # Hidden from the list endpoint.
    assert client.get("/api/hostings/").data["count"] == 0


@pytest.mark.django_db
def test_hosting_check_action(client, monkeypatch):
    monkeypatch.setattr(WooClient, "system_status", lambda self: {"environment": {}})
    hosting = HostingFactory()
    site = SiteFactory(hosting=hosting)

    resp = client.post(f"/api/hostings/{hosting.id}/check/")
    assert resp.status_code == 200
    assert resp.data["results"][0]["id"] == site.id
    site.refresh_from_db()
    assert site.status == Site.Status.UP


@pytest.mark.django_db
def test_filter_sites_by_hosting(client):
    h1 = HostingFactory()
    grouped = SiteFactory(hosting=h1)
    orphan = SiteFactory(hosting=None)

    by_id = client.get(f"/api/sites/?hosting={h1.id}")
    assert {s["id"] for s in by_id.data["results"]} == {grouped.id}

    none = client.get("/api/sites/?hosting=none")
    assert {s["id"] for s in none.data["results"]} == {orphan.id}

    all_sites = client.get("/api/sites/")
    assert {s["id"] for s in all_sites.data["results"]} == {grouped.id, orphan.id}


@pytest.mark.django_db
def test_create_site_with_hosting(client):
    hosting = HostingFactory()
    resp = client.post(
        "/api/sites/",
        {
            "name": "Shop",
            "base_url": "https://shop-new.example.com",
            "consumer_key": "ck_x",
            "consumer_secret": "cs_secret",
            "hosting": hosting.id,
        },
        format="json",
    )
    assert resp.status_code == 201
    assert resp.data["hosting"] == hosting.id
    assert resp.data["hosting_name"] == hosting.name
