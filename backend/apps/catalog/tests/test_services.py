import httpx
import pytest

from apps.catalog import services
from apps.catalog.models import (
    Category,
    CategoryMapping,
    ProductMapping,
    ProductVariationMapping,
)
from apps.catalog.tests.factories import (
    MasterProductFactory,
    ProductMappingFactory,
)
from apps.sites.tests.factories import SiteFactory
from apps.sync.models import SyncLog


class _FakeClient:
    """Fake WooClient for unit tests (no HTTP). Echoes ids/skus like /products/batch.

    ``calls`` records every ``batch_products`` invocation so tests can assert how
    the work was split / chunked. ``variation_calls`` does the same for
    ``batch_variations`` (keyed by parent id). ``categories`` is what
    ``list_categories`` returns. Created products/variations get incrementing ids.
    """

    def __init__(self, *, raise_error=False, categories=None):
        self.calls = []
        self.variation_calls = []
        self.raise_error = raise_error
        self.categories = categories or []
        self._next_id = 9000
        self._next_var_id = 8000

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

    def batch_variations(self, parent_id, create=None, update=None, delete=None):
        create, update, delete = create or [], update or [], delete or []
        self.variation_calls.append(
            {"parent_id": parent_id, "create": create, "update": update, "delete": delete}
        )
        if self.raise_error:
            raise httpx.ConnectError("boom")
        created = []
        for item in create:
            created.append({"id": self._next_var_id, "sku": item["sku"]})
            self._next_var_id += 1
        updated = [{"id": item["id"], "sku": item["sku"]} for item in update]
        deleted = [{"id": woo_id} for woo_id in delete]
        return {"create": created, "update": updated, "delete": deleted}

    def list_categories(self, per_page=100):
        if self.raise_error:
            raise httpx.ConnectError("boom")
        return self.categories


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


# --- product types: payload shape --------------------------------------------


def test_payload_external_includes_link_fields():
    master = MasterProductFactory.build(
        type="external",
        external_url="https://shop.example/aff",
        button_text="Mua ngay",
    )
    payload = services.build_product_payload(master)
    assert payload["type"] == "external"
    assert payload["external_url"] == "https://shop.example/aff"
    assert payload["button_text"] == "Mua ngay"


def test_payload_variable_sends_attributes_not_variations():
    master = MasterProductFactory.build(
        type="variable",
        attributes=[{"name": "Màu", "options": ["Đỏ", "Xanh"], "variation": True}],
        variations=[{"sku": "SP-1-DO", "regular_price": "10"}],
    )
    payload = services.build_product_payload(master)
    assert payload["attributes"] == [
        {"name": "Màu", "options": ["Đỏ", "Xanh"], "variation": True, "visible": True}
    ]
    assert "variations" not in payload  # variations go via a separate endpoint


def test_payload_resolves_category_id_when_mapped_else_name():
    master = MasterProductFactory.build(categories=["Pin mặt trời", "Inverter"])
    payload = services.build_product_payload(master, category_id_by_name={"Pin mặt trời": 42})
    assert payload["categories"] == [{"id": 42}, {"name": "Inverter"}]


def test_variation_payload_maps_attributes_as_name_option_pairs():
    payload = services.build_variation_payload(
        {
            "sku": "sp-1-do",
            "regular_price": "100",
            "sale_price": "90",
            "weight": "1.2",
            "stock_status": "instock",
            "attributes": {"Màu": "Đỏ"},
            "image": "https://x/v.jpg",
        }
    )
    assert payload["sku"] == "SP-1-DO"  # normalized
    assert payload["regular_price"] == "100"
    assert payload["sale_price"] == "90"
    assert payload["attributes"] == [{"name": "Màu", "option": "Đỏ"}]
    assert payload["image"] == {"src": "https://x/v.jpg"}


# --- grouped products --------------------------------------------------------


