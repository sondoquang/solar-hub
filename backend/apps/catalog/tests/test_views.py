import pytest

from apps.catalog.models import MasterProduct
from apps.catalog.tests.factories import (
    CategoryFactory,
    CategoryMappingFactory,
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
        lambda site_ids=None, master_ids=None, run_id=None, triggered_by_id=None: captured.update(
            site_ids=site_ids, master_ids=master_ids, run_id=run_id, triggered_by_id=triggered_by_id
        )
        or _Result(),
    )

    resp = client.post("/api/products/sync_now/", {"sites": [1, 2], "products": [5]}, format="json")
    assert resp.status_code == 200
    # run_id + expected drive the progress banner; run_id is threaded to the task.
    assert resp.data["task_id"] == "task-123"
    assert resp.data["run_id"] == captured["run_id"]
    assert resp.data["expected"] == 0  # no sites in this test DB
    assert captured["site_ids"] == [1, 2]
    assert captured["master_ids"] == [5]
    assert "triggered_by_id" in captured  # threaded from request.user


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
def test_categories_picker_returns_full_catalog_in_one_page(client):
    # The form picker loads everything with one big page; the default
    # max_page_size=100 used to truncate big catalogs silently, so categories
    # past the cutoff never showed up in the product-form TreeSelect.
    from apps.catalog.models import Category

    Category.objects.bulk_create(Category(name=f"Danh mục {i:03d}") for i in range(150))
    resp = client.get("/api/products/categories/", {"page_size": 1000})
    assert resp.status_code == 200
    assert resp.data["count"] == 150
    assert len(resp.data["results"]) == 150
    assert resp.data["next"] is None


@pytest.mark.django_db
def test_categories_pull_now_dispatches_task(client, user, monkeypatch):
    from apps.sync import tasks

    captured = {}

    class _Result:
        id = "cat-1"

    monkeypatch.setattr(
        tasks.pull_all_categories,
        "delay",
        lambda site_ids=None, run_id=None, triggered_by_id=None: captured.update(
            site_ids=site_ids, run_id=run_id, triggered_by_id=triggered_by_id
        )
        or _Result(),
    )

    resp = client.post("/api/products/categories/pull_now/", {"sites": [3]}, format="json")
    assert resp.status_code == 200
    assert resp.data["task_id"] == "cat-1"
    # The view mints the run_id, returns it AND passes the same one to the task
    # — that's what lets the report group this click's SyncLog rows.
    assert resp.data["run_id"] == captured["run_id"]
    assert captured["site_ids"] == [3]
    # The clicking admin is threaded onto the task → onto each SyncLog row.
    assert captured["triggered_by_id"] == user.id


@pytest.mark.django_db
def test_categories_clear_all_returns_counts(client):
    """Clears unused categories + history, keeps in-use ones, returns counts."""
    from apps.sync.models import SyncLog

    site = SiteFactory()
    used = CategoryFactory(name="Pin mặt trời")
    orphan = CategoryFactory(name="Rác")
    MasterProductFactory(sku="SP-1", categories=["Pin mặt trời"])
    CategoryMappingFactory(category=orphan, site=site)
    SyncLog.objects.create(site=site, operation="pull_categories", status="success")

    resp = client.post("/api/products/categories/clear_all/", format="json")

    assert resp.status_code == 200
    assert resp.data["categories_kept"] == 1
    assert resp.data["categories_cleared"] == 1
    assert resp.data["history_cleared"] == 1
    used.refresh_from_db()
    orphan.refresh_from_db()
    assert used.is_deleted is False
    assert orphan.is_deleted is True


@pytest.mark.django_db
def test_categories_clear_all_requires_auth():
    from rest_framework.test import APIClient

    resp = APIClient().post("/api/products/categories/clear_all/", format="json")
    assert resp.status_code in (401, 403)


# --- per-site category mappings ------------------------------------------------


@pytest.mark.django_db
def test_category_mappings_requires_site(client):
    assert client.get("/api/products/categories/mappings/").status_code == 400
    assert client.get("/api/products/categories/mappings/", {"site": "abc"}).status_code == 400


