import uuid

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

    def __init__(self, *, raise_error=False, categories=None, error_skus=None, stale_woo_ids=None):
        self.calls = []
        self.variation_calls = []
        self.raise_error = raise_error
        self.categories = categories or []
        # SKUs Woo rejects per-item: returned as {"error": ...} with no id, like
        # a duplicate-SKU create against /products/batch (HTTP 200 overall).
        self.error_skus = set(error_skus or [])
        # Woo ids that no longer exist on the site (product deleted outside the
        # Hub): updates against them are rejected like Woo does — the error
        # item still ECHOES the requested id.
        self.stale_woo_ids = set(stale_woo_ids or [])
        self._next_id = 9000
        self._next_var_id = 8000

    def batch_products(self, create=None, update=None, delete=None):
        create, update, delete = create or [], update or [], delete or []
        self.calls.append({"create": create, "update": update, "delete": delete})
        if self.raise_error:
            raise httpx.ConnectError("boom")
        created = []
        for item in create:
            if item["sku"] in self.error_skus:
                created.append(
                    {"error": {"code": "product_invalid_sku", "message": "Invalid or duplicated SKU."}}
                )
                continue
            created.append({"id": self._next_id, "sku": item["sku"]})
            self._next_id += 1
        updated = []
        for item in update:
            if item["id"] in self.stale_woo_ids:
                updated.append(
                    {
                        "id": item["id"],
                        "error": {
                            "code": "woocommerce_rest_product_invalid_id",
                            "message": "Invalid ID.",
                        },
                    }
                )
                continue
            updated.append({"id": item["id"], "sku": item["sku"]})
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
def test_push_per_item_error_does_not_false_succeed(monkeypatch):
    """A Woo per-item reject (HTTP 200 batch) must NOT count as created nor log a
    clean success: no mapping, status ERROR, the SKU + code surfaced in detail."""
    site = SiteFactory()
    master = MasterProductFactory(sku="SP-1")
    fake = _FakeClient(error_skus=["SP-1"])
    _patch_client(monkeypatch, fake)

    result = services.push_products_to_site(site, masters=[master])

    assert result["created"] == 0
    assert result["error"] is None  # batch HTTP call itself succeeded
    assert not ProductMapping.objects.filter(site=site).exists()
    log = SyncLog.objects.get(site=site)
    assert log.status == SyncLog.Status.ERROR
    assert log.created_count == 0
    assert log.detail["failed"] == [
        {"sku": "SP-1", "op": "create", "code": "product_invalid_sku", "message": "Invalid or duplicated SKU."}
    ]


@pytest.mark.django_db
def test_push_partial_when_some_items_fail(monkeypatch):
    """One item lands, one is rejected → PARTIAL: the good one maps, the bad one
    is recorded in detail."""
    site = SiteFactory()
    ok = MasterProductFactory(sku="SP-OK")
    bad = MasterProductFactory(sku="SP-BAD")
    fake = _FakeClient(error_skus=["SP-BAD"])
    _patch_client(monkeypatch, fake)

    result = services.push_products_to_site(site, masters=[ok, bad])

    assert result["created"] == 1
    assert ProductMapping.objects.filter(master=ok, site=site).exists()
    assert not ProductMapping.objects.filter(master=bad, site=site).exists()
    log = SyncLog.objects.get(site=site)
    assert log.status == SyncLog.Status.PARTIAL
    assert log.created_count == 1
    assert [f["sku"] for f in log.detail["failed"]] == ["SP-BAD"]


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
    pin = Category.objects.get(name="Pin mặt trời")
    inverter = Category.objects.get(name="Inverter")
    assert inverter.parent_id == pin.id  # woo parent id 10 → "Pin mặt trời"
    assert pin.parent_id is None  # parent 0 = root
    assert CategoryMapping.objects.filter(site=site).count() == 2

    # Re-pull: same data → no duplicates.
    services.pull_categories_for_site(site)
    assert Category.objects.count() == 2
    assert CategoryMapping.objects.filter(site=site).count() == 2
    assert SyncLog.objects.filter(site=site, operation="pull_categories").count() == 2


@pytest.mark.django_db
def test_pull_categories_tree_is_last_pull_wins(monkeypatch):
    """Two sites disagree on the tree: site A nests Inverter under Pin, site B
    keeps Inverter at the root. The later pull (B) wins, clearing the parent."""
    s1, s2 = SiteFactory(), SiteFactory()

    _patch_client(
        monkeypatch,
        _FakeClient(
            categories=[
                {"id": 10, "name": "Pin mặt trời", "parent": 0},
                {"id": 11, "name": "Inverter", "parent": 10},
            ]
        ),
    )
    services.pull_categories_for_site(s1)
    assert Category.objects.get(name="Inverter").parent_id == (
        Category.objects.get(name="Pin mặt trời").id
    )

    # Site B exposes Inverter as a root category → parent cleared (last-pull-wins).
    _patch_client(
        monkeypatch,
        _FakeClient(categories=[{"id": 7, "name": "Inverter", "parent": 0}]),
    )
    services.pull_categories_for_site(s2)
    assert Category.objects.get(name="Inverter").parent_id is None


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
def test_pull_categories_duplicate_name_one_site_collapses(monkeypatch):
    """Two woo categories on one site that normalize to the same name collapse
    to a single (category, site) mapping instead of tripping the unique
    constraint."""
    site = SiteFactory()
    fake = _FakeClient(
        categories=[
            {"id": 104, "name": "Pin mặt trời"},
            {"id": 220, "name": " Pin mặt trời "},  # normalizes to the same name
        ]
    )
    _patch_client(monkeypatch, fake)

    result = services.pull_categories_for_site(site)

    assert result["error"] is None
    assert Category.objects.filter(name="Pin mặt trời").count() == 1
    mappings = CategoryMapping.objects.filter(site=site)
    assert mappings.count() == 1
    # Smallest woo id wins so the choice is stable across re-pulls.
    assert mappings.get().woo_category_id == 104

    # Re-pull stays idempotent — no duplicate, same winner.
    services.pull_categories_for_site(site)
    assert CategoryMapping.objects.filter(site=site).count() == 1
    assert CategoryMapping.objects.get(site=site).woo_category_id == 104


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


