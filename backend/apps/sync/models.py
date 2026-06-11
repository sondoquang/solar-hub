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
    error = models.TextField(blank=True)  # exception class name only (no PII)
    detail = models.JSONField(default=dict)  # short summary (skus, message)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["operation", "created_at"])]

    def __str__(self) -> str:
        return f"{self.operation} site={self.site_id} {self.status}"
