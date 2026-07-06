"""Push notifications: open on trigger, lazy-finalize from SyncLog, bell endpoints.

The heavy per-site outcome lives on SyncLog (grouped by run_id); a Notification is
the persistent handle the app-wide bell/modal polls. Finalize is computed from the
run's SyncLog rows on read (no Celery chord), so these tests drive it by creating
the rows a real push would have written.
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.catalog.tests.factories import MasterProductFactory
from apps.sites.tests.factories import SiteFactory
from apps.sync import services
from apps.sync.models import Notification, SyncLog
from apps.sync.services import PRODUCT_OPERATION


def _plog(site, run_id, *, status=SyncLog.Status.SUCCESS, error="", created=0, updated=0, **detail):
    return SyncLog.objects.create(
        site=site,
        operation=PRODUCT_OPERATION,
        status=status,
        run_id=run_id,
        error=error,
        created_count=created,
        updated_count=updated,
        detail={"site_name": site.name if site else "", **detail},
    )


def _notif(expected=2, **over):
    return Notification.objects.create(
        run_id=uuid.uuid4(),
        operation=PRODUCT_OPERATION,
        expected=expected,
        summary=over.pop("summary", {}),
        **over,
    )


# --- open_push_notification ---------------------------------------------------


@pytest.mark.django_db
def test_open_push_notification_snapshots_products():
    m = MasterProductFactory(sku="SP-1", name="Tấm Pin")
    notif = services.open_push_notification(
        run_id=uuid.uuid4(), operation=PRODUCT_OPERATION, expected=3, user_id=None, master_ids=[m.id]
    )
    assert notif.status == Notification.Status.RUNNING
    assert notif.expected == 3
    assert notif.summary["products"] == [{"id": m.id, "name": "Tấm Pin", "sku": "SP-1"}]
    assert notif.summary["all_products"] is False


@pytest.mark.django_db
def test_open_push_notification_marks_whole_catalog():
    notif = services.open_push_notification(
        run_id=uuid.uuid4(), operation=PRODUCT_OPERATION, expected=5, user_id=None, master_ids=None
    )
    assert notif.summary["all_products"] is True
    assert notif.summary["products"] == []


@pytest.mark.django_db
def test_open_push_notification_noop_when_no_sites():
    assert (
        services.open_push_notification(
            run_id=uuid.uuid4(),
            operation=PRODUCT_OPERATION,
            expected=0,
            user_id=None,
            master_ids=None,
        )
        is None
    )
    assert Notification.objects.count() == 0


# --- finalize_notification ----------------------------------------------------


@pytest.mark.django_db
def test_finalize_stays_running_until_all_sites_reported():
    notif = _notif(expected=2)
    _plog(SiteFactory(), notif.run_id)  # only 1 of 2 sites landed
    services.finalize_notification(notif)
    assert notif.status == Notification.Status.RUNNING


@pytest.mark.django_db
def test_finalize_completes_and_rolls_up_per_site():
    notif = _notif(expected=2, summary={"products": [], "all_products": True})
    ok = SiteFactory(name="alpha.vn")
    bad = SiteFactory(name="beta.vn")
    _plog(ok, notif.run_id, created=2, updated=1)
    _plog(
        bad,
        notif.run_id,
        status=SyncLog.Status.PARTIAL,
        updated=1,
        failed=[{"sku": "SP-9", "op": "update", "code": "rest_cannot_update", "message": "boom"}],
    )

    services.finalize_notification(notif)

    assert notif.status == Notification.Status.COMPLETED
    assert notif.completed_at is not None
    s = notif.summary
    assert s["site_count"] == 2 and s["done"] == 2
    assert s["success"] == 1 and s["partial"] == 1 and s["error"] == 0
    assert s["created"] == 2 and s["updated"] == 2
    # The non-success site is surfaced with its reason.
    assert [f["site_name"] for f in s["failed_sites"]] == ["beta.vn"]
    assert s["failed_sites"][0]["failed"][0]["sku"] == "SP-9"


@pytest.mark.django_db
def test_finalize_marks_timeout_when_stuck(settings):
    settings.PUSH_NOTIFICATION_TIMEOUT_SECONDS = 60
    notif = _notif(expected=2)
    # No site ever reported, and the run is older than the timeout.
    Notification.objects.filter(id=notif.id).update(
        created_at=timezone.now() - timedelta(minutes=5)
    )
    notif.refresh_from_db()

    services.finalize_notification(notif)

    assert notif.status == Notification.Status.TIMEOUT
    assert notif.summary["done"] == 0


@pytest.mark.django_db
def test_finalize_enqueues_report_email_once(monkeypatch):
    # The report email is queued exactly once, on the RUNNING→terminal transition.
    calls = []
    monkeypatch.setattr(
        "apps.sync.tasks.send_product_sync_report_task.delay",
        lambda run_id: calls.append(run_id),
    )
    notif = _notif(expected=1, summary={"all_products": True})
    _plog(SiteFactory(), notif.run_id, created=1)

    services.finalize_notification(notif)
    assert notif.status == Notification.Status.COMPLETED
    assert calls == [str(notif.run_id)]

    # A second finalize is a no-op (already terminal) — no re-enqueue.
    services.finalize_notification(notif)
    assert calls == [str(notif.run_id)]


@pytest.mark.django_db
def test_finalize_is_idempotent():
    notif = _notif(expected=1)
    _plog(SiteFactory(), notif.run_id, created=1)
    services.finalize_notification(notif)
    assert notif.status == Notification.Status.COMPLETED
    completed_at = notif.completed_at
    # A second call must not re-finalize / move the timestamp.
    services.finalize_notification(notif)
    assert notif.completed_at == completed_at


# --- endpoints ----------------------------------------------------------------


@pytest.mark.django_db
def test_list_finalizes_running_and_reports_counts(client):
    notif = _notif(expected=1)
    _plog(SiteFactory(), notif.run_id, created=1)

    resp = client.get("/api/notifications/")

    assert resp.status_code == 200
    assert resp.data["running"] == 0  # finalized on read
    assert resp.data["unread"] == 1
    row = resp.data["results"][0]
    assert row["run_id"] == str(notif.run_id)
    assert row["status"] == "completed"
    assert row["read"] is False


@pytest.mark.django_db
def test_unread_count_endpoint(client):
    _notif(expected=2)  # running, unread
    read = _notif(expected=1)
    read.read_at = timezone.now()
    read.save(update_fields=["read_at"])

    data = client.get("/api/notifications/unread_count/").data
    assert data["unread"] == 1
    assert data["running"] == 2  # both still running (no rows)


@pytest.mark.django_db
def test_mark_read_single(client):
    notif = _notif(expected=1)
    resp = client.post(f"/api/notifications/{notif.id}/read/")
    assert resp.status_code == 200
    notif.refresh_from_db()
    assert notif.read_at is not None
    assert resp.data["read"] is True


@pytest.mark.django_db
def test_mark_all_read(client):
    _notif(expected=1)
    _notif(expected=2)
    resp = client.post("/api/notifications/mark_all_read/")
    assert resp.status_code == 200
    assert resp.data["unread"] == 0
    assert Notification.objects.filter(read_at__isnull=True).count() == 0


@pytest.mark.django_db
def test_read_unknown_404(client):
    assert client.post("/api/notifications/999999/read/").status_code == 404