@pytest.mark.django_db
def test_category_mappings_lists_for_site(client):
    site, other = SiteFactory(), SiteFactory()
    parent = CategoryFactory(name="Sản phẩm")
    pin = CategoryFactory(name="Pin mặt trời", parent=parent)
    CategoryMappingFactory(category=pin, site=site, woo_category_id=220, woo_name=" Pin  mặt trời ")
    CategoryMappingFactory(site=other)  # site khác — không được lẫn vào

    resp = client.get("/api/products/categories/mappings/", {"site": site.id})
    assert resp.status_code == 200
    assert resp.data["count"] == 1
    row = resp.data["results"][0]
    assert row["woo_category_id"] == 220
    assert row["woo_name"] == " Pin  mặt trời "  # tên RAW trên site
    assert row["category_id"] == pin.id
    assert row["category_name"] == "Pin mặt trời"
    assert row["category_parent_id"] == parent.id
    assert row["category_parent_name"] == "Sản phẩm"


@pytest.mark.django_db
def test_category_mappings_search(client):
    site = SiteFactory()
    CategoryMappingFactory(
        category=CategoryFactory(name="Pin mặt trời"),
        site=site,
        woo_category_id=104,
        woo_name="Pin mặt trời",
    )
    CategoryMappingFactory(
        category=CategoryFactory(name="Inverter"),
        site=site,
        woo_category_id=300,
        woo_name="Biến tần",
    )

    def names(params):
        resp = client.get("/api/products/categories/mappings/", {"site": site.id, **params})
        return [r["category_name"] for r in resp.data["results"]]

    assert names({"search": "Biến"}) == ["Inverter"]  # theo woo_name
    assert names({"search": "Inver"}) == ["Inverter"]  # theo tên Hub
    assert names({"search": "104"}) == ["Pin mặt trời"]  # theo woo_category_id


@pytest.mark.django_db
def test_category_mappings_excludes_deleted_categories(client):
    site = SiteFactory()
    CategoryMappingFactory(category=CategoryFactory(is_deleted=True), site=site)
    resp = client.get("/api/products/categories/mappings/", {"site": site.id})
    assert resp.data["count"] == 0


# --- category dashboard: overview / matrix / per-category sites ---------------


@pytest.mark.django_db
def test_category_overview_counts(client):
    s1, s2 = SiteFactory(), SiteFactory()
    root = CategoryFactory(name="Ắc quy")
    CategoryFactory(name="Ắc quy khô", parent=root)  # live child, unlinked
    CategoryMappingFactory(category=root, site=s1)
    CategoryMappingFactory(category=root, site=s2)
    CategoryFactory(name="Đã xóa", is_deleted=True)

    data = client.get("/api/products/categories/overview/").data
    assert data["hub_used"] == 2  # root + child (live)
    assert data["hub_total"] == 3  # + soft-deleted
    assert data["linked"] == 1  # only root is on a site
    assert data["unlinked"] == 1
    assert data["linked_pct"] == 50.0
    assert data["site_count"] == 2
    assert data["root_count"] == 1
    assert data["child_count"] == 1
    assert data["deleted_count"] == 1


@pytest.mark.django_db
def test_category_matrix_pivots_sites(client):
    s1 = SiteFactory(name="solarcity.com.vn")
    s2 = SiteFactory(name="demowp.com")
    root = CategoryFactory(name="Ắc quy")
    phoenix = CategoryFactory(name="Ắc quy Phoenix", parent=root)
    CategoryMappingFactory(
        category=phoenix, site=s1, woo_category_id=124, woo_name="Ắc Quy Phoenix"
    )
    CategoryMappingFactory(
        category=phoenix, site=s2, woo_category_id=871, woo_name="Ác Quy Phoenix"
    )

    data = client.get("/api/products/categories/matrix/").data
    # The response carries every live site as a dynamic column header.
    assert {s["id"] for s in data["sites"]} == {s1.id, s2.id}

    row = next(r for r in data["results"] if r["name"] == "Ắc quy Phoenix")
    assert row["parent_name"] == "Ắc quy"
    assert row["linked_site_count"] == 2
    assert row["cells"][str(s1.id)] == {"woo_id": 124, "woo_name": "Ắc Quy Phoenix"}
    assert row["cells"][str(s2.id)]["woo_id"] == 871

    # Root has no mappings → empty cells, count 0.
    root_row = next(r for r in data["results"] if r["name"] == "Ắc quy")
    assert root_row["cells"] == {}
    assert root_row["linked_site_count"] == 0


