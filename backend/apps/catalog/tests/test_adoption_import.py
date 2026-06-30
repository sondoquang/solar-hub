"""Name-based adoption (push) + product import from a site.

Reuses the no-HTTP ``_FakeClient`` / ``_patch_client`` from test_services so the
push/import flow runs against an in-memory client that echoes ids like Woo.
"""

import uuid

import pytest

from apps.catalog import services
from apps.catalog.models import MasterProduct, ProductMapping
from apps.catalog.tests.factories import MasterProductFactory, ProductMappingFactory
from apps.catalog.tests.test_services import _FakeClient, _patch_client
from apps.sites.tests.factories import SiteFactory
from apps.sync.models import SyncLog

# --- normalize_match_name ----------------------------------------------------


def test_normalize_match_name_folds_diacritics_and_lowercases():
    # Accented / unaccented Vietnamese names converge; đ → d.
    assert services.normalize_match_name("  Tấm Pin  Mặt Trời ") == "tam pin mat troi"
    assert services.normalize_match_name("Tam Pin Mat Troi") == "tam pin mat troi"
    assert services.normalize_match_name("Đèn LED") == "den led"


def test_normalize_match_name_keeps_diacritics_when_flag_off(settings):
    settings.PRODUCT_MATCH_FOLD_DIACRITICS = False
    assert services.normalize_match_name(" Tấm Pin ") == "tấm pin"


# --- name-based adoption -----------------------------------------------------


@pytest.mark.django_db
def test_adopt_links_existing_product_then_updates(monkeypatch):
    """A site product whose normalized name matches the master's match_name is
    adopted (mapping created) and pushed as an UPDATE, not a duplicate create."""
    site = SiteFactory()
    master = MasterProductFactory(sku="SP-1", match_name="Tấm Pin Mặt Trời", categories=[])
    fake = _FakeClient(
        products=[{"id": 555, "name": "tam pin mat troi", "sku": "OLD", "type": "simple"}]
    )
    _patch_client(monkeypatch, fake)

    result = services.push_products_to_site(site, masters=[master])

    assert result["created"] == 0 and result["updated"] == 1
    mapping = ProductMapping.objects.get(master=master, site=site)
    assert mapping.woo_product_id == 555  # adopted the existing site product
    assert fake.calls[0]["update"][0]["id"] == 555
    assert not fake.calls[0]["create"]
    log = SyncLog.objects.get(site=site)
    assert log.detail["adopted"] == ["SP-1"]
    assert log.detail["adopted_count"] == 1


@pytest.mark.django_db
def test_adopt_falls_back_to_name_when_no_match_name(monkeypatch):
    """A hand-created master (blank match_name) adopts by its ``name``."""
    site = SiteFactory()
    master = MasterProductFactory(sku="SP-1", name="Inverter 5kW", match_name="", categories=[])
    fake = _FakeClient(
        products=[{"id": 42, "name": "INVERTER 5KW", "sku": "X", "type": "simple"}]
    )
    _patch_client(monkeypatch, fake)

    services.push_products_to_site(site, masters=[master])

    assert ProductMapping.objects.get(master=master, site=site).woo_product_id == 42


@pytest.mark.django_db
def test_adopt_not_found_creates_as_before(monkeypatch):
    """No name match on the site → the master is created (regression-safe)."""
    site = SiteFactory()
    master = MasterProductFactory(sku="SP-1", match_name="Khác Hẳn", categories=[])
    fake = _FakeClient(
        products=[{"id": 7, "name": "Hoàn toàn khác", "sku": "Y", "type": "simple"}]
    )
    _patch_client(monkeypatch, fake)

    result = services.push_products_to_site(site, masters=[master])

    assert result["created"] == 1 and result["updated"] == 0
    assert fake.calls[0]["create"]
    assert ProductMapping.objects.get(master=master, site=site).woo_product_id == 9000