@pytest.mark.django_db
def test_grouped_resolves_mapped_children_and_records_missing(monkeypatch):
    site = SiteFactory()
    child_mapped = MasterProductFactory(sku="CHILD-1")
    MasterProductFactory(sku="CHILD-2")  # exists but unmapped on this site
    ProductMappingFactory(master=child_mapped, site=site, woo_product_id=111)
    grouped = MasterProductFactory(
        sku="BUNDLE", type="grouped", grouped_skus=["CHILD-1", "CHILD-2"]
    )
    fake = _FakeClient()
    _patch_client(monkeypatch, fake)

    services.push_products_to_site(site, masters=[grouped])

    created = fake.calls[0]["create"]
    bundle_payload = next(p for p in created if p["sku"] == "BUNDLE")
    assert bundle_payload["grouped_products"] == [111]  # only the mapped child
    log = SyncLog.objects.get(site=site)
    assert log.detail["grouped_unresolved"] == {"BUNDLE": ["CHILD-2"]}


# --- variable products: two-step push ----------------------------------------


@pytest.mark.django_db
def test_variable_pushes_parent_then_variations(monkeypatch):
    site = SiteFactory()
    master = MasterProductFactory(
        sku="SP-V",
        type="variable",
        attributes=[{"name": "Màu", "options": ["Đỏ"], "variation": True}],
        variations=[{"sku": "SP-V-DO", "regular_price": "100", "attributes": {"Màu": "Đỏ"}}],
    )
    monkeypatch.setattr(services, "_throttle_seconds", lambda: 0)
    fake = _FakeClient()
    _patch_client(monkeypatch, fake)

    services.push_products_to_site(site, masters=[master])

    # Parent created, then a variations batch against the new parent id.
    parent = ProductMapping.objects.get(master=master, site=site)
    assert len(fake.variation_calls) == 1
    assert fake.variation_calls[0]["parent_id"] == parent.woo_product_id
    assert len(fake.variation_calls[0]["create"]) == 1
    var = ProductVariationMapping.objects.get(site=site, variation_sku="SP-V-DO")
    assert var.woo_parent_id == parent.woo_product_id
    log = SyncLog.objects.get(site=site)
    assert log.detail["variations"] == {"created": 1, "updated": 0, "deleted": 0}


@pytest.mark.django_db
def test_variable_re_push_updates_variation(monkeypatch):
    site = SiteFactory()
    master = MasterProductFactory(
        sku="SP-V",
        type="variable",
        attributes=[{"name": "Màu", "options": ["Đỏ"], "variation": True}],
        variations=[{"sku": "SP-V-DO", "regular_price": "100", "attributes": {"Màu": "Đỏ"}}],
    )
    monkeypatch.setattr(services, "_throttle_seconds", lambda: 0)
    fake = _FakeClient()
    _patch_client(monkeypatch, fake)

    services.push_products_to_site(site, masters=[master])
    var_id = ProductVariationMapping.objects.get(
        site=site, variation_sku="SP-V-DO"
    ).woo_variation_id

    services.push_products_to_site(site, masters=[master])

    # Second run sent the variation as an update (keyed by woo id), no duplicate.
    assert fake.variation_calls[1]["update"][0]["id"] == var_id
    assert ProductVariationMapping.objects.filter(site=site, master=master).count() == 1


@pytest.mark.django_db
def test_variable_removing_a_variation_deletes_it(monkeypatch):
    site = SiteFactory()
    master = MasterProductFactory(
        sku="SP-V",
        type="variable",
        attributes=[{"name": "Màu", "options": ["Đỏ", "Xanh"], "variation": True}],
        variations=[
            {"sku": "SP-V-DO", "regular_price": "100", "attributes": {"Màu": "Đỏ"}},
            {"sku": "SP-V-XANH", "regular_price": "100", "attributes": {"Màu": "Xanh"}},
        ],
    )
    monkeypatch.setattr(services, "_throttle_seconds", lambda: 0)
    fake = _FakeClient()
    _patch_client(monkeypatch, fake)
    services.push_products_to_site(site, masters=[master])
    removed = ProductVariationMapping.objects.get(site=site, variation_sku="SP-V-XANH")

    master.variations = [{"sku": "SP-V-DO", "regular_price": "100", "attributes": {"Màu": "Đỏ"}}]
    master.save(update_fields=["variations"])
    services.push_products_to_site(site, masters=[master])

    assert fake.variation_calls[1]["delete"] == [removed.woo_variation_id]
    assert not ProductVariationMapping.objects.filter(site=site, variation_sku="SP-V-XANH").exists()


