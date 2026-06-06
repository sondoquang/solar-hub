import factory
from django.utils import timezone

from apps.orders.models import Order
from apps.sites.tests.factories import SiteFactory


class OrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Order

    site = factory.SubFactory(SiteFactory)
    woo_order_id = factory.Sequence(lambda n: 1000 + n)
    number = factory.Sequence(lambda n: str(1000 + n))
    status = "processing"
    currency = "VND"
    total = "150000.00"
    customer_name = "Trần Thị B"
    customer_phone = "0900000000"
    customer_email = "kh@example.com"
    line_items = factory.LazyFunction(
        lambda: [{"sku": "SP-1", "name": "Pin mặt trời", "quantity": 1, "total": "150000.00"}]
    )
    date_created_woo = factory.LazyFunction(timezone.now)
    date_modified_woo = factory.LazyFunction(timezone.now)