@pytest.mark.django_db
def test_adopt_ambiguous_name_is_skipped_not_created(monkeypatch):
    """Two site products share the normalized name → not adopted AND not created
    (would duplicate); reported in detail as ambiguous, run flagged PARTIAL."""
    site = SiteFactory()
    run_id = uuid.uuid4()
    master = MasterProductFactory(sku="SP-1", match_name="Pin", categories=[])
    fake = _FakeClient(
        products=[
            {"id": 1, "name": "Pin", "sku": "A", "type": "simple"},
            {"id": 2, "name": "PIN", "sku": "B", "type": "simple"},
        ]
    )
    _patch_client(monkeypatch, fake)

    result = services.push_products_to_site(site, masters=[master], run_id=run_id)

    assert result["created"] == 0 and result["updated"] == 0
    assert not ProductMapping.objects.filter(master=master, site=site).exists()
    assert not fake.calls  # nothing planned → no batch call
    log = SyncLog.objects.get(site=site, run_id=run_id)
    assert log.status == SyncLog.Status.PARTIAL
    assert log.detail["ambiguous"] == ["SP-1"]


@pytest.mark.django_db
def test_adopt_skips_claimed_woo_id(monkeypatch):
    """A site product already mapped to another master is not re-adopted (the
    (site, woo_product_id) unique constraint) — the second master is created."""
    site = SiteFactory()
    other = MasterProductFactory(sku="SP-OTHER", categories=[])
    ProductMappingFactory(master=other, site=site, woo_product_id=555)
    master = MasterProductFactory(sku="SP-1", match_name="Pin", categories=[])
    fake = _FakeClient(products=[{"id": 555, "name": "Pin", "sku": "A", "type": "simple"}])
    _patch_client(monkeypatch, fake)

    result = services.push_products_to_site(site, masters=[master])

    assert result["created"] == 1
    assert ProductMapping.objects.get(master=master, site=site).woo_product_id == 9000


@pytest.mark.django_db
def test_adopt_runs_once_then_relies_on_mapping(monkeypatch):
    """After the first adoption the mapping is stable — a second push never lists
    the site's products again (no name match on every run)."""
    site = SiteFactory()
    master = MasterProductFactory(sku="SP-1", match_name="Pin", categories=[])
    fake = _FakeClient(products=[{"id": 99, "name": "Pin", "sku": "A", "type": "simple"}])
    _patch_client(monkeypatch, fake)

    services.push_products_to_site(site, masters=[master])
    services.push_products_to_site(site, masters=[master])

    assert fake.list_products_calls == 1  # second run had no unmapped candidate


@pytest.mark.django_db
def test_adopt_skipped_for_sapo_sites(monkeypatch):
    """v1 scopes name adoption to WooCommerce — a Sapo push never lists products
    for matching (keeps the old SKU/mapping behaviour, no extra per-store call)."""
    from apps.sites.models import Site

    site = SiteFactory(platform=Site.Platform.SAPO, sapo_store_host="a.mysapo.net")
    master = MasterProductFactory(sku="SP-1", match_name="Pin", categories=[])
    # A name-matching product exists on the store, but adoption must NOT run.
    fake = _FakeClient(products=[{"id": 555, "name": "Pin", "sku": "A", "type": "simple"}])
    _patch_client(monkeypatch, fake)

    result = services.push_products_to_site(site, masters=[master])

    assert fake.list_products_calls == 0  # adoption skipped for Sapo
    assert result["created"] == 1  # created via the normal path, not adopted to 555
    assert ProductMapping.objects.get(master=master, site=site).woo_product_id == 9000


@pytest.mark.django_db
def test_adopt_http_error_logs_and_returns(monkeypatch):
    """A network failure listing the site's products aborts only this site."""
    site = SiteFactory()
    master = MasterProductFactory(sku="SP-1", categories=[])
    fake = _FakeClient(raise_error=True)
    _patch_client(monkeypatch, fake)

    result = services.push_products_to_site(site, masters=[master])

    assert result["error"] == "ConnectError"
    assert SyncLog.objects.get(site=site).status == SyncLog.Status.ERROR


# --- import_products_from_site -----------------------------------------------


