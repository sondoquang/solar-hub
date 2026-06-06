from django.db import models


class Order(models.Model):
    """A WooCommerce order normalized into the Hub (single source of truth).

    Orders flow in from two idempotent paths that may overlap: the periodic
    poll (``apps/sync/tasks.poll_all_orders``, implemented now) and, later, a
    real-time webhook. The ``UNIQUE(site, woo_order_id)`` constraint makes the
    upsert in ``apps/orders/services.upsert_order`` safe against duplication.

    ``date_created_woo`` is the order's creation time *on the site*; the poll
    uses ``MAX(date_created_woo)`` per site as its watermark (``after=``).

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
    forwarded = models.BooleanField(default=False, db_index=True)  # sent to marketing?
    forwarded_at = models.DateTimeField(null=True, blank=True)

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
        ]

    def __str__(self) -> str:
        return f"#{self.number or self.woo_order_id} ({self.site_id})"
