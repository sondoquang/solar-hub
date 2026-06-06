import pytest

from apps.monitoring.models import HealthCheck
from apps.monitoring.services import (
    derive_status,
    health_stats,
    record_check,
)
from apps.sites.tests.factories import SiteFactory


@pytest.mark.parametrize(
    "ok,ms,expected",
    [
        (True, 250, HealthCheck.Status.HEALTHY),
        (True, 999, HealthCheck.Status.HEALTHY),
        (True, 1000, HealthCheck.Status.WARNING),
        (True, 4999, HealthCheck.Status.WARNING),
        # Reachable (HTTP 2xx) is never critical, however slow — just a warning.
        (True, 5000, HealthCheck.Status.WARNING),
        (True, 8000, HealthCheck.Status.WARNING),
        (False, 50, HealthCheck.Status.CRITICAL),
        (True, None, HealthCheck.Status.HEALTHY),
    ],
)
def test_derive_status(ok, ms, expected):
    assert derive_status(ok, ms) == expected


@pytest.mark.django_db
def test_record_check_sets_status_and_system_actor():
    site = SiteFactory()
    check = record_check(site=site, ok=True, response_time_ms=1500)
    assert check.status == HealthCheck.Status.WARNING
    assert check.performed_by is None  # → "Hệ thống"
    assert check.check_type == HealthCheck.CheckType.MANUAL


@pytest.mark.django_db
def test_record_check_keeps_authenticated_actor(user):
    site = SiteFactory()
    check = record_check(
        site=site,
        ok=True,
        response_time_ms=200,
        check_type=HealthCheck.CheckType.PERIODIC,
        performed_by=user,
    )
    assert check.performed_by == user
    assert check.check_type == HealthCheck.CheckType.PERIODIC


@pytest.mark.django_db
def test_record_check_rejects_invalid_check_type():
    site = SiteFactory()
    check = record_check(site=site, ok=False, check_type="bogus")
    assert check.check_type == HealthCheck.CheckType.MANUAL


@pytest.mark.django_db
def test_health_stats_counts_by_status():
    site = SiteFactory()
    # Several rows per status so a GROUP BY polluted by the model's default
    # ordering (which would split counts per timestamp) is caught.
    for _ in range(5):
        record_check(site=site, ok=True, response_time_ms=200)  # healthy
    for _ in range(3):
        record_check(site=site, ok=True, response_time_ms=2000)  # warning
    for _ in range(2):
        record_check(site=site, ok=False)  # critical
    stats = health_stats(HealthCheck.objects.all(), {})
    assert stats == {
        "total": 10,
        "healthy": 5,
        "warning": 3,
        "critical": 2,
        "trend_pct": None,
    }
