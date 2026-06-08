from django.db import models


class MasterProduct(models.Model):
    """The Hub's source-of-truth product (catalog gốc).

    CRUD happens here (Admin/API); a "Sync all" then pushes every master to each
    WooCommerce site via ``apps/catalog/services.push_products_to_site``. ``sku``
    is the cross-site matching key (UNIQUE, user-controlled, normalized to upper
    in the service/serializer before save) — ``woo_product_id`` is per-site and
    lives on ``ProductMapping``, never assumed equal across sites.

    Soft-delete (``is_deleted``) so a removed product can still be pushed as a
    WooCommerce ``delete`` on the next sync (the mapping carries its per-site id).
    Categories are stored by **name** in v1 (Woo matches/creates them on push);
    per-site category/attribute id mapping is a later phase.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISH = "publish", "Publish"
        PENDING = "pending", "Pending"
        PRIVATE = "private", "Private"

    class StockStatus(models.TextChoices):
        INSTOCK = "instock", "In stock"
        OUTOFSTOCK = "outofstock", "Out of stock"
        ONBACKORDER = "onbackorder", "On backorder"

    sku = models.CharField(max_length=120, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=20, default="simple")  # Woo product type
    description = models.TextField(blank=True)
    short_description = models.TextField(blank=True)
    regular_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sale_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    stock_status = models.CharField(
        max_length=20, choices=StockStatus.choices, default=StockStatus.INSTOCK
    )
    weight = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    # List of image URLs: ["https://...", ...] (pushed as [{"src": url}]).
    images = models.JSONField(default=list)
    # List of category names: ["Pin mặt trời", ...] (pushed as [{"name": n}]).
    categories = models.JSONField(default=list)

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.sku} — {self.name}"


class ProductMapping(models.Model):
    """Maps one ``MasterProduct`` to its ``woo_product_id`` on one ``Site``.

    The invariant from docs/backend/ARCHITECTURE.md: ``woo_product_id`` (and Woo
    category/attribute ids) are RIÊNG per site — the Hub never assumes they match
    across sites, so every site reference goes through this row. UNIQUE
    ``(master, site)`` keeps the push idempotent (re-run updates, never
    duplicates); UNIQUE ``(site, woo_product_id)`` guards against two masters
    claiming the same remote product.
    """

    master = models.ForeignKey(
        MasterProduct,
        on_delete=models.CASCADE,
        related_name="mappings",
    )
    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="product_mappings",
        db_index=True,
    )
    woo_product_id = models.BigIntegerField()
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["master", "site"], name="mapping_unique_master_site"),
            models.UniqueConstraint(
                fields=["site", "woo_product_id"], name="mapping_unique_site_woo"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.master_id}@{self.site_id} → {self.woo_product_id}"
