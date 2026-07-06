from django.db import models


class DomainInfo(models.Model):
    """Current domain-level snapshot for one site: WHOIS, DNS records, SSL/TLS
    certificate, DNSBL blacklist status and Google index status.

    One MUTABLE row per site — unlike ``monitoring.HealthCheck`` this is not
    audit history: WHOIS/SSL facts change on the order of months, so only the
    latest state matters (raw payloads are kept in the JSON fields for
    diagnosis). Each check group carries its own ``*_status`` + ``*_checked_at``
    so one failing lookup (e.g. WHOIS on ``.vn`` — VNNIC has no public RDAP)
    degrades that section only, never the whole row. Rows are created/refreshed
    by ``apps/domains/services.refresh_domain_info`` (Celery only — the lookups
    are slow network I/O).
    """

    class CheckStatus(models.TextChoices):
        PENDING = "pending", "Đang kiểm tra"
        OK = "ok", "Thành công"
        PARTIAL = "partial", "Thiếu một phần"
        ERROR = "error", "Lỗi"
        UNSUPPORTED = "unsupported", "Chưa hỗ trợ"
        SKIPPED = "skipped", "Bỏ qua"

    class BlacklistVerdict(models.TextChoices):
        CLEAN = "clean", "Sạch"
        LISTED = "listed", "Bị liệt kê"
        UNKNOWN = "unknown", "Không xác định"

    site = models.OneToOneField(
        "sites.Site", on_delete=models.CASCADE, related_name="domain_info"
    )
    # host = full hostname from base_url (SSL / A-record target); domain = the
    # registrable domain (WHOIS / NS / MX / blacklist target). E.g. base_url
    # "https://shop.example.com.vn" → host "shop.example.com.vn",
    # domain "example.com.vn".
    host = models.CharField(max_length=255)
    domain = models.CharField(max_length=255, db_index=True)

    # 1. WHOIS (RDAP first, port-43 whois fallback)
    whois_status = models.CharField(
        max_length=20, choices=CheckStatus.choices, default=CheckStatus.PENDING
    )
    whois_registrar = models.CharField(max_length=255, blank=True)
    whois_created_at = models.DateTimeField(null=True, blank=True)
    whois_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    whois_source = models.CharField(max_length=20, blank=True)  # "rdap" | "whois43"
    whois_raw = models.JSONField(default=dict, blank=True)
    whois_checked_at = models.DateTimeField(null=True, blank=True)

    # 2. DNS records: {"A": [...], "MX": ["10 mail.example.com"], ...}
    dns_status = models.CharField(
        max_length=20, choices=CheckStatus.choices, default=CheckStatus.PENDING
    )
    dns_records = models.JSONField(default=dict, blank=True)
    dns_checked_at = models.DateTimeField(null=True, blank=True)

    # 3. SSL/TLS leaf certificate of host:443
    ssl_status = models.CharField(
        max_length=20, choices=CheckStatus.choices, default=CheckStatus.PENDING
    )
    ssl_issuer = models.CharField(max_length=255, blank=True)
    ssl_subject = models.CharField(max_length=255, blank=True)
    ssl_not_before = models.DateTimeField(null=True, blank=True)
    ssl_not_after = models.DateTimeField(null=True, blank=True, db_index=True)
    ssl_checked_at = models.DateTimeField(null=True, blank=True)

    # 4. DNSBL blacklists. ``verdict`` rolls up the per-list results in
    # ``blacklist_results``; UNKNOWN also covers Spamhaus refusing public
    # resolvers — that must never read as LISTED.
    blacklist_status = models.CharField(
        max_length=20, choices=CheckStatus.choices, default=CheckStatus.PENDING
    )
    blacklist_verdict = models.CharField(
        max_length=10, choices=BlacklistVerdict.choices, default=BlacklistVerdict.UNKNOWN
    )
    blacklist_results = models.JSONField(default=list, blank=True)
    blacklist_checked_at = models.DateTimeField(null=True, blank=True)

    # 5. Google index (Custom Search API; SKIPPED until GOOGLE_CSE_API_KEY set)
    gindex_status = models.CharField(
        max_length=20, choices=CheckStatus.choices, default=CheckStatus.SKIPPED
    )
    gindex_indexed = models.BooleanField(null=True, blank=True)
    gindex_total_results = models.BigIntegerField(null=True, blank=True)
    gindex_checked_at = models.DateTimeField(null=True, blank=True)

    last_refreshed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_error = models.CharField(max_length=255, blank=True)  # exception class names only
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["domain", "id"]
        permissions = [
            ("refresh_domaininfo", "Có thể kiểm tra lại thông tin tên miền"),
        ]

    def __str__(self) -> str:
        return f"{self.domain} (site {self.site_id})"

    @property
    def is_pending(self) -> bool:
        """True while any check is queued/running — the FE polls on this."""
        return self.CheckStatus.PENDING in (
            self.whois_status,
            self.dns_status,
            self.ssl_status,
            self.blacklist_status,
            self.gindex_status,
        )
