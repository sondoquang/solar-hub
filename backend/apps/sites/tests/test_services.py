import httpx
import pytest

from apps.integrations.woocommerce import WooClient
from apps.sites import services
from apps.sites.crypto import decrypt_secret
from apps.sites.models import Site

from .factories import SiteFactory


@pytest.mark.django_db
def test_create_site_encrypts_secret():
    site = services.create_site(
        name="Shop",
        base_url="https://shop.example.com",
        consumer_key="ck_x",
        consumer_secret="cs_plain",
    )
    assert bytes(site.consumer_secret_enc) != b"cs_plain"
    assert decrypt_secret(site.consumer_secret_enc) == "cs_plain"


@pytest.mark.django_db
def test_test_connection_success(monkeypatch):
    monkeypatch.setattr(WooClient, "system_status", lambda self: {"environment": {}})
    site = SiteFactory()
    result = services.test_connection(site)
    site.refresh_from_db()
    assert result["ok"] is True
    assert site.status == Site.Status.UP
    assert site.last_checked_at is not None


@pytest.mark.django_db
def test_test_connection_failure(monkeypatch):
    def boom(self):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(WooClient, "system_status", boom)
    site = SiteFactory()
    result = services.test_connection(site)
    site.refresh_from_db()
    assert result["ok"] is False
    assert site.status == Site.Status.DOWN