@pytest.mark.django_db
def test_category_matrix_excludes_soft_deleted_site(client):
    live = SiteFactory(name="live.vn")
    gone = SiteFactory(name="gone.vn", is_deleted=True)
    cat = CategoryFactory(name="Ắc quy")
    CategoryMappingFactory(category=cat, site=live, woo_category_id=10)
    CategoryMappingFactory(category=cat, site=gone, woo_category_id=20)

    data = client.get("/api/products/categories/matrix/").data
    assert {s["id"] for s in data["sites"]} == {live.id}  # soft-deleted site dropped
    row = data["results"][0]
    assert list(row["cells"].keys()) == [str(live.id)]
    assert row["linked_site_count"] == 1  # the gone site's mapping is not counted


@pytest.mark.django_db
def test_category_matrix_search_by_name_or_parent(client):
    root = CategoryFactory(name="Ắc quy")
    CategoryFactory(name="Ắc quy khô", parent=root)
    CategoryFactory(name="Inverter")

    def names(params):
        return [r["name"] for r in client.get("/api/products/categories/matrix/", params).data["results"]]

    assert names({"search": "khô"}) == ["Ắc quy khô"]  # by own name
    # "Ắc quy" matches the root by name and the child by parent name.
    assert set(names({"search": "Ắc quy"})) == {"Ắc quy", "Ắc quy khô"}


@pytest.mark.django_db
def test_category_sites_lists_link_state(client):
    linked = SiteFactory(name="A-Site", status="up", is_primary=True)
    SiteFactory(name="B-Site", status="down")
    cat = CategoryFactory(name="Ắc quy")
    CategoryMappingFactory(category=cat, site=linked, woo_category_id=872, woo_name="Ắc quy")

    resp = client.get(f"/api/products/categories/{cat.id}/sites/")
    assert resp.status_code == 200
    by_name = {r["site_name"]: r for r in resp.data}
    assert by_name["A-Site"]["linked"] is True
    assert by_name["A-Site"]["woo_category_id"] == 872
    assert by_name["A-Site"]["woo_name"] == "Ắc quy"
    assert by_name["A-Site"]["is_primary"] is True
    assert by_name["B-Site"]["linked"] is False
    assert by_name["B-Site"]["woo_category_id"] is None


# --- per-product sync status --------------------------------------------------


@pytest.mark.django_db
def test_sync_status_lists_sites(client):
    synced = SiteFactory(
        name="A-Site", status="up", base_url="https://a-site.example.com", is_primary=True
    )
    SiteFactory(name="B-Site", status="down")
    m = MasterProductFactory(sku="SP-1")
    ProductMappingFactory(master=m, site=synced, woo_product_id=900)

    resp = client.get(f"/api/products/{m.id}/sync_status/")
    assert resp.status_code == 200
    by_name = {r["site_name"]: r for r in resp.data}
    assert by_name["A-Site"]["synced"] is True
    assert by_name["A-Site"]["woo_product_id"] == 900
    assert by_name["A-Site"]["site_status"] == "up"
    assert by_name["A-Site"]["site_url"] == "https://a-site.example.com"
    assert by_name["A-Site"]["is_primary"] is True
    assert by_name["B-Site"]["synced"] is False
    assert by_name["B-Site"]["site_status"] == "down"
    assert by_name["B-Site"]["is_primary"] is False


# --- product media library ----------------------------------------------------


@pytest.fixture()
def _media_root(settings, tmp_path):
    # Write uploads to a throwaway dir, not the repo's backend/media.
    settings.MEDIA_ROOT = str(tmp_path)


