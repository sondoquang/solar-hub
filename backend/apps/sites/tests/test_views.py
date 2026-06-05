import pytest
from rest_framework.test import APIClient

from apps.integrations.woocommerce import WooClient
from apps.sites.crypto import decrypt_secret
from apps.sites.models import Site

from .factories import SiteFactory


@pytest.fixture
def client():
    return APIClient()


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
def test_test_connection_action(client, monkeypatch):
    monkeypatch.setattr(WooClient, "system_status", lambda self: {"environment": {}})
    site = SiteFactory()
    resp = client.post(f"/api/sites/{site.id}/test_connection/")
    assert resp.status_code == 200
    assert resp.data["ok"] is True
    assert resp.data["status"] == "up"
