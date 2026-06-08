import pytest

from apps.catalog.models import MasterProduct
from apps.catalog.tests.factories import (
    CategoryFactory,
    MasterProductFactory,
    ProductMappingFactory,
)
from apps.sites.tests.factories import SiteFactory


@pytest.mark.django_db
def test_create_normalizes_sku(client):
    resp = client.post(
        "/api/products/",
        {"sku": "  sp-9 ", "name": "Pin", "regular_price": "100000.00"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["sku"] == "SP-9"  # normalized server-side
    assert MasterProduct.objects.get(name="Pin").sku == "SP-9"


@pytest.mark.django_db
def test_create_duplicate_sku_rejected(client):
    MasterProductFactory(sku="SP-1")
    resp = client.post("/api/products/", {"sku": "sp-1", "name": "X"}, format="json")
    assert resp.status_code == 400
    assert "sku" in resp.data


@pytest.mark.django_db
def test_list_excludes_soft_deleted_and_shows_mappings(client):
    site = SiteFactory(name="solarhub.com.vn")
    m = MasterProductFactory(sku="SP-1")
    ProductMappingFactory(master=m, site=site, woo_product_id=777)
    MasterProductFactory(sku="SP-DEL", is_deleted=True)

    resp = client.get("/api/products/")
    assert resp.status_code == 200
    skus = [r["sku"] for r in resp.data["results"]]
    assert "SP-1" in skus and "SP-DEL" not in skus
    row = next(r for r in resp.data["results"] if r["sku"] == "SP-1")
    assert row["mapping_count"] == 1
    assert row["mappings"][0]["site_name"] == "solarhub.com.vn"


@pytest.mark.django_db
def test_filter_by_status(client):
    MasterProductFactory(status="publish")
    MasterProductFactory(status="draft")
    assert client.get("/api/products/", {"status": "draft"}).data["count"] == 1


@pytest.mark.django_db
def test_destroy_soft_deletes(client):
    m = MasterProductFactory(sku="SP-1")
    resp = client.delete(f"/api/products/{m.id}/")
    assert resp.status_code == 204
    m.refresh_from_db()
    assert m.is_deleted is True and m.deleted_at is not None
    # Soft-deleted, so the row still exists (for the next push to remove remotely).
    assert MasterProduct.objects.filter(id=m.id).exists()


@pytest.mark.django_db
def test_stats(client):
    site = SiteFactory()
    mapped = MasterProductFactory(status="publish")
    ProductMappingFactory(master=mapped, site=site)
    MasterProductFactory(status="draft")  # unmapped

    data = client.get("/api/products/stats/").data
    assert data["total"] == 2
    assert data["mapped"] == 1
    assert data["unmapped"] == 1
    assert data["by_status"] == {"publish": 1, "draft": 1}


@pytest.mark.django_db
def test_sync_now_dispatches_task(client, monkeypatch):
    from apps.sync import tasks

    captured = {}

    class _Result:
        id = "task-123"

    monkeypatch.setattr(
        tasks.push_all_products,
        "delay",
        lambda site_ids=None, master_ids=None: captured.update(
            site_ids=site_ids, master_ids=master_ids
        )
        or _Result(),
    )

    resp = client.post("/api/products/sync_now/", {"sites": [1, 2], "products": [5]}, format="json")
    assert resp.status_code == 200
    assert resp.data == {"task_id": "task-123"}
    assert captured == {"site_ids": [1, 2], "master_ids": [5]}


@pytest.mark.django_db
def test_sync_now_validates_sites(client):
    resp = client.post("/api/products/sync_now/", {"sites": ["x"]}, format="json")
    assert resp.status_code == 400


# --- product types via the serializer ----------------------------------------


@pytest.mark.django_db
def test_create_external_requires_url(client):
    resp = client.post(
        "/api/products/",
        {"sku": "EXT-1", "name": "Aff", "type": "external"},
        format="json",
    )
    assert resp.status_code == 400
    assert "external_url" in resp.data


@pytest.mark.django_db
def test_create_variable_requires_variation_attribute(client):
    resp = client.post(
        "/api/products/",
        {
            "sku": "VAR-1",
            "name": "Bien the",
            "type": "variable",
            "attributes": [{"name": "Màu", "options": ["Đỏ"], "variation": False}],
        },
        format="json",
    )
    assert resp.status_code == 400
    assert "attributes" in resp.data


@pytest.mark.django_db
def test_create_variable_ok_and_normalizes_variation_sku(client):
    resp = client.post(
        "/api/products/",
        {
            "sku": "VAR-1",
            "name": "Bien the",
            "type": "variable",
            "regular_price": "100000.00",
            "attributes": [{"name": "Màu", "options": ["Đỏ"], "variation": True}],
            "variations": [{"sku": " var-1-do ", "regular_price": "100000.00"}],
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["variations"][0]["sku"] == "VAR-1-DO"


@pytest.mark.django_db
def test_create_grouped_normalizes_skus(client):
    resp = client.post(
        "/api/products/",
        {
            "sku": "BUNDLE",
            "name": "Combo",
            "type": "grouped",
            "grouped_skus": [" child-1 ", "child-2"],
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["grouped_skus"] == ["CHILD-1", "CHILD-2"]


# --- categories endpoint ------------------------------------------------------


@pytest.mark.django_db
def test_categories_list_and_search(client):
    CategoryFactory(name="Pin mặt trời")
    CategoryFactory(name="Inverter")
    resp = client.get("/api/products/categories/")
    assert resp.status_code == 200
    names = [c["name"] for c in resp.data["results"]]
    assert "Pin mặt trời" in names and "Inverter" in names

    resp = client.get("/api/products/categories/", {"search": "Inv"})
    assert [c["name"] for c in resp.data["results"]] == ["Inverter"]


@pytest.mark.django_db
def test_categories_pull_now_dispatches_task(client, monkeypatch):
    from apps.sync import tasks

    captured = {}

    class _Result:
        id = "cat-1"

    monkeypatch.setattr(
        tasks.pull_all_categories,
        "delay",
        lambda site_ids=None: captured.update(site_ids=site_ids) or _Result(),
    )

    resp = client.post("/api/products/categories/pull_now/", {"sites": [3]}, format="json")
    assert resp.status_code == 200
    assert resp.data == {"task_id": "cat-1"}
    assert captured == {"site_ids": [3]}


# --- per-product sync status --------------------------------------------------


@pytest.mark.django_db
def test_sync_status_lists_sites(client):
    synced = SiteFactory(name="A-Site")
    SiteFactory(name="B-Site")
    m = MasterProductFactory(sku="SP-1")
    ProductMappingFactory(master=m, site=synced, woo_product_id=900)

    resp = client.get(f"/api/products/{m.id}/sync_status/")
    assert resp.status_code == 200
    by_name = {r["site_name"]: r for r in resp.data}
    assert by_name["A-Site"]["synced"] is True
    assert by_name["A-Site"]["woo_product_id"] == 900
    assert by_name["B-Site"]["synced"] is False
