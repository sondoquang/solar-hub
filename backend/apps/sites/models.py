from django.conf import settings
from django.db import models


class Hosting(models.Model):
    """A hosting account / server that groups multiple WooCommerce sites (domains).

    Sites under the same hosting share server resources, so health-checks are
    throttled per hosting (``check_concurrency`` domains at a time) to avoid
    hammering a weak shared host. See apps/sites/services.check_hosting."""

    name = models.CharField(max_length=120)
    provider = models.CharField(max_length=120, blank=True)  # e.g. "TenTen"
    account_username = models.CharField(max_length=120, blank=True)  # login account
    note = models.TextField(blank=True)
    check_concurrency = models.PositiveSmallIntegerField(
        default=5
    )  # max domains health-checked at once
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name


class Site(models.Model):
    """A registered WooCommerce site. ``consumer_secret`` is stored Fernet-encrypted
    (see apps/sites/crypto.py); business logic lives in apps/sites/services.py."""

    class Status(models.TextChoices):
        UP = "up", "Up"
        DOWN = "down", "Down"
        UNKNOWN = "unknown", "Unknown"

    class SiteType(models.TextChoices):
        WEBSITE = "website", "Website"
        API = "api", "API"
        MAIL = "mail", "Mail Server"
        DATABASE = "database", "Database"

    name = models.CharField(max_length=120)
    base_url = models.URLField()
    consumer_key = models.CharField(max_length=120)
    consumer_secret_enc = models.BinaryField()
    site_type = models.CharField(
        max_length=20,
        choices=SiteType.choices,
        default=SiteType.WEBSITE,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UNKNOWN,
        db_index=True,
    )
    last_checked_at = models.DateTimeField(null=True, blank=True)
    hosting = models.ForeignKey(
        "Hosting",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sites",
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return self.name


class SiteNote(models.Model):
    """An append-only-style note in a site's note history. Each save is a new
    row (newest first) so the UI shows a running journal; old notes can be
    edited or soft-deleted. ``content`` is sanitized rich-text HTML (see
    apps/sites/services.sanitize_note_html) and ``created_by`` records who wrote
    it (mirrors monitoring.HealthCheck.performed_by)."""

    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        related_name="notes",
        db_index=True,
    )
    content = models.TextField(blank=True)  # sanitized rich-text HTML
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]  # newest note first
        indexes = [models.Index(fields=["site", "created_at"])]

    def __str__(self) -> str:
        return f"Note #{self.pk} on {self.site_id}"


def site_note_upload_to(instance, filename: str) -> str:
    """MEDIA_ROOT-relative path for a note attachment, namespaced per note."""
    return f"site_notes/{instance.note_id}/{filename}"


class SiteNoteImage(models.Model):
    """An image attached to a SiteNote. Attachments only — never inlined into
    the note's HTML body (the editor has no image button)."""

    note = models.ForeignKey(
        SiteNote,
        on_delete=models.CASCADE,
        related_name="images",
    )
    image = models.ImageField(upload_to=site_note_upload_to)
    original_name = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.original_name or f"Image #{self.pk}"
