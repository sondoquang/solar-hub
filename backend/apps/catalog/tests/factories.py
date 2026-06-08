import factory

from apps.catalog.models import MasterProduct, ProductMapping
from apps.sites.tests.factories import SiteFactory


class MasterProductFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MasterProduct

    sku = factory.Sequence(lambda n: f"SP-{n}")
    name = factory.Sequence(lambda n: f"Sản phẩm {n}")
    regular_price = "150000.00"
    status = "publish"
    stock_status = "instock"
    categories = factory.LazyFunction(lambda: ["Pin mặt trời"])
    images = factory.LazyFunction(list)


class ProductMappingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProductMapping

    master = factory.SubFactory(MasterProductFactory)
    site = factory.SubFactory(SiteFactory)
    woo_product_id = factory.Sequence(lambda n: 5000 + n)