def make_image(name="a.png", fmt="PNG", content_type="image/png"):
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, format=fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=content_type)


@pytest.mark.django_db
def test_media_upload_returns_absolute_url(client, _media_root, settings):
    settings.MEDIA_PUBLIC_BASE_URL = ""  # isolate from the developer's .env
    resp = client.post("/api/products/media/", {"image": make_image("pin.png")}, format="multipart")
    assert resp.status_code == 201, resp.data
    assert resp.data["original_name"] == "pin.png"
    assert resp.data["url"].startswith("http://testserver/media/products/")
    # The raw file field is write-only; the client only ever sees `url`.
    assert "image" not in resp.data


@pytest.mark.django_db
def test_media_rejects_non_image(client, _media_root):
    from django.core.files.uploadedfile import SimpleUploadedFile

    bad = SimpleUploadedFile("x.txt", b"not an image", content_type="text/plain")
    resp = client.post("/api/products/media/", {"image": bad}, format="multipart")
    assert resp.status_code == 400
    assert "image" in resp.data


@pytest.mark.django_db
def test_media_list_newest_first_and_delete_removes_file(client, _media_root):
    from pathlib import Path

    from apps.catalog.models import ProductImage

    client.post("/api/products/media/", {"image": make_image("a.png")}, format="multipart")
    created = client.post(
        "/api/products/media/", {"image": make_image("b.png")}, format="multipart"
    ).data

    resp = client.get("/api/products/media/")
    assert resp.status_code == 200
    names = [r["original_name"] for r in resp.data["results"]]
    assert names == ["b.png", "a.png"]

    img = ProductImage.objects.get(id=created["id"])
    stored = Path(img.image.path)
    assert stored.exists()
    assert client.delete(f"/api/products/media/{created['id']}/").status_code == 204
    assert not ProductImage.objects.filter(id=created["id"]).exists()
    assert not stored.exists()


@pytest.mark.django_db
def test_media_url_uses_public_base_when_configured(client, _media_root, settings):
    settings.MEDIA_PUBLIC_BASE_URL = "https://hub.example.com"
    resp = client.post("/api/products/media/", {"image": make_image("pin.png")}, format="multipart")
    assert resp.status_code == 201, resp.data
    assert resp.data["url"].startswith("https://hub.example.com/media/products/")


@pytest.mark.django_db
def test_set_media_public_url_rewrites_stored_media_urls():
    from django.core.management import call_command

    m = MasterProductFactory(
        sku="SP-IMG",
        images=[
            "http://localhost:8000/media/products/2026/06/a.png",
            "https://shop.example.com/wp-content/keep-me.png",  # not Hub media
        ],
        description='<p>x</p><img src="https://old-tunnel.trycloudflare.com/media/products/b.png">',
        variations=[{"sku": "SP-IMG-1", "image": "http://localhost:8000/media/products/c.png"}],
    )
    call_command("set_media_public_url", "https://hub.example.com")
    m.refresh_from_db()
    assert m.images == [
        "https://hub.example.com/media/products/2026/06/a.png",
        "https://shop.example.com/wp-content/keep-me.png",
    ]
    assert 'src="https://hub.example.com/media/products/b.png"' in m.description
    assert m.variations[0]["image"] == "https://hub.example.com/media/products/c.png"


@pytest.mark.django_db
def test_media_webp_upload_is_stored_as_png(client, _media_root, settings):
    """Many WP sites reject webp sideload (kills the whole product in the
    batch), so webp uploads are re-encoded to PNG at the door."""
    settings.MEDIA_PUBLIC_BASE_URL = ""
    resp = client.post(
        "/api/products/media/",
        {"image": make_image("pin.webp", fmt="WEBP", content_type="image/webp")},
        format="multipart",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["url"].endswith(".png")

    from apps.catalog.models import ProductImage

    img = ProductImage.objects.get(id=resp.data["id"])
    assert img.image.name.endswith(".png")
    from PIL import Image as PILImage

    assert PILImage.open(img.image.path).format == "PNG"
