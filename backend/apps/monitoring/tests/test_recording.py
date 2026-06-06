"""The health-check history is fed by apps.sites.services.test_connection —
every manual or periodic check appends one row."""

import httpx
import pytest

from apps.integrations.woocommerce import WooClient
from apps.monitoring.models import HealthCheck
from apps.sites import services as site_services
from apps.sites.tests.factories import SiteFactory


@pytest.mark.django_db
def test_test_connection_records_history(monkeypatch, user):
    monkeypatch.setattr(WooClient, "system_status", lambda self: {"environment": {}})
    site = SiteFactory()

    result = site_services.test_connection(
        site, check_type="manual", performed_by=user
    )

    assert "response_time_ms" in result
    check = HealthCheck.objects.get(site=site)
    assert check.ok is True
    assert check.check_type == HealthCheck.CheckType.MANUAL
    assert check.performed_by == user
    assert check.response_time_ms is not None


@pytest.mark.django_db
def test_failed_connection_records_critical(monkeypatch):
    def boom(self):
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(WooClient, "system_status", boom)
    site = SiteFactory()

    # The periodic Celery path runs through check_hosting (check_type="periodic");
    # here we exercise the default direct call (manual, no user).
    site_services.test_connection(site)

    check = HealthCheck.objects.get(site=site)
    assert check.ok is False
    assert check.status == HealthCheck.Status.CRITICAL
    assert check.check_type == HealthCheck.CheckType.MANUAL
    assert check.performed_by is None


@pytest.mark.django_db
def test_api_action_attributes_check_to_request_user(client, user, monkeypatch):
    monkeypatch.setattr(WooClient, "system_status", lambda self: {"environment": {}})
    site = SiteFactory()

    resp = client.post(f"/api/sites/{site.id}/test_connection/")

    assert resp.status_code == 200
    check = HealthCheck.objects.get(site=site)
    assert check.check_type == HealthCheck.CheckType.MANUAL
    assert check.performed_by == user
