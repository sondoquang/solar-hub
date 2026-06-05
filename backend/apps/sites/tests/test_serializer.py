import pytest

from apps.sites.serializers import SiteSerializer

from .factories import SiteFactory


@pytest.mark.django_db
def test_secret_never_in_output():
    site = SiteFactory()
    data = SiteSerializer(site).data
    assert "consumer_secret" not in data
    assert "consumer_secret_enc" not in data
    assert data["consumer_key"] == "ck_test"


def test_create_requires_secret():
    s = SiteSerializer(
        data={
            "name": "Shop",
            "base_url": "https://shop.example.com",
            "consumer_key": "ck_x",
        }
    )
    assert not s.is_valid()
    assert "consumer_secret" in s.errors
