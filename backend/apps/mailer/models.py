"""Mail (SMTP) configuration — a single, system-wide settings row.

The Hub sends an order digest twice a day (see ``apps.mailer.tasks``) and lets an
admin send selected orders to an arbitrary address on demand. Both use the SMTP
account configured here (e.g. a Gmail address + *app password*).

The app password is a secret: it is stored encrypted in ``password_enc`` (Fernet,
same key as the WooCommerce ``consumer_secret``) and never returned by the API or
written to a log. Only decrypted in memory when building an SMTP connection.
"""

from django.db import models

from apps.sites.crypto import decrypt_secret, encrypt_secret


def default_digest_times() -> list[str]:
    """Default daily send times for the auto digest (local time, ``"HH:MM"``)."""
    return ["09:00", "16:00"]


class MailSettings(models.Model):
    """System-wide SMTP settings (singleton, ``pk=1``).

    Use :meth:`load` to read/create the row; ``save`` pins the pk so there is
    never more than one. The plaintext app password is set via
    :meth:`set_password` and read back only via :meth:`get_password`.
    """

    SINGLETON_ID = 1

    smtp_host = models.CharField(max_length=255, default="smtp.gmail.com")
    smtp_port = models.PositiveIntegerField(default=587)
    use_tls = models.BooleanField(default=True)
    use_ssl = models.BooleanField(default=False)

    # SMTP login (usually the sender Gmail address) + the encrypted app password.
    username = models.CharField(max_length=255, blank=True)
    password_enc = models.BinaryField(null=True, blank=True)

    # "From" header. ``from_email`` falls back to ``username`` when blank.
    from_email = models.CharField(max_length=255, blank=True)
    from_name = models.CharField(max_length=255, blank=True, default="Solar Hub")

    # Recipients of the twice-daily digest (list of email strings).
    recipients = models.JSONField(default=list, blank=True)

    # Recipients of the product-sync report email (sent once a push run finishes,
    # see apps.sync.tasks.send_product_sync_report_task). A separate list from the
    # order digest so the two audiences can differ; when left empty the report
    # falls back to ``recipients`` (see apps.mailer.services.product_sync_recipients).
    product_sync_recipients = models.JSONField(default=list, blank=True)
    # Master switch for the product-sync report email (the push itself is
    # unaffected — only whether a report is emailed on completion).
    product_sync_report_enabled = models.BooleanField(default=True)

    # Master switch for the scheduled digest (manual send is unaffected).
    digest_enabled = models.BooleanField(default=True)
    # Daily local-time slots the digest fires at, as ``"HH:MM"`` strings (e.g.
    # ["09:00", "16:00"]). A minute-level Celery Beat tick
    # (apps.mailer.tasks.dispatch_due_digests) reads these and sends when a slot
    # is due — so the schedule is editable from the UI without a redeploy.
    digest_times = models.JSONField(default=default_digest_times, blank=True)
    # Watermark: only orders synced after this are included in the next digest.
    last_digest_sent_at = models.DateTimeField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cấu hình Mail SMTP"
        verbose_name_plural = "Cấu hình Mail SMTP"
        permissions = [
            ("test_mailsettings", "Có thể gửi email thử"),
        ]

    def __str__(self) -> str:
        return f"MailSettings({self.username or 'chưa cấu hình'})"

    def save(self, *args, **kwargs):
        # Pin the primary key so the table holds at most one row.
        self.pk = self.SINGLETON_ID
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "MailSettings":
        obj, _ = cls.objects.get_or_create(pk=cls.SINGLETON_ID)
        return obj

    # --- Secret handling -------------------------------------------------
    def set_password(self, plaintext: str) -> None:
        """Encrypt and store the app password (empty string clears it)."""
        self.password_enc = encrypt_secret(plaintext) if plaintext else None

    def get_password(self) -> str:
        """Decrypt the stored app password (``""`` when none is set)."""
        if not self.password_enc:
            return ""
        return decrypt_secret(self.password_enc)

    @property
    def has_password(self) -> bool:
        return bool(self.password_enc)

    @property
    def effective_from_email(self) -> str:
        return self.from_email or self.username

    @property
    def is_configured(self) -> bool:
        """Enough to actually send: host, login, password and a sender."""
        return bool(
            self.smtp_host
            and self.username
            and self.has_password
            and self.effective_from_email
        )
