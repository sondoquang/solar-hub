import pytest

from apps.catalog.models import MasterProduct
from apps.catalog.tests.factories import MasterProductFactory, ProductMappingFactory
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
