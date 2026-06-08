import httpx
import pytest

from apps.catalog import services
from apps.catalog.models import ProductMapping
from apps.catalog.tests.factories import MasterProductFactory, ProductMappingFactory
from apps.sites.tests.factories import SiteFactory
from apps.sync.models import SyncLog


class _FakeClient:
    """Fake WooClient for unit tests (no HTTP). Echoes ids/skus like /products/batch.

    ``calls`` records every ``batch_products`` invocation so tests can assert how
    the work was split / chunked. Created products are assigned incrementing ids.
    """

    def __init__(self, *, raise_error=False):
        self.calls = []
        self.raise_error = raise_error
        self._next_id = 9000

    def batch_products(self, create=None, update=None, delete=None):
        create, update, delete = create or [], update or [], delete or []
        self.calls.append({"create": create, "update": update, "delete": delete})
        if self.raise_error:
            raise httpx.ConnectError("boom")
        created = []
        for item in create:
            created.append({"id": self._next_id, "sku": item["sku"]})
            self._next_id += 1
        updated = [{"id": item["id"], "sku": item["sku"]} for item in update]
        deleted = [{"id": woo_id} for woo_id in delete]
        return {"create": created, "update": updated, "delete": deleted}


def _patch_client(monkeypatch, fake):
    monkeypatch.setattr("apps.sites.services.client_for_site", lambda site: fake)


# --- pure helpers (no DB) ----------------------------------------------------


def test_normalize_sku_trims_collapses_uppers():
    assert services.normalize_sku("  sp 1  ") == "SP 1"
    assert services.normalize_sku("a\t b\n c") == "A B C"
    assert services.normalize_sku("") == ""


def test_build_product_payload_maps_fields():
    master = MasterProductFactory.build(
        sku="SP-1",
        name="Pin",
        regular_price="150000.00",
        sale_price="120000.00",
        weight="2.5",
        categories=["Pin mặt trời", "Inverter"],
        images=["https://x/1.jpg"],
        status="publish",
        stock_status="instock",
    )
    payload = services.build_product_payload(master)
    assert payload["sku"] == "SP-1"
    assert payload["regular_price"] == "150000.00"  # string for Woo
    assert payload["sale_price"] == "120000.00"
    assert payload["weight"] == "2.5"
    assert payload["categories"] == [{"name": "Pin mặt trời"}, {"name": "Inverter"}]
    assert payload["images"] == [{"src": "https://x/1.jpg"}]


def test_build_product_payload_omits_optional_when_unset():
    master = MasterProductFactory.build(sale_price=None, weight=None)
    payload = services.build_product_payload(master)
    assert "sale_price" not in payload
    assert "weight" not in payload


# --- push_products_to_site ---------------------------------------------------


@pytest.mark.django_db
def test_push_creates_and_maps(monkeypatch):
    site = SiteFactory()
    m1 = MasterProductFactory(sku="SP-1")
    m2 = MasterProductFactory(sku="SP-2")
    fake = _FakeClient()
    _patch_client(monkeypatch, fake)

    result = services.push_products_to_site(site, masters=[m1, m2])

    assert result == {
        "site_id": site.id,
        "created": 2,
        "updated": 0,
        "deleted": 0,
        "error": None,
    }
    # Both unmapped masters went into one batch as `create`.
    assert len(fake.calls) == 1
    assert len(fake.calls[0]["create"]) == 2
    assert ProductMapping.objects.filter(site=site).count() == 2
    mapping = ProductMapping.objects.get(master=m1, site=site)
    assert mapping.woo_product_id  # saved from response
    assert mapping.last_synced_at is not None
    log = SyncLog.objects.get(site=site)
    assert log.status == SyncLog.Status.SUCCESS
    assert log.created_count == 2


@pytest.mark.django_db
def test_push_is_idempotent(monkeypatch):
    """Second run updates the same mappings — no duplicates, no new create."""
    site = SiteFactory()
    m1 = MasterProductFactory(sku="SP-1")
    fake = _FakeClient()
    _patch_client(monkeypatch, fake)

    services.push_products_to_site(site, masters=[m1])
    woo_id = ProductMapping.objects.get(master=m1, site=site).woo_product_id

    result = services.push_products_to_site(site, masters=[m1])

    assert result["created"] == 0 and result["updated"] == 1
    # Mapping count unchanged; second call sent it as an update keyed by woo id.
    assert ProductMapping.objects.filter(master=m1, site=site).count() == 1
    assert fake.calls[1]["update"] == [{"id": woo_id, "sku": "SP-1"}] or (
        fake.calls[1]["update"][0]["id"] == woo_id
    )
    assert ProductMapping.objects.get(master=m1, site=site).woo_product_id == woo_id


@pytest.mark.django_db
def test_push_deletes_soft_deleted_and_drops_mapping(monkeypatch):
    site = SiteFactory()
    master = MasterProductFactory(sku="SP-1", is_deleted=True)
    ProductMappingFactory(master=master, site=site, woo_product_id=777)
    fake = _FakeClient()
    _patch_client(monkeypatch, fake)

    result = services.push_products_to_site(site, masters=[master])

    assert result["deleted"] == 1
    assert fake.calls[0]["delete"] == [777]
    # Mapping removed so a later run does not re-issue the delete.
    assert not ProductMapping.objects.filter(master=master, site=site).exists()


@pytest.mark.django_db
def test_push_chunks_over_item_limit(monkeypatch):
    site = SiteFactory()
    masters = [MasterProductFactory(sku=f"SP-{i}") for i in range(5)]
    monkeypatch.setattr(services, "_item_limit", lambda: 2)
    monkeypatch.setattr(services, "_throttle_seconds", lambda: 0)
    fake = _FakeClient()
    _patch_client(monkeypatch, fake)

    result = services.push_products_to_site(site, masters=masters)

    assert result["created"] == 5
    # 5 creates, limit 2 → 3 batch requests, none over the cap.
    assert len(fake.calls) == 3
    assert all(len(c["create"]) + len(c["update"]) + len(c["delete"]) <= 2 for c in fake.calls)
    assert ProductMapping.objects.filter(site=site).count() == 5


@pytest.mark.django_db
def test_push_swallows_http_error_and_logs(monkeypatch):
    site = SiteFactory()
    master = MasterProductFactory(sku="SP-1")
    fake = _FakeClient(raise_error=True)
    _patch_client(monkeypatch, fake)

    result = services.push_products_to_site(site, masters=[master])

    assert result["error"] == "ConnectError"  # returned, not raised
    assert not ProductMapping.objects.filter(site=site).exists()
    log = SyncLog.objects.get(site=site)
    assert log.status == SyncLog.Status.ERROR
    assert log.error == "ConnectError"


@pytest.mark.django_db
def test_push_noop_when_nothing_to_do(monkeypatch):
    """No masters → no WooCommerce call and no SyncLog row."""
    site = SiteFactory()
    fake = _FakeClient()
    _patch_client(monkeypatch, fake)

    result = services.push_products_to_site(site, masters=[])

    assert result == {
        "site_id": site.id,
        "created": 0,
        "updated": 0,
        "deleted": 0,
        "error": None,
    }
    assert fake.calls == []
    assert not SyncLog.objects.filter(site=site).exists()