@pytest.mark.django_db
def test_import_creates_masters_and_maps(monkeypatch):
    site = SiteFactory()
    fake = _FakeClient(
        products=[
            {
                "id": 11,
                "name": "Tấm Pin 450W",
                "sku": "PIN-450",
                "type": "simple",
                "regular_price": "1500000",
                "status": "publish",
                "stock_status": "instock",
            }
        ]
    )
    _patch_client(monkeypatch, fake)

    result = services.import_products_from_site(site)

    assert result["created"] == 1 and result["linked"] == 0
    master = MasterProduct.objects.get(sku="PIN-450")
    assert master.match_name == "tam pin 450w"  # frozen, normalized
    assert master.source_site_id == site.id
    assert master.imported_at is not None
    assert ProductMapping.objects.get(master=master, site=site).woo_product_id == 11
    log = SyncLog.objects.get(site=site, operation="import_products")
    assert log.status == SyncLog.Status.SUCCESS
    assert log.detail["created"] == 1


@pytest.mark.django_db
def test_import_links_existing_sku_without_creating(monkeypatch):
    site = SiteFactory()
    existing = MasterProductFactory(sku="PIN-450")
    fake = _FakeClient(
        products=[{"id": 11, "name": "Pin", "sku": "PIN-450", "type": "simple"}]
    )
    _patch_client(monkeypatch, fake)

    result = services.import_products_from_site(site)

    assert result["created"] == 0 and result["linked"] == 1
    assert ProductMapping.objects.get(master=existing, site=site).woo_product_id == 11


@pytest.mark.django_db
def test_import_skips_already_mapped(monkeypatch):
    site = SiteFactory()
    master = MasterProductFactory(sku="PIN-450")
    ProductMappingFactory(master=master, site=site, woo_product_id=11)
    fake = _FakeClient(
        products=[{"id": 11, "name": "Pin", "sku": "PIN-450", "type": "simple"}]
    )
    _patch_client(monkeypatch, fake)

    result = services.import_products_from_site(site)

    assert result["created"] == 0 and result["linked"] == 0 and result["skipped"] == 1


@pytest.mark.django_db
def test_import_skips_non_simple_types(monkeypatch):
    site = SiteFactory()
    fake = _FakeClient(
        products=[
            {"id": 1, "name": "Combo", "sku": "C-1", "type": "grouped"},
            {"id": 2, "name": "Biến thể", "sku": "V-1", "type": "variable"},
            {"id": 3, "name": "Đơn", "sku": "S-1", "type": "simple"},
        ]
    )
    _patch_client(monkeypatch, fake)

    result = services.import_products_from_site(site)

    assert result["created"] == 1  # only the simple one
    log = SyncLog.objects.get(site=site, operation="import_products")
    assert log.detail["skipped"] == 2
    assert log.detail["skipped_types"] == {"grouped": 1, "variable": 1}


@pytest.mark.django_db
def test_import_placeholder_sku_when_blank(monkeypatch):
    site = SiteFactory()
    fake = _FakeClient(products=[{"id": 11, "name": "Pin", "sku": "", "type": "simple"}])
    _patch_client(monkeypatch, fake)

    services.import_products_from_site(site)

    assert MasterProduct.objects.filter(sku=f"IMPORT-{site.id}-11").exists()


# --- import-time image internalization ---------------------------------------
# A product imported from one site carries that site's image URLs; pushing it to
# OTHER sites then fails to sideload them (the source is usually unreachable from
# the target). Import downloads the images into the Hub media library so an
# imported product behaves like a Hub-created one. See services._internalize_*.


@pytest.fixture()
def _media_root(settings, tmp_path):
    # Write downloaded images to a throwaway dir, not the repo's backend/media,
    # and make the Hub URL public/deterministic for assertions.
    settings.MEDIA_ROOT = str(tmp_path)
    settings.MEDIA_PUBLIC_BASE_URL = "https://hub.test"


def _png_bytes():
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2, 2), "blue").save(buf, format="PNG")
    return buf.getvalue()


