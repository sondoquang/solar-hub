import factory
from django.utils import timezone

from apps.monitoring.models import HealthCheck
from apps.sites.tests.factories import SiteFactory


class HealthCheckFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HealthCheck

    site = factory.SubFactory(SiteFactory)
    status = HealthCheck.Status.HEALTHY
    check_type = HealthCheck.CheckType.PERIODIC
    response_time_ms = 250
    ok = True
    detail = "Kết nối thành công."
    performed_by = None
    checked_at = factory.LazyFunction(timezone.now)
