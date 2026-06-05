import factory

from apps.sites.crypto import encrypt_secret
from apps.sites.models import Site


class SiteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Site

    name = factory.Sequence(lambda n: f"Site {n}")
    base_url = "https://shop.example.com"
    consumer_key = "ck_test"
    consumer_secret_enc = factory.LazyFunction(lambda: encrypt_secret("cs_secret"))
