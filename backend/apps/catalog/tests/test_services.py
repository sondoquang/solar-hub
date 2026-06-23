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
    CategoryFactory,
    CategoryMappingFactory,
    MasterProductFactory,
    ProductMappingFactory,
)
from apps.sites.tests.factories import SiteFactory
from apps.sync.models import SyncLog


class _FakeClient:
    """Fake WooClient for unit tests (no HTTP). Echoes ids/skus like /products/batch.

    ``calls`` records every ``batch_products`` invocation so tests can assert how
    the work was split / chunked. ``variation_calls`` does the same for
    ``batch_variations`` (keyed by parent id), ``category_calls`` for
    ``batch_categories``. ``categories`` is what ``list_categories`` returns.
    Created products/variations/categories get incrementing ids.
    """

    def __init__(
        self,
        *,
        raise_error=False,
        categories=None,
        products=None,
        error_skus=None,
        stale_woo_ids=None,
        category_error_names=None,
        existing_term_ids=None,
    ):
        self.calls = []
        self.variation_calls = []
        self.category_calls = []
        self.list_products_calls = 0
        self.raise_error = raise_error
        self.categories = categories or []
        # What ``list_products`` returns (Woo-shaped {id, name, sku, type}).
        self.products = products or []
        # SKUs Woo rejects per-item: returned as {"error": ...} with no id, like
        # a duplicate-SKU create against /products/batch (HTTP 200 overall).
        self.error_skus = set(error_skus or [])
        # Woo ids that no longer exist on the site (product deleted outside the
        # Hub): updates against them are rejected like Woo does — the error
        # item still ECHOES the requested id.
        self.stale_woo_ids = set(stale_woo_ids or [])
        # Category names whose create is rejected per-item (HTTP 200 overall).
        self.category_error_names = set(category_error_names or [])
        # name → woo term id that ALREADY exists on the site: the create is
        # rejected `term_exists` carrying that id in error.data.resource_id,
        # exactly like Woo when the term was never pulled into the Hub.
        self.existing_term_ids = existing_term_ids or {}
        self._next_id = 9000
        self._next_var_id = 8000
        self._next_cat_id = 600

    def batch_products(self, create=None, update=None, delete=None):
        create, update, delete = create or [], update or [], delete or []
        self.calls.append({"create": create, "update": update, "delete": delete})
        if self.raise_error:
            raise httpx.ConnectError("boom")
        created = []
        for item in create:
            if item["sku"] in self.error_skus:
                created.append(
                    {
                        "error": {
                            "code": "product_invalid_sku",
                            "message": "Invalid or duplicated SKU.",
                        }
                    }
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

    def list_products(self, per_page=100, search=None):
        self.list_products_calls += 1
        if self.raise_error:
            raise httpx.ConnectError("boom")
        return self.products

    def batch_categories(self, create=None):
        create = create or []
        self.category_calls.append({"create": create})
        if self.raise_error:
            raise httpx.ConnectError("boom")
        created = []
        for item in create:
            name = item["name"]
            if name in self.category_error_names:
                created.append(
                    {"error": {"code": "woocommerce_rest_cannot_create", "message": "nope"}}
                )
            elif name in self.existing_term_ids:
                created.append(
                    {
                        "id": 0,
                        "error": {
                            "code": "term_exists",
                            "message": "A term with the name provided already exists.",
                            "data": {"status": 400, "resource_id": self.existing_term_ids[name]},
                        },
                    }
                )
            else:
                created.append({"id": self._next_cat_id, "name": name})
                self._next_cat_id += 1
        return {"create": created}


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


def test_build_product_payload_sends_empty_string_when_unset():
    # Woo only clears sale_price/weight when it receives "" — omitting the key
    # would leave the old value on the site after an update.
    master = MasterProductFactory.build(sale_price=None, weight=None)
    payload = services.build_product_payload(master)
    assert payload["sale_price"] == ""
    assert payload["weight"] == ""


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
        {
            "sku": "SP-1",
            "op": "create",
            "code": "product_invalid_sku",
            "message": "Invalid or duplicated SKU.",
        }
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


@pytest.mark.django_db
def test_push_stamps_run_id_for_progress(monkeypatch):
    """A tracked run threads run_id/triggered_by/started_at onto the SyncLog row
    so the progress banner can group and poll it."""
    import uuid

    site = SiteFactory()
    master = MasterProductFactory(sku="SP-RUN")
    _patch_client(monkeypatch, _FakeClient())
    run_id = uuid.uuid4()

    services.push_products_to_site(site, masters=[master], run_id=run_id, triggered_by_id=None)

    log = SyncLog.objects.get(site=site)
    assert str(log.run_id) == str(run_id)
    assert log.started_at is not None


@pytest.mark.django_db
def test_push_noop_logs_only_when_tracked(monkeypatch):
    """A no-op push writes nothing untracked, but a tracked run records a SUCCESS
    row so the banner's done count reaches expected even for in-sync sites."""
    import uuid

    site = SiteFactory()
    _patch_client(monkeypatch, _FakeClient())
    run_id = uuid.uuid4()

    services.push_products_to_site(site, masters=[], run_id=run_id)

    log = SyncLog.objects.get(site=site)
    assert log.status == SyncLog.Status.SUCCESS
    assert str(log.run_id) == str(run_id)


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


# --- push: ensure categories exist on the site --------------------------------
# Woo's products endpoint IGNORES name-only category refs (no auto-create), so
# the push must create unmapped categories on the site before building payloads
# — otherwise a re-categorized product silently keeps its old categories there.


@pytest.mark.django_db
def test_push_creates_unmapped_categories_before_products(monkeypatch):
    site = SiteFactory()
    master = MasterProductFactory(sku="SP-1", categories=["Pin mặt trời"])
    fake = _FakeClient()
    _patch_client(monkeypatch, fake)

    services.push_products_to_site(site, masters=[master])

    assert fake.category_calls == [{"create": [{"name": "Pin mặt trời"}]}]
    mapping = CategoryMapping.objects.get(site=site, category__name="Pin mặt trời")
    assert mapping.woo_name == "Pin mặt trời"
    assert mapping.last_synced_at is not None
    # The product payload referenced the fresh id — a name ref would be ignored.
    assert fake.calls[0]["create"][0]["categories"] == [{"id": mapping.woo_category_id}]
    log = SyncLog.objects.get(site=site)
    assert log.status == SyncLog.Status.SUCCESS
    assert log.detail["categories"] == {"created": ["Pin mặt trời"], "linked": [], "failed": []}


@pytest.mark.django_db
def test_push_skips_category_call_when_all_mapped(monkeypatch):
    site = SiteFactory()
    category = CategoryFactory(name="Pin mặt trời")
    CategoryMappingFactory(category=category, site=site, woo_category_id=42)
    master = MasterProductFactory(sku="SP-1", categories=["Pin mặt trời"])
    fake = _FakeClient()
    _patch_client(monkeypatch, fake)

    services.push_products_to_site(site, masters=[master])

    assert fake.category_calls == []
    assert fake.calls[0]["create"][0]["categories"] == [{"id": 42}]


@pytest.mark.django_db
def test_push_maps_existing_site_term_on_term_exists(monkeypatch):
    """The site already has the term (never pulled) → Woo rejects the create with
    ``term_exists`` + the existing id; the Hub maps that id instead of failing."""
    site = SiteFactory()
    master = MasterProductFactory(sku="SP-1", categories=["Pin mặt trời"])
    fake = _FakeClient(existing_term_ids={"Pin mặt trời": 321})
    _patch_client(monkeypatch, fake)

    services.push_products_to_site(site, masters=[master])

    mapping = CategoryMapping.objects.get(site=site, category__name="Pin mặt trời")
    assert mapping.woo_category_id == 321
    assert fake.calls[0]["create"][0]["categories"] == [{"id": 321}]
    log = SyncLog.objects.get(site=site)
    assert log.status == SyncLog.Status.SUCCESS
    assert log.detail["categories"]["linked"] == ["Pin mặt trời"]


@pytest.mark.django_db
def test_push_creates_parent_category_before_child(monkeypatch):
    """An unmapped category with an unmapped Hub parent → the parent is created
    first (its own wave), then the child references the parent's new woo id."""
    site = SiteFactory()
    parent = CategoryFactory(name="Inverter")
    CategoryFactory(name="Inverter Hybrid", parent=parent)
    master = MasterProductFactory(sku="SP-1", categories=["Inverter Hybrid"])
    fake = _FakeClient()
    _patch_client(monkeypatch, fake)

    services.push_products_to_site(site, masters=[master])

    assert fake.category_calls[0] == {"create": [{"name": "Inverter"}]}
    parent_woo = CategoryMapping.objects.get(site=site, category__name="Inverter").woo_category_id
    assert fake.category_calls[1] == {"create": [{"name": "Inverter Hybrid", "parent": parent_woo}]}
    child_woo = CategoryMapping.objects.get(
        site=site, category__name="Inverter Hybrid"
    ).woo_category_id
    assert fake.calls[0]["create"][0]["categories"] == [{"id": child_woo}]


@pytest.mark.django_db
def test_push_category_create_failure_marks_partial(monkeypatch):
    """A category create rejected per-item must not pass silently: the product
    still pushes (name ref, which Woo ignores) but the run is flagged PARTIAL
    with the gap in detail — this is exactly the silent-miss the ensure step
    exists to surface."""
    site = SiteFactory()
    master = MasterProductFactory(sku="SP-1", categories=["Danh mục hỏng"])
    fake = _FakeClient(category_error_names=["Danh mục hỏng"])
    _patch_client(monkeypatch, fake)

    result = services.push_products_to_site(site, masters=[master])

    assert result["error"] is None
    assert fake.calls[0]["create"][0]["categories"] == [{"name": "Danh mục hỏng"}]
    log = SyncLog.objects.get(site=site)
    assert log.status == SyncLog.Status.PARTIAL
    assert log.detail["categories"]["failed"] == [
        {"name": "Danh mục hỏng", "code": "woocommerce_rest_cannot_create", "message": "nope"}
    ]


@pytest.mark.django_db
def test_push_registers_hand_typed_category_in_hub(monkeypatch):
    """A product can carry a name no pull has seen — the ensure step creates the
    Hub ``Category`` row too, so the picker and later pulls converge on it."""
    site = SiteFactory()
    master = MasterProductFactory(sku="SP-1", categories=["  Tên   gõ tay "])
    fake = _FakeClient()
    _patch_client(monkeypatch, fake)

    services.push_products_to_site(site, masters=[master])

    category = Category.objects.get(name="Tên gõ tay")  # normalized before storing
    assert CategoryMapping.objects.filter(site=site, category=category).exists()


# --- category pull -----------------------------------------------------------


@pytest.mark.django_db
def test_pull_categories_upserts_idempotently(monkeypatch):
    site = SiteFactory()
    fake = _FakeClient(
        categories=[
            {"id": 10, "name": " Pin  mặt trời ", "slug": "pin", "parent": 0},
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
    # The mapping keeps the RAW site name (un-normalized) for the mapping screen.
    assert CategoryMapping.objects.get(site=site, woo_category_id=10).woo_name == (
        " Pin  mặt trời "
    )

    # Re-pull: same data → no duplicates, woo_name survives.
    services.pull_categories_for_site(site)
    assert Category.objects.count() == 2
    assert CategoryMapping.objects.filter(site=site).count() == 2
    assert CategoryMapping.objects.get(site=site, woo_category_id=10).woo_name == (
        " Pin  mặt trời "
    )
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


# --- clear_category_sync_data ------------------------------------------------


@pytest.mark.django_db
def test_clear_category_sync_keeps_in_use_and_ancestors():
    """A category a live product uses is kept, together with its ancestors so the
    kept tree stays connected; every other live category is soft-deleted."""
    site = SiteFactory()
    root = CategoryFactory(name="Sản phẩm")
    used = CategoryFactory(name="Pin mặt trời", parent=root)
    orphan = CategoryFactory(name="Rác")
    # Live product references the leaf by name (matched after normalize).
    MasterProductFactory(sku="SP-1", categories=[" Pin mặt trời "])
    # A soft-deleted product must NOT protect its categories.
    MasterProductFactory(sku="SP-2", categories=["Rác"], is_deleted=True)
    for cat in (root, used, orphan):
        CategoryMappingFactory(category=cat, site=site)

    result = services.clear_category_sync_data()

    used.refresh_from_db()
    root.refresh_from_db()
    orphan.refresh_from_db()
    assert used.is_deleted is False  # in use → kept
    assert root.is_deleted is False  # ancestor of in-use → kept
    assert orphan.is_deleted is True  # not used → cleared
    assert result["categories_kept"] == 2
    assert result["categories_cleared"] == 1
    # Kept categories keep their mappings; the cleared one loses its mapping.
    assert CategoryMapping.objects.filter(category=used).exists()
    assert CategoryMapping.objects.filter(category=root).exists()
    assert not CategoryMapping.objects.filter(category=orphan).exists()
    assert result["mappings_cleared"] == 1


@pytest.mark.django_db
def test_clear_category_sync_soft_deletes_history():
    """The pull history is soft-deleted (rows kept, but hidden from the report)."""
    site = SiteFactory()
    SyncLog.objects.create(
        site=site, operation="pull_categories", status=SyncLog.Status.SUCCESS,
        run_id=uuid.uuid4(),
    )
    # An unrelated operation is left untouched.
    SyncLog.objects.create(site=site, operation="push_products", status=SyncLog.Status.SUCCESS)

    result = services.clear_category_sync_data()

    assert result["history_cleared"] == 1
    assert SyncLog.objects.get(operation="pull_categories").is_deleted is True
    assert SyncLog.objects.get(operation="push_products").is_deleted is False


@pytest.mark.django_db
def test_pull_revives_soft_deleted_category(monkeypatch):
    """After a clear soft-deletes a category, re-pulling its name revives it
    (is_deleted reset to False) instead of leaving it hidden forever."""
    site = SiteFactory()
    dead = CategoryFactory(name="Inverter", is_deleted=True)

    _patch_client(monkeypatch, _FakeClient(categories=[{"id": 5, "name": "Inverter"}]))
    services.pull_categories_for_site(site)

    dead.refresh_from_db()
    assert dead.is_deleted is False
    assert CategoryMapping.objects.filter(site=site, category=dead).exists()


# --- product_sync_status -----------------------------------------------------


@pytest.mark.django_db
def test_product_sync_status_lists_all_sites(monkeypatch):
    synced_site = SiteFactory(name="A-Site", base_url="https://a-site.example.com", is_primary=True)
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