@pytest.mark.django_db
def test_pull_categories_snapshots_run_into_synclog(monkeypatch):
    """detail carries the report snapshot — site/hosting names, the raw Woo
    name of every category and the Hub Category it converged to — and the row
    is stamped with the run_id."""
    from apps.sites.tests.factories import HostingFactory

    site = SiteFactory(hosting=HostingFactory(provider="TenTen"))
    fake = _FakeClient(
        categories=[
            {"id": 104, "name": "Pin mặt trời"},
            {"id": 220, "name": " Pin  mặt trời "},  # collapses onto the same Hub row
            {"id": 300, "name": "Inverter"},
        ]
    )
    _patch_client(monkeypatch, fake)

    run_id = str(uuid.uuid4())
    services.pull_categories_for_site(site, run_id=run_id)

    log = SyncLog.objects.get(site=site, operation="pull_categories")
    assert str(log.run_id) == run_id
    detail = log.detail
    assert detail["site_name"] == site.name
    assert detail["site_url"] == site.base_url
    assert detail["hosting"] == "TenTen"
    assert detail["pulled"] == 3
    assert detail["mapped"] == 2  # the duplicate pair maps once

    by_woo = {c["woo_id"]: c for c in detail["categories"]}
    assert set(by_woo) == {104, 220, 300}
    # Raw Woo names preserved (the report shows what the SITE has)...
    assert by_woo[220]["woo_name"] == " Pin  mặt trời "
    # ...while both duplicates point at the one Hub category they merged into.
    pin = Category.objects.get(name="Pin mặt trời")
    assert by_woo[104]["hub_id"] == by_woo[220]["hub_id"] == pin.id
    assert by_woo[300]["hub_name"] == "Inverter"


@pytest.mark.django_db
def test_pull_categories_error_and_empty_rows_carry_run_id(monkeypatch):
    """A failed or empty site still shows up in its run (run_id + site snapshot
    on the SyncLog row); without a run_id the column stays NULL."""
    site = SiteFactory()  # no hosting
    run_id = str(uuid.uuid4())

    _patch_client(monkeypatch, _FakeClient(raise_error=True))
    services.pull_categories_for_site(site, run_id=run_id)
    error_log = SyncLog.objects.get(site=site, status=SyncLog.Status.ERROR)
    assert str(error_log.run_id) == run_id
    assert error_log.detail["site_name"] == site.name
    assert error_log.detail["hosting"] == ""

    _patch_client(monkeypatch, _FakeClient(categories=[]))
    services.pull_categories_for_site(site)  # no run_id → legacy-style row
    empty_log = SyncLog.objects.get(site=site, status=SyncLog.Status.SUCCESS)
    assert empty_log.run_id is None
    assert empty_log.detail["pulled"] == 0


# --- product_sync_status -----------------------------------------------------


@pytest.mark.django_db
def test_product_sync_status_lists_all_sites(monkeypatch):
    synced_site = SiteFactory(
        name="A-Site", base_url="https://a-site.example.com", is_primary=True
    )
    SiteFactory(name="B-Site")  # active, not synced
    master = MasterProductFactory(sku="SP-1")
    ProductMappingFactory(master=master, site=synced_site, woo_product_id=321)

    rows = services.product_sync_status(master)

    by_name = {r["site_name"]: r for r in rows}
    assert by_name["A-Site"]["synced"] is True
    assert by_name["A-Site"]["woo_product_id"] == 321
    assert by_name["A-Site"]["site_url"] == "https://a-site.example.com"
    assert by_name["A-Site"]["is_primary"] is True
    assert by_name["B-Site"]["synced"] is False
    assert by_name["B-Site"]["woo_product_id"] is None
    assert by_name["B-Site"]["is_primary"] is False


# --- stale mapping self-heal (product deleted on the site outside the Hub) ----


@pytest.mark.django_db
def test_push_recreates_product_when_mapping_is_stale(monkeypatch, settings):
    """An update against a woo id that was deleted on the site (wp-admin) comes
    back as ``woocommerce_rest_product_invalid_id`` WITH the id echoed — it must
    not count as success; the mapping is dropped and the product re-created in
    the same run."""
    from apps.catalog.models import ProductMapping

    settings.PRODUCT_PUSH_THROTTLE_SECONDS = 0
    site = SiteFactory()
    m = MasterProductFactory(sku="SP-1")
    ProductMappingFactory(master=m, site=site, woo_product_id=555)
    fake = _FakeClient(stale_woo_ids={555})
    _patch_client(monkeypatch, fake)

    result = services.push_products_to_site(site)

    assert result["error"] is None
    assert result["created"] == 1 and result["updated"] == 0
    mapping = ProductMapping.objects.get(master=m, site=site)
    assert mapping.woo_product_id != 555  # fresh id from the re-create
    # Call 1: the rejected update; call 2: the healing create.
    assert fake.calls[0]["update"][0]["id"] == 555
    assert fake.calls[1]["create"][0]["sku"] == "SP-1"
    log = SyncLog.objects.latest("id")
    assert log.status == SyncLog.Status.SUCCESS
    assert log.detail["recreated_stale"] == 1
    assert log.detail["failed"] == []
    assert log.created_count == 1 and log.updated_count == 0
