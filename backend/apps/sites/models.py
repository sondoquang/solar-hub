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

    name = models.CharField(max_length=120)
    base_url = models.URLField()
    consumer_key = models.CharField(max_length=120)
    consumer_secret_enc = models.BinaryField()
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