@pytest.mark.django_db
def test_deleting_variable_parent_cascades_variation_mappings(monkeypatch):
    site = SiteFactory()
    master = MasterProductFactory(
        sku="SP-V",
        type="variable",
        attributes=[{"name": "Màu", "options": ["Đỏ"], "variation": True}],
        variations=[{"sku": "SP-V-DO", "regular_price": "100", "attributes": {"Màu": "Đỏ"}}],
    )
    monkeypatch.setattr(services, "_throttle_seconds", lambda: 0)
    fake = _FakeClient()
    _patch_client(monkeypatch, fake)
    services.push_products_to_site(site, masters=[master])

    master.is_deleted = True
    master.save(update_fields=["is_deleted"])
    services.push_products_to_site(site, masters=[master])

    assert not ProductMapping.objects.filter(master=master, site=site).exists()
    assert not ProductVariationMapping.objects.filter(master=master, site=site).exists()


# --- category pull -----------------------------------------------------------


@pytest.mark.django_db
def test_pull_categories_upserts_idempotently(monkeypatch):
    site = SiteFactory()
    fake = _FakeClient(
        categories=[
            {"id": 10, "name": "Pin mặt trời", "slug": "pin", "parent": 0},
            {"id": 11, "name": "Inverter", "slug": "inv", "parent": 10},
        ]
    )
    _patch_client(monkeypatch, fake)

    result = services.pull_categories_for_site(site)
    assert result["pulled"] == 2
    assert Category.objects.count() == 2
    inverter = Category.objects.get(name="Inverter")
    assert inverter.parent_name == "Pin mặt trời"
    assert CategoryMapping.objects.filter(site=site).count() == 2

    # Re-pull: same data → no duplicates.
    services.pull_categories_for_site(site)
    assert Category.objects.count() == 2
    assert CategoryMapping.objects.filter(site=site).count() == 2
    assert SyncLog.objects.filter(site=site, operation="pull_categories").count() == 2


@pytest.mark.django_db
def test_pull_categories_same_name_two_sites_converges(monkeypatch):
    s1, s2 = SiteFactory(), SiteFactory()
    monkeypatch.setattr(
        "apps.sites.services.client_for_site",
        lambda site: _FakeClient(categories=[{"id": 99, "name": "Pin mặt trời"}]),
    )

    services.pull_categories_for_site(s1)
    services.pull_categories_for_site(s2)

    assert Category.objects.filter(name="Pin mặt trời").count() == 1
    assert CategoryMapping.objects.filter(category__name="Pin mặt trời").count() == 2


@pytest.mark.django_db
def test_pull_categories_swallows_http_error(monkeypatch):
    site = SiteFactory()
    fake = _FakeClient(raise_error=True)
    _patch_client(monkeypatch, fake)

    result = services.pull_categories_for_site(site)

    assert result["error"] == "ConnectError"
    assert Category.objects.count() == 0
    log = SyncLog.objects.get(site=site, operation="pull_categories")
    assert log.status == SyncLog.Status.ERROR


# --- product_sync_status -----------------------------------------------------


@pytest.mark.django_db
def test_product_sync_status_lists_all_sites(monkeypatch):
    synced_site = SiteFactory(name="A-Site")
    SiteFactory(name="B-Site")  # active, not synced
    master = MasterProductFactory(sku="SP-1")
    ProductMappingFactory(master=master, site=synced_site, woo_product_id=321)

    rows = services.product_sync_status(master)

    by_name = {r["site_name"]: r for r in rows}
    assert by_name["A-Site"]["synced"] is True
    assert by_name["A-Site"]["woo_product_id"] == 321
    assert by_name["B-Site"]["synced"] is False
    assert by_name["B-Site"]["woo_product_id"] is None
