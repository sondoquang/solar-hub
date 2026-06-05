import pytest

from apps.sites.models import Hosting, Site
from apps.sites.serializers import HostingSerializer, SiteSerializer

from .factories import HostingFactory, SiteFactory


@pytest.mark.django_db
def test_hosting_serializer_aggregates_site_health():
    hosting = HostingFactory()
    SiteFactory(hosting=hosting, status=Site.Status.UP)
    SiteFactory(hosting=hosting, status=Site.Status.UP)
    SiteFactory(hosting=hosting, status=Site.Status.DOWN)
    SiteFactory(hosting=hosting, status=Site.Status.UNKNOWN)
    SiteFactory(hosting=hosting, is_deleted=True, status=Site.Status.UP)  # excluded

    # Mirror the viewset's prefetch so the SerializerMethodFields read .all().
    obj = Hosting.objects.prefetch_related("sites").get(id=hosting.id)
    data = HostingSerializer(obj).data

    assert data["site_count"] == 4
    assert data["status_counts"] == {"up": 2, "down": 1, "unknown": 1}


@pytest.mark.django_db
def test_site_serializer_exposes_hosting_fields():
    hosting = HostingFactory(name="Server A")
    site = SiteFactory(hosting=hosting)
    data = SiteSerializer(site).data
    assert data["hosting"] == hosting.id
    assert data["hosting_name"] == "Server A"


@pytest.mark.django_db
def test_site_serializer_hosting_optional():
    site = SiteFactory(hosting=None)
    data = SiteSerializer(site).data
    assert data["hosting"] is None
    assert data["hosting_name"] is None
