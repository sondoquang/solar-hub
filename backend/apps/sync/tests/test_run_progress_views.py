"""Live run-progress API: /api/sync/run-progress/{run_id}/?operation=.

Powers the "Đang đồng bộ… X/Y site hoàn tất" banner on the Đơn hàng / Sản phẩm
pages. Generic over operation; counts the per-site SyncLog rows of one run.
"""

import uuid

import pytest

from apps.sites.tests.factories import SiteFactory
from apps.sync.models import SyncLog


def _log(site, run_id, operation, status=SyncLog.Status.SUCCESS):
    return SyncLog.objects.create(
        site=site, operation=operation, status=status, run_id=run_id, detail={}
    )


@pytest.mark.django_db
def test_progress_counts_rows_of_the_run(client):
    s1, s2, s3 = SiteFactory(), SiteFactory(), SiteFactory()
    run_id = uuid.uuid4()
    _log(s1, run_id, "poll_orders")
    _log(s2, run_id, "poll_orders", status=SyncLog.Status.ERROR)
    # A different run + a different operation must not leak into the count.
    _log(s3, uuid.uuid4(), "poll_orders")
    _log(s3, run_id, "push_products")

    resp = client.get(f"/api/sync/run-progress/{run_id}/?operation=poll_orders")
    assert resp.status_code == 200
    assert resp.data["done"] == 2
    assert resp.data["error_count"] == 1
    assert resp.data["run_id"] == str(run_id)


@pytest.mark.django_db
def test_progress_zero_before_first_site(client):
    """Unknown/just-triggered run returns done=0 (never 404) so the banner can
    poll a fresh run and wait for done to climb."""
    resp = client.get(f"/api/sync/run-progress/{uuid.uuid4()}/?operation=push_products")
    assert resp.status_code == 200
    assert resp.data["done"] == 0
    assert resp.data["error_count"] == 0


@pytest.mark.django_db
def test_progress_rejects_unknown_operation(client):
    resp = client.get(f"/api/sync/run-progress/{uuid.uuid4()}/?operation=bogus")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_progress_rejects_non_uuid(client):
    """The router's UUID lookup regex 404s arbitrary strings before the view."""
    resp = client.get("/api/sync/run-progress/not-a-uuid/?operation=poll_orders")
    assert resp.status_code == 404
