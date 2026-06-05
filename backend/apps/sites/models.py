from django.db import models


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name
