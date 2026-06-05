import pytest

from apps.integrations.woocommerce import WooClient
from apps.sites.crypto import decrypt_secret

from .factories import SiteFactory


@pytest.mark.django_db
def test_bulk_test_connections(client, monkeypatch):
    monkeypatch.setattr(WooClient, "system_status", lambda self: {"environment": {}})
    s1, s2 = SiteFactory(), SiteFactory()
    resp = client.post(
        "/api/sites/test_connections/", {"ids": [s1.id, s2.id]}, format="json"
    )
    assert resp.status_code == 200
    results = resp.data["results"]
    assert len(results) == 2
    assert all(r["ok"] for r in results)


@pytest.mark.django_db
def test_update_changes_name_keeps_secret(client):
    site = SiteFactory()
    resp = client.patch(f"/api/sites/{site.id}/", {"name": "Renamed"}, format="json")
    assert resp.status_code == 200
    site.refresh_from_db()
    assert site.name == "Renamed"
    # secret unchanged (no consumer_secret sent)
    assert decrypt_secret(site.consumer_secret_enc) == "cs_secret"


@pytest.mark.django_db
def test_update_rotates_secret_when_provided(client):
    site = SiteFactory()
    resp = client.patch(
        f"/api/sites/{site.id}/", {"consumer_secret": "new_secret"}, format="json"
    )
    assert resp.status_code == 200
    site.refresh_from_db()
    assert decrypt_secret(site.consumer_secret_enc) == "new_secret"
