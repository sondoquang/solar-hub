"""Tests for the Site.platform field: serializer default, client dispatch and
the optional ``platform`` column of the Excel import."""

import pytest

from apps.integrations.sapo import SapoClient
from apps.integrations.woocommerce import WooClient
from apps.sites.models import Site
from apps.sites.serializers import SiteSerializer
from apps.sites.services import client_for_site

from .factories import SiteFactory
from .test_import import make_xlsx


@pytest.mark.django_db
def test_serializer_defaults_platform_to_woocommerce():
    serializer = SiteSerializer(
        data={
            "name": "Shop",
            "base_url": "https://shop.example.com",
            "consumer_key": "ck",
            "consumer_secret": "cs",
        }
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["platform"] == Site.Platform.WOOCOMMERCE


@pytest.mark.django_db
def test_serializer_accepts_sapo_and_rejects_unknown():
    base = {
        "name": "Store",
        "base_url": "https://store.mysapo.net",
        "consumer_key": "apikey",
        "consumer_secret": "apisecret",
    }
    ok = SiteSerializer(data={**base, "platform": "sapo"})
    assert ok.is_valid(), ok.errors
    assert ok.validated_data["platform"] == Site.Platform.SAPO

    bad = SiteSerializer(data={**base, "platform": "shopify"})
    assert not bad.is_valid()
    assert "platform" in bad.errors


@pytest.mark.django_db
def test_create_site_api_persists_platform(client):
    resp = client.post(
        "/api/sites/",
        {
            "name": "Sapo Store",
            "base_url": "https://store.mysapo.net",
            "consumer_key": "apikey",
            "consumer_secret": "apisecret",
            "platform": "sapo",
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["platform"] == "sapo"
    assert Site.objects.get(name="Sapo Store").platform == Site.Platform.SAPO


@pytest.mark.django_db
def test_client_for_site_dispatches_on_platform():
    woo_site = SiteFactory()
    sapo_site = SiteFactory(platform=Site.Platform.SAPO)
    assert isinstance(client_for_site(woo_site), WooClient)
    sapo_client = client_for_site(sapo_site)
    assert isinstance(sapo_client, SapoClient)
    assert sapo_client.base == sapo_site.base_url.rstrip("/") + "/admin"


@pytest.mark.django_db
def test_list_filters_by_platform(client):
    SiteFactory(name="Woo Shop")
    SiteFactory(name="Sapo Store", platform=Site.Platform.SAPO)

    resp = client.get("/api/sites/", {"platform": "sapo"})
    names = [r["name"] for r in resp.data["results"]]
    assert names == ["Sapo Store"]

    resp = client.get("/api/sites/", {"platform": "woocommerce"})
    names = [r["name"] for r in resp.data["results"]]
    assert names == ["Woo Shop"]

    # unknown value is ignored → unfiltered list
    resp = client.get("/api/sites/", {"platform": "shopify"})
    assert resp.data["count"] == 2


@pytest.mark.django_db
def test_import_with_platform_column(client):
    buf = make_xlsx(
        [
            ("Woo Shop", "https://woo.example.com", "ck", "cs", "woocommerce"),
            ("Sapo Store", "https://store.mysapo.net", "apikey", "apisecret", "SAPO"),
            ("Default", "https://default.example.com", "ck", "cs", ""),
            ("Bad", "https://bad.example.com", "ck", "cs", "shopify"),
        ],
        header=("name", "base_url", "consumer_key", "consumer_secret", "platform"),
    )
    resp = client.post("/api/sites/import_excel/", {"file": buf}, format="multipart")
    assert resp.data["created"] == 3
    assert len(resp.data["errors"]) == 1
    assert "platform" in resp.data["errors"][0]["error"]
    assert Site.objects.get(name="Sapo Store").platform == Site.Platform.SAPO
    assert Site.objects.get(name="Default").platform == Site.Platform.WOOCOMMERCE


@pytest.mark.django_db
def test_import_without_platform_column_defaults_to_woocommerce(client):
    buf = make_xlsx([("Shop", "https://shop.example.com", "ck", "cs")])
    resp = client.post("/api/sites/import_excel/", {"file": buf}, format="multipart")
    assert resp.data["created"] == 1
    assert Site.objects.get(name="Shop").platform == Site.Platform.WOOCOMMERCE