def _fake_fetcher(calls, *, data=None, content_type="image/png"):
    """A stand-in for services._fetch_image_bytes that records the URLs it was
    asked to download and returns canned image bytes (no real HTTP)."""
    payload = data if data is not None else _png_bytes()

    def _fetch(url):
        calls.append(url)
        return payload, content_type

    return _fetch


def _woo_product(**over):
    item = {
        "id": 11,
        "name": "Tấm Pin 450W",
        "sku": "PIN-450",
        "type": "simple",
        "status": "publish",
        "stock_status": "instock",
    }
    item.update(over)
    return item


@pytest.mark.django_db
def test_import_internalizes_gallery_and_description_images(monkeypatch, _media_root):
    site = SiteFactory()
    src_main = "https://site-a.example/wp-content/uploads/main.jpg"
    src_desc = "https://site-a.example/wp-content/uploads/desc.jpg"
    fake = _FakeClient(
        products=[
            _woo_product(
                images=[{"src": src_main}],
                description=f'<p>xem</p><img src="{src_desc}"/>',
            )
        ]
    )
    _patch_client(monkeypatch, fake)
    calls = []
    monkeypatch.setattr(services, "_fetch_image_bytes", _fake_fetcher(calls))

    result = services.import_products_from_site(site)

    master = MasterProduct.objects.get(sku="PIN-450")
    # Gallery + description both point at the Hub now, not the source site.
    assert master.images and all(
        u.startswith("https://hub.test/media/products/") for u in master.images
    )
    assert src_main not in master.images
    assert "https://hub.test/media/products/" in master.description
    assert "site-a.example" not in master.description
    # Both remote images were downloaded; the report counts them.
    assert set(calls) == {src_main, src_desc}
    assert result["images_internalized"] == 2
    log = SyncLog.objects.get(site=site, operation="import_products")
    assert log.detail["images_internalized"] == 2
    assert log.detail["image_download_failures"] == 0


@pytest.mark.django_db
def test_import_downloads_a_shared_image_once(monkeypatch, _media_root):
    """Same URL in the gallery and the description is fetched a single time."""
    site = SiteFactory()
    shared = "https://site-a.example/wp-content/uploads/hero.jpg"
    fake = _FakeClient(
        products=[_woo_product(images=[{"src": shared}], description=f'<img src="{shared}">')]
    )
    _patch_client(monkeypatch, fake)
    calls = []
    monkeypatch.setattr(services, "_fetch_image_bytes", _fake_fetcher(calls))

    result = services.import_products_from_site(site)

    assert calls == [shared]  # downloaded once, reused
    assert result["images_internalized"] == 1


@pytest.mark.django_db
def test_import_keeps_source_url_when_download_fails(monkeypatch, _media_root):
    site = SiteFactory()
    src = "https://site-a.example/wp-content/uploads/main.jpg"
    fake = _FakeClient(products=[_woo_product(images=[{"src": src}])])
    _patch_client(monkeypatch, fake)
    monkeypatch.setattr(services, "_fetch_image_bytes", lambda url: None)

    result = services.import_products_from_site(site)

    master = MasterProduct.objects.get(sku="PIN-450")
    assert master.images == [src]  # left as a hot-link, better than dropping it
    assert result["images_internalized"] == 0
    assert result["image_download_failures"] == 1


def test_normalize_remote_image_url_adds_scheme_to_protocol_relative():
    # Protocol-relative srcs (common from CDN-hosted images) get an https scheme so
    # httpx does not reject them with UnsupportedProtocol; everything else is kept.
    assert (
        services._normalize_remote_image_url("//bizweb.dktcdn.net/100/files/x.jpg")
        == "https://bizweb.dktcdn.net/100/files/x.jpg"
    )
    assert (
        services._normalize_remote_image_url("https://site-a.example/x.jpg")
        == "https://site-a.example/x.jpg"
    )
    assert services._normalize_remote_image_url("/media/products/x.png") == "/media/products/x.png"
    assert services._normalize_remote_image_url("") == ""


