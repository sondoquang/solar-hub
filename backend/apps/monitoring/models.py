from django.conf import settings
from django.db import models


class HealthCheck(models.Model):
    """A single health-check observation for a site (website).

    One row is appended every time a site's connection is tested — either
    manually from the UI (``MANUAL``, attributed to the acting user) or by the
    periodic Celery task (``PERIODIC``, ``performed_by=None`` → "Hệ thống").

    This is append-only audit history (like ``sync_logs``): there is no delete
    endpoint, so the soft-delete rule for editable business entities does not
    apply. ``status`` is derived from reachability + response time in
    ``apps/monitoring/services.derive_status``.
    """

    class Status(models.TextChoices):
        HEALTHY = "healthy", "Khỏe mạnh"
        WARNING = "warning", "Cảnh báo"
        CRITICAL = "critical", "Lỗi nghiêm trọng"

    class CheckType(models.TextChoices):
        PERIODIC = "periodic", "Kiểm tra định kỳ"
        MANUAL = "manual", "Kiểm tra thủ công"

    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="health_checks",
        db_index=True,
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, db_index=True
    )
    check_type = models.CharField(
        max_length=20, choices=CheckType.choices, default=CheckType.MANUAL
    )
    # Round-trip time of the system_status call; null only if timing failed.
    response_time_ms = models.PositiveIntegerField(null=True, blank=True)
    ok = models.BooleanField(default=False)  # raw reachability of the call
    detail = models.CharField(max_length=255, blank=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="health_checks",
    )
    checked_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-checked_at"]
        indexes = [
            models.Index(fields=["status", "checked_at"]),
            models.Index(fields=["site", "checked_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.site_id} {self.status} @ {self.checked_at:%Y-%m-%d %H:%M}"
