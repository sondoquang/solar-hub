import factory

from apps.catalog.models import (
    Category,
    CategoryMapping,
    MasterProduct,
    ProductMapping,
    ProductVariationMapping,
)
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


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f"Danh mục {n}")


class CategoryMappingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CategoryMapping

    category = factory.SubFactory(CategoryFactory)
    site = factory.SubFactory(SiteFactory)
    woo_category_id = factory.Sequence(lambda n: 6000 + n)


class ProductVariationMappingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProductVariationMapping

    master = factory.SubFactory(MasterProductFactory)
    site = factory.SubFactory(SiteFactory)
    variation_sku = factory.Sequence(lambda n: f"SP-VAR-{n}")
    woo_variation_id = factory.Sequence(lambda n: 7000 + n)
    woo_parent_id = factory.Sequence(lambda n: 5000 + n)