@pytest.mark.django_db
def test_import_internalizes_protocol_relative_images(monkeypatch, _media_root):
    """Protocol-relative srcs (``//cdn/...``) are normalized to https before the
    download, so they internalize instead of failing with UnsupportedProtocol."""
    site = SiteFactory()
    gallery = "//bizweb.dktcdn.net/100/414/235/files/data.jpg"
    desc = "//bizweb.dktcdn.net/100/414/235/files/spec.png"
    fake = _FakeClient(
        products=[_woo_product(images=[{"src": gallery}], description=f'<img src="{desc}"/>')]
    )
    _patch_client(monkeypatch, fake)
    calls = []
    monkeypatch.setattr(services, "_fetch_image_bytes", _fake_fetcher(calls))

    result = services.import_products_from_site(site)

    # httpx was handed schemed URLs, never the raw //... form.
    assert set(calls) == {
        "https://bizweb.dktcdn.net/100/414/235/files/data.jpg",
        "https://bizweb.dktcdn.net/100/414/235/files/spec.png",
    }
    master = MasterProduct.objects.get(sku="PIN-450")
    assert master.images and all(
        u.startswith("https://hub.test/media/products/") for u in master.images
    )
    assert "https://hub.test/media/products/" in master.description
    assert "bizweb.dktcdn.net" not in master.description
    assert result["images_internalized"] == 2
    assert result["image_download_failures"] == 0


def test_fetch_image_bytes_swallows_invalid_url(monkeypatch):
    # httpx.InvalidURL is NOT an httpx.HTTPError subclass; a too-long src (e.g. a
    # base64 data: URI that slips through) must be swallowed, not crash the import.
    def _boom(*a, **k):
        raise services.httpx.InvalidURL("URL too long")

    monkeypatch.setattr(services.httpx, "get", _boom)
    assert services._fetch_image_bytes("https://x.example/huge.jpg") is None


@pytest.mark.django_db
def test_import_leaves_data_uri_images_untouched(monkeypatch, _media_root):
    """A base64 data: URI in the description is self-contained — never fetched
    (httpx would reject it as 'URL too long') and left embedded as-is."""
    site = SiteFactory()
    data_uri = "data:image/png;base64," + "A" * 5000
    fake = _FakeClient(products=[_woo_product(description=f'<img src="{data_uri}"/>')])
    _patch_client(monkeypatch, fake)
    calls = []
    monkeypatch.setattr(services, "_fetch_image_bytes", _fake_fetcher(calls))

    result = services.import_products_from_site(site)

    assert calls == []  # never attempted — not an http(s) src
    master = MasterProduct.objects.get(sku="PIN-450")
    assert data_uri in master.description
    assert result["image_download_failures"] == 0


@pytest.mark.django_db
def test_import_skips_internalization_when_disabled(monkeypatch, settings):
    settings.PRODUCT_INTERNALIZE_IMPORTED_IMAGES = False
    site = SiteFactory()
    src = "https://site-a.example/wp-content/uploads/main.jpg"
    fake = _FakeClient(products=[_woo_product(images=[{"src": src}])])
    _patch_client(monkeypatch, fake)
    calls = []
    monkeypatch.setattr(services, "_fetch_image_bytes", _fake_fetcher(calls))

    services.import_products_from_site(site)

    assert calls == []  # never touched the network
    assert MasterProduct.objects.get(sku="PIN-450").images == [src]


@pytest.mark.django_db
def test_import_linking_existing_sku_does_not_download(monkeypatch, _media_root):
    """Linking to an existing master reuses its (already-Hub) images — no fetch."""
    site = SiteFactory()
    MasterProductFactory(sku="PIN-450", images=["https://hub.test/media/products/x.png"])
    src = "https://site-a.example/wp-content/uploads/main.jpg"
    fake = _FakeClient(products=[_woo_product(images=[{"src": src}])])
    _patch_client(monkeypatch, fake)
    calls = []
    monkeypatch.setattr(services, "_fetch_image_bytes", _fake_fetcher(calls))

    result = services.import_products_from_site(site)

    assert result["linked"] == 1 and calls == []


