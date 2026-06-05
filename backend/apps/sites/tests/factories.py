import factory

from apps.sites.crypto import encrypt_secret
from apps.sites.models import Hosting, Site


class HostingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Hosting

    name = factory.Sequence(lambda n: f"Hosting {n}")
    provider = "TenTen"
    check_concurrency = 5


class SiteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Site

    name = factory.Sequence(lambda n: f"Site {n}")
    base_url = factory.Sequence(lambda n: f"https://shop{n}.example.com")
    consumer_key = "ck_test"
    consumer_secret_enc = factory.LazyFunction(lambda: encrypt_secret("cs_secret"))
