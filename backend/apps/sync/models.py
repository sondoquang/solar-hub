from django.conf import settings
from django.db import models


class SyncLog(models.Model):
    """Audit trail of every sync operation (push_products), one row per site run.

    Recorded so a sync can be traced after the fact (PROJECT_RULE §logging):
    which site, what operation, the outcome, and the create/update/delete counts.
    ``error`` holds the exception class name only — never the WooCommerce payload
    or any PII/secret. ``site`` is SET_NULL on delete so logs outlive the site.

    ``run_id`` groups the per-site rows of one fan-out (one user click of
    "sync categories" = one run across all sites). Nullable because rows
    written before the field existed — and operations that don't fan out —
    have no run; the category-run report simply excludes those.

    ``triggered_by`` is the admin who clicked "sync" (null for periodic/beat or
    shell runs); ``started_at`` is when this site's operation began, so the
    per-site (and per-run) duration is ``created_at - started_at``. Both feed the
    "Người chạy"/"Thời gian" columns of the category-run report; SET_NULL so a
    deleted user does not erase the log.
    """

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        PARTIAL = "partial", "Partial"
        ERROR = "error", "Error"

    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sync_logs",
        db_index=True,
    )
    operation = models.CharField(max_length=40, db_index=True)  # e.g. "push_products"
    status = models.CharField(max_length=20, choices=Status.choices, db_index=True)
    created_count = models.IntegerField(default=0)
    updated_count = models.IntegerField(default=0)
    deleted_count = models.IntegerField(default=0)
    run_id = models.UUIDField(null=True, blank=True, db_index=True, editable=False)
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sync_logs",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)  # exception class name only (no PII)
    detail = models.JSONField(default=dict)  # short summary (skus, message)
    # Soft-delete for the "clear category sync data" reset: a global clear marks
    # every pull_categories row deleted so the category-run report starts fresh,
    # without losing the rows (audit trail stays recoverable). The report queries
    # filter is_deleted=False; the operation index already covers the hot path.
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["operation", "created_at"])]

    def __str__(self) -> str:
        return f"{self.operation} site={self.site_id} {self.status}"


class Notification(models.Model):
    """A push-run notification: opened when a product push is triggered, finalized
    when every targeted site has reported (or the run times out).

    Backs the app-wide "đã push xong" modal + the notification bell. The heavy
    per-site outcome lives on ``SyncLog`` (grouped by ``run_id``); this row is the
    lightweight, PERSISTENT handle the UI polls — so the completion modal fires
    even if the user closed it and switched tabs, and past pushes stay reviewable.
    ``summary`` is a compact roll-up filled on finalize (per-site success/partial/
    error + which products); the full per-site detail is the product-run report
    (``/api/sync/product-runs/{run_id}/``, same ``run_id``).

    Finalize is LAZY (computed from ``SyncLog`` on read — see
    ``apps.sync.services.finalize_notification``) so no Celery result backend /
    chord is required; a beat sweep finalizes runs nobody polls. ``read_at`` is
    global (an internal admin tool) — the first reader clears the unread badge.
    """

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        TIMEOUT = "timeout", "Timeout"

    run_id = models.UUIDField(unique=True, db_index=True, editable=False)
    operation = models.CharField(max_length=40, default="push_products")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.RUNNING, db_index=True
    )
    expected = models.IntegerField(default=0)  # number of sites the run targets
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="push_notifications",
    )
    # Compact roll-up: trigger-time it holds the target products; finalize adds the
    # per-site success/partial/error split + totals. See services._summarize_push_detail.
    summary = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)  # null = unread
    # When the finalized run's report email was sent (null = not yet). Set with an
    # atomic filtered UPDATE in ``apps.sync.tasks.send_product_sync_report_task`` so
    # the report is emailed exactly once even if two callers finalize concurrently.
    report_emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self) -> str:
        return f"notif {self.operation} {self.run_id} {self.status}"
