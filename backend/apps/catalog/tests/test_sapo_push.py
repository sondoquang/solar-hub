"""End-to-end-ish push to a Sapo site: a REAL SapoClient (faked httpx) behind
``client_for_site``, proving the adapter's Woo-shaped responses flow through
``push_products_to_site`` unchanged — mappings saved, unsupported types
reported as per-item failures in the SyncLog (status PARTIAL)."""

import pytest

from apps.catalog import services
from apps.catalog.models import ProductMapping
from apps.integrations import sapo
from apps.sites.models import Site
from apps.sites.tests.factories import SiteFactory
from apps.sync.models import SyncLog

from .factories import MasterProductFactory


class _FakeSapoHttp:
    """Minimal Sapo store: collections empty, every create succeeds."""

    def __init__(self):
        self.calls = []
        self._next_id = 9000

    def __call__(self, method, url, *, json=None, params=None, auth=None, timeout=None):
        self.calls.append((method, url))
        if method == "GET" and "/custom_collections.json" in url:
            return _Resp(200, {"custom_collections": []})
        if method == "POST" and "/custom_collections.json" in url:
            self._next_id += 1
            # Sapo custom_collection carries the name in ``name`` (NOT Shopify's
            # ``title``); match the real SapoClient.batch_categories payload.
            name = json["custom_collection"]["name"]
            return _Resp(201, {"custom_collection": {"id": self._next_id, "name": name}})
        if method == "POST" and "/products.json" in url:
            self._next_id += 1
            return _Resp(201, {"product": {"id": self._next_id}})
        if method == "POST" and "/collects.json" in url:
            return _Resp(201, {"collect": {"id": 1}})
        return _Resp(200, {})


class _Resp:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json = json_data
        self.headers = {}
        self.text = ""

    def json(self):
        return self._json

    def raise_for_status(self):
        assert self.status_code < 400


@pytest.mark.django_db
def test_push_to_sapo_site_maps_simple_and_reports_grouped_as_failure(
    monkeypatch, settings
):
    settings.SAPO_THROTTLE_SECONDS = 0  # no pacing in tests
    site = SiteFactory(platform=Site.Platform.SAPO)
    simple = MasterProductFactory(sku="SP-SIMPLE")
    grouped = MasterProductFactory(sku="SP-GROUPED", type="grouped", grouped_skus=["SP-SIMPLE"])

    fake = _FakeSapoHttp()
    monkeypatch.setattr(sapo._POOL, "request", fake)

    result = services.push_products_to_site(site, masters=[simple, grouped])

    # the simple product landed and is mapped to its Sapo product id
    mapping = ProductMapping.objects.get(master=simple, site=site)
    assert mapping.woo_product_id >= 9000
    assert result["created"] == 1
    # the grouped product is impossible on Sapo → no mapping, but visible
    assert not ProductMapping.objects.filter(master=grouped, site=site).exists()

    log = SyncLog.objects.get(site=site, operation="push_products")
    assert log.status == SyncLog.Status.PARTIAL
    failed = log.detail["failed"]
    assert any(
        f["sku"] == "SP-GROUPED" and f["code"] == "sapo_unsupported_type" for f in failed
    )
    # the referenced category was created as a custom collection first
    assert any("/custom_collections.json" in url for method, url in fake.calls if method == "POST")
