import httpx
import pytest

from apps.integrations.sapo import SapoClient
from apps.integrations.woocommerce import WooClient
from apps.sites import services
from apps.sites.crypto import decrypt_secret
from apps.sites.models import Site

from .factories import HostingFactory, SiteFactory


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


@pytest.mark.django_db
def test_test_connection_sapo_success(monkeypatch):
    # client_for_site dispatches on platform, so a Sapo site exercises SapoClient.
    monkeypatch.setattr(SapoClient, "system_status", lambda self: {})
    site = SiteFactory(platform=Site.Platform.SAPO)
    result = services.test_connection(site)
    site.refresh_from_db()
    assert result["ok"] is True
    assert site.status == Site.Status.UP


@pytest.mark.django_db
def test_client_for_site_sapo_uses_canonical_host_when_known():
    # Once the canonical *.mysapo.net host is discovered, the client must target
    # it directly: the storefront domain bounces per-order admin paths to login.
    site = SiteFactory(
        platform=Site.Platform.SAPO,
        base_url="https://shop.example.com",
        sapo_store_host="shop-x.mysapo.net",
    )
    client = services.client_for_site(site)
    assert client.base == "https://shop-x.mysapo.net/admin"


@pytest.mark.django_db
def test_client_for_site_sapo_falls_back_to_base_url_before_resolved():
    # A site not yet health-checked (blank host) uses base_url + redirect-following.
    site = SiteFactory(
        platform=Site.Platform.SAPO,
        base_url="https://shop.example.com",
        sapo_store_host="",
    )
    client = services.client_for_site(site)
    assert client.base == "https://shop.example.com/admin"


@pytest.mark.django_db
def test_test_connection_sapo_persists_store_host(monkeypatch):
    """A successful Sapo health-check stores the canonical *.mysapo.net host the
    client landed on — the dedup key the order poll groups storefronts by."""
    def fake_status(self):
        self.resolved_host = "store-x.mysapo.net"  # what _send would record
        return {}

    monkeypatch.setattr(SapoClient, "system_status", fake_status)
    site = SiteFactory(platform=Site.Platform.SAPO)
    services.test_connection(site)
    site.refresh_from_db()
    assert site.sapo_store_host == "store-x.mysapo.net"


@pytest.mark.django_db
def test_test_connection_http_status_error_records_status_and_body(monkeypatch):
    def boom(self):
        response = httpx.Response(
            401,
            text="unauthorized",
            request=httpx.Request("GET", "https://shop.example.com"),
        )
        raise httpx.HTTPStatusError("401", request=response.request, response=response)

    monkeypatch.setattr(WooClient, "system_status", boom)
    site = SiteFactory()
    result = services.test_connection(site)
    site.refresh_from_db()
    assert result["ok"] is False
    assert site.status == Site.Status.DOWN
    assert "401" in result["detail"]
    assert "unauthorized" in result["detail"]


@pytest.mark.django_db
def test_check_hosting_checks_primary_sites_first(monkeypatch):
    # concurrency=1 → sequential, so the check order is the submission order.
    hosting = HostingFactory(check_concurrency=1)
    normal = SiteFactory(hosting=hosting)
    primary = SiteFactory(hosting=hosting, is_primary=True)
    checked = []
    monkeypatch.setattr(
        services,
        "test_connection",
        lambda site, **kwargs: checked.append(site.id) or {"ok": True},
    )
    services.check_hosting(hosting.id, check_type="manual")
    assert checked == [primary.id, normal.id]