@pytest.mark.django_db
def test_import_reencodes_webp_to_png(monkeypatch, _media_root):
    """webp is re-encoded to PNG on the way in (many WP sites reject webp
    sideload, which would kill the whole product in a later push batch)."""
    import io

    from PIL import Image

    from apps.catalog.models import ProductImage

    buf = io.BytesIO()
    Image.new("RGB", (2, 2), "green").save(buf, format="WEBP")
    site = SiteFactory()
    fake = _FakeClient(
        products=[_woo_product(images=[{"src": "https://site-a.example/up/p.webp"}])]
    )
    _patch_client(monkeypatch, fake)
    monkeypatch.setattr(
        services,
        "_fetch_image_bytes",
        _fake_fetcher([], data=buf.getvalue(), content_type="image/webp"),
    )

    services.import_products_from_site(site)

    master = MasterProduct.objects.get(sku="PIN-450")
    assert master.images[0].endswith(".png")
    assert ProductImage.objects.get().image.name.endswith(".png")


# --- internalize_imported_images management command --------------------------
# Backfill for products imported BEFORE import-time internalization existed: they
# still carry the source site's image URLs. See the command module docstring.


@pytest.mark.django_db
def test_backfill_command_internalizes_legacy_imported_master(monkeypatch, _media_root):
    from django.core.management import call_command

    src_main = "https://site-a.example/wp-content/uploads/old.jpg"
    src_desc = "https://site-a.example/wp-content/uploads/inline.jpg"
    site = SiteFactory()
    master = MasterProductFactory(
        sku="LEGACY-1",
        source_site=site,
        images=[src_main],
        description=f'<img src="{src_desc}">',
    )
    calls = []
    monkeypatch.setattr(services, "_fetch_image_bytes", _fake_fetcher(calls))

    call_command("internalize_imported_images")

    master.refresh_from_db()
    assert master.images[0].startswith("https://hub.test/media/products/")
    assert "site-a.example" not in master.description
    assert set(calls) == {src_main, src_desc}


@pytest.mark.django_db
def test_backfill_command_dry_run_downloads_nothing(monkeypatch, _media_root):
    from django.core.management import call_command

    src = "https://site-a.example/wp-content/uploads/old.jpg"
    site = SiteFactory()
    master = MasterProductFactory(sku="LEGACY-1", source_site=site, images=[src])
    calls = []
    monkeypatch.setattr(services, "_fetch_image_bytes", _fake_fetcher(calls))

    call_command("internalize_imported_images", "--dry-run")

    master.refresh_from_db()
    assert master.images == [src]  # untouched
    assert calls == []  # nothing downloaded


@pytest.mark.django_db
def test_backfill_command_skips_hand_created_and_already_hub(monkeypatch, _media_root):
    """Only imported masters with remaining remote refs are touched: a hand-created
    master (no source_site) and one already on the Hub are left alone."""
    from django.core.management import call_command

    site = SiteFactory()
    hand = MasterProductFactory(  # no source_site
        sku="HAND-1", images=["https://other.example/wp-content/x.jpg"]
    )
    done = MasterProductFactory(
        sku="IMP-OK", source_site=site, images=["https://hub.test/media/products/y.png"]
    )
    calls = []
    monkeypatch.setattr(services, "_fetch_image_bytes", _fake_fetcher(calls))

    call_command("internalize_imported_images")

    hand.refresh_from_db()
    done.refresh_from_db()
    assert hand.images == ["https://other.example/wp-content/x.jpg"]  # not imported → skipped
    assert done.images == ["https://hub.test/media/products/y.png"]  # already Hub → skipped
    assert calls == []


@pytest.mark.django_db
def test_backfill_command_requires_public_base_url(settings):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    settings.MEDIA_PUBLIC_BASE_URL = ""
    with pytest.raises(CommandError):
        call_command("internalize_imported_images")
