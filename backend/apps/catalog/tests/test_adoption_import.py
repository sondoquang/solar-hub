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
