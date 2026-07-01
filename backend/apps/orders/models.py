from django.db import models

# Risk classification of a synced order — does it look like a real customer
# order, or a bot / spam / "vào phá chọn đại" one? Computed by
# ``apps.orders.services.classify_order`` on every upsert.
GENUINE = "genuine"
SUSPICIOUS = "suspicious"
SPAM = "spam"
CLASSIFICATION_CHOICES = [
    (GENUINE, "Hợp lệ"),
    (SUSPICIOUS, "Nghi ngờ"),
    (SPAM, "Spam/Bot"),
]


class Order(models.Model):
    """A WooCommerce order normalized into the Hub (single source of truth).

    Orders flow in from two idempotent paths that may overlap: the periodic
    poll (``apps/sync/tasks.poll_all_orders``, implemented now) and, later, a
    real-time webhook. The ``UNIQUE(site, woo_order_id)`` constraint makes the
    upsert in ``apps/orders/services.upsert_order`` safe against duplication.

    ``date_created_woo`` is the order's creation time *on the site*. The poll's
    watermark is ``MAX(date_modified_woo)`` per ``(site, status)`` (sent as
    ``modified_after=``) so a status change on an older order is caught too.

    PII (customer name/phone/email/address) is stored here because the Hub
    aggregates orders, but it MUST NOT be logged in production (see CLAUDE.md).
    """

    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="orders",
        db_index=True,
    )
    # WooCommerce order id — unique per site, never assumed equal across sites.
    woo_order_id = models.BigIntegerField()
    number = models.CharField(max_length=40, blank=True)  # display order number
    status = models.CharField(max_length=30, db_index=True)  # processing/completed/…
    # Payment status. Sapo's ``financial_status`` (pending/authorized/
    # partially_paid/paid/…); the Sapo order flow drives off this instead of the
    # lifecycle ``status``. Blank for WooCommerce orders (Woo has no separate
    # payment-status field on the order resource).
    payment_status = models.CharField(max_length=30, blank=True, db_index=True)
    currency = models.CharField(max_length=10, blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Customer info (PII — stored, never logged).
    customer_name = models.CharField(max_length=255, blank=True)
    customer_phone = models.CharField(max_length=40, blank=True)
    customer_email = models.CharField(max_length=255, blank=True)
    shipping_address = models.TextField(blank=True)
    customer_note = models.TextField(blank=True)

    # Trimmed line items: [{sku, name, quantity, total}, ...].
    line_items = models.JSONField(default=list)

    date_created_woo = models.DateTimeField(db_index=True)
    # Order's last-modified time on the site. Drives the per-(site, status)
    # poll watermark (``modified_after=``) so status transitions on older
    # orders are caught, not just newly created ones. Nullable for rows that
    # predate this field; populated on the next upsert.
    date_modified_woo = models.DateTimeField(null=True, blank=True, db_index=True)
    forwarded = models.BooleanField(default=False, db_index=True)  # sent to marketing?
    forwarded_at = models.DateTimeField(null=True, blank=True)

    # Risk classification (genuine / suspicious / spam). Recomputed on each
    # upsert; a suspicious/spam order is held back from auto-forward (see
    # ``services._auto_forward_if_completed``). ``risk_reasons`` is the list of
    # rule codes that fired (e.g. ["phone_invalid", "velocity_phone"]).
    classification = models.CharField(
        max_length=20, choices=CLASSIFICATION_CHOICES, default=GENUINE, db_index=True
    )
    risk_score = models.IntegerField(default=0)  # 0–100, higher = riskier
    risk_reasons = models.JSONField(default=list)
    classified_at = models.DateTimeField(null=True, blank=True)

    # Original payload, kept for debugging / reconciliation.
    raw = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_created_woo"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "woo_order_id"], name="order_unique_per_site"
            ),
        ]
        indexes = [
            models.Index(fields=["site", "date_created_woo"]),
            models.Index(fields=["status", "date_created_woo"]),
            models.Index(fields=["forwarded", "date_created_woo"]),
            # Per-(site, status) poll watermark: MAX(date_modified_woo).
            models.Index(fields=["site", "status", "date_modified_woo"]),
            # List-screen filter by classification.
            models.Index(fields=["classification", "date_created_woo"]),
            # Velocity lookups: orders sharing a phone / email in a time window.
            models.Index(fields=["customer_phone", "date_created_woo"]),
            models.Index(fields=["customer_email", "date_created_woo"]),
        ]

    def __str__(self) -> str:
        return f"#{self.number or self.woo_order_id} ({self.site_id})"
