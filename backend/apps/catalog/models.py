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

    class Type(models.TextChoices):
        SIMPLE = "simple", "Simple"
        GROUPED = "grouped", "Grouped"
        EXTERNAL = "external", "External/Affiliate"
        VARIABLE = "variable", "Variable"

    sku = models.CharField(max_length=120, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    # The product's name as it was when imported from a site, frozen at import
    # time and never touched by edits to ``name``. It is the cross-site *name*
    # matching key: on the first push to a site with no mapping yet, the push
    # looks the site up by this name and "adopts" the existing product (creates
    # the mapping + updates it) instead of creating a duplicate. After that one
    # adoption the stable ProductMapping takes over — name matching never runs
    # again for that (master, site). Blank for hand-created masters (the push
    # falls back to ``name``). See services.normalize_match_name / _adopt_by_name.
    match_name = models.CharField(max_length=255, blank=True, default="", db_index=True)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.SIMPLE)
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
    # List of category names: ["Pin mặt trời", ...]. Pushed as [{"id": n}] via the
    # site's CategoryMapping — Woo ignores name-only refs, so the push creates any
    # unmapped category on the site first (services._ensure_site_categories).
    categories = models.JSONField(default=list)

    # --- Type-specific data (all defaulted → simple products are unaffected) -----
    # external: the affiliate link + buy-button label Woo shows instead of add-to-cart.
    external_url = models.URLField(blank=True, default="")
    button_text = models.CharField(max_length=120, blank=True, default="")
    # grouped: child products referenced by SKU (cross-site safe — resolved to each
    # site's woo_product_id at push time, never assumed equal across sites).
    grouped_skus = models.JSONField(default=list)  # ["SP-1", "SP-2"]
    # variable: attribute definitions and the per-combination variations.
    #   attributes: [{"name", "options": [...], "variation": bool, "visible": bool}]
    #   variations: [{"sku", "regular_price", "sale_price", "stock_status",
    #                 "weight", "attributes": {name: option}, "image"}]
    # Variations are pushed via a separate endpoint (/products/{id}/variations/batch)
    # and their per-site woo ids live on ProductVariationMapping.
    attributes = models.JSONField(default=list)
    variations = models.JSONField(default=list)

    # Where this master was imported from (audit only; SET_NULL so deleting the
    # site keeps the master). Null for hand-created products.
    source_site = models.ForeignKey(
        "sites.Site",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="imported_products",
    )
    imported_at = models.DateTimeField(null=True, blank=True)

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.sku} — {self.name}"


class ProductImage(models.Model):
    """Hub-side media library for product images (kiểu WP Media Library).

    Files are uploaded once to the Hub (MEDIA_ROOT) and referenced by URL from
    ``MasterProduct.images`` / the description HTML — the push to WooCommerce
    stays URL-based (``[{"src": url}]``), each site downloads the file itself.
    Rows are intentionally not tied to a product: like WordPress, the library
    is shared so an image can be reused across products.
    """

    image = models.ImageField(upload_to="products/%Y/%m/")
    original_name = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return self.original_name or f"Image #{self.pk}"


class SiteMediaAsset(models.Model):
    """Cache: one Hub media file that has been sideloaded onto one ``Site``.

    Used by the description-image sideload (services._sideload_description_images,
    WooCommerce only). When a product's description HTML embeds a Hub image
    (``/media/...``), the push makes Woo download it into the site's own media
    library and rewrites the description ``src`` to the returned site URL. This
    row remembers that upload so the SAME image is never re-uploaded to the SAME
    site on later pushes (Woo's REST sideload does not dedup by source URL — it
    would create a duplicate attachment every push otherwise).

    Keyed by ``source_path`` (the host-INDEPENDENT ``/media/...`` part, not the
    full URL) so the cache survives a change of the Hub's public host (new
    cloudflared tunnel / real deploy — see the set_media_public_url command).
    UNIQUE ``(site, source_path)`` keeps the sideload idempotent.
    """

    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="media_assets",
        db_index=True,
    )
    # Host-independent Hub media path, e.g. "/media/products/2026/06/x.png".
    source_path = models.CharField(max_length=500)
    # The URL the file resolved to on the SITE after Woo sideloaded it.
    site_url = models.URLField(max_length=500)
    # The site's attachment id (kept for audit / future cleanup; nullable because
    # some Woo responses omit it).
    woo_media_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["site", "source_path"], name="mediaasset_unique_site_path"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source_path}@{self.site_id} → {self.site_url}"


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


class Category(models.Model):
    """Hub-side catalog of category names, populated by a pull from each site.

    The product still references categories by **name** (``MasterProduct.categories``);
    this table is the picker source ("tick from existing") and the per-site
    ``woo_category_id`` lives on ``CategoryMapping``. ``name`` is normalized
    (trim + collapse whitespace, case preserved for display) and UNIQUE, so the
    same category coming from several sites converges to one row with several
    mappings.

    **Cây danh mục (tree):** ``parent`` là self-FK dựng lại đúng cây như
    WooCommerce (1 cây toàn cục cho cả Hub). Vì ``Category`` dedup theo *tên*
    còn cây cha–con có thể khác nhau giữa các site, quan hệ cha là **last-pull-
    wins**: mỗi lần pull một site ghi đè ``parent`` theo cây của site đó. Gốc =
    ``parent`` null. ``on_delete=SET_NULL`` để xóa cha không kéo con biến mất.
    """

    name = models.CharField(max_length=255, unique=True, db_index=True)
    slug = models.CharField(max_length=255, blank=True, default="")
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    is_deleted = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name


class CategoryMapping(models.Model):
    """Maps one ``Category`` to its ``woo_category_id`` on one ``Site``.

    Mirrors ``ProductMapping``: per-site ids are RIÊNG, so resolving a category
    name to the right remote id on push goes through this row. UNIQUE
    ``(category, site)`` keeps the pull idempotent; UNIQUE ``(site,
    woo_category_id)`` guards against two categories claiming the same remote id.
    """

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="mappings",
    )
    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="category_mappings",
        db_index=True,
    )
    woo_category_id = models.BigIntegerField()
    # Tên RAW trên site (chưa normalize) — để màn hình mapping đối chiếu được
    # "tên trên site" vs "tên Hub". Refresh mỗi lần pull (mapping rebuild wholesale).
    woo_name = models.CharField(max_length=255, blank=True, default="")
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["category", "site"], name="catmap_unique_category_site"
            ),
            models.UniqueConstraint(
                fields=["site", "woo_category_id"], name="catmap_unique_site_woo"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.category_id}@{self.site_id} → {self.woo_category_id}"


class ProductVariationMapping(models.Model):
    """Maps one variation (by ``variation_sku``) of a variable ``MasterProduct``
    to its ``woo_variation_id`` on one ``Site``.

    Variations are child products in WooCommerce with their own ids, pushed via
    ``/products/{parent}/variations/batch`` after the parent. ``woo_parent_id`` is
    kept for convenience (that endpoint needs the parent id). UNIQUE
    ``(master, site, variation_sku)`` keeps the variation push idempotent; UNIQUE
    ``(site, woo_variation_id)`` guards against duplicates.
    """

    master = models.ForeignKey(
        MasterProduct,
        on_delete=models.CASCADE,
        related_name="variation_mappings",
    )
    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="variation_mappings",
        db_index=True,
    )
    variation_sku = models.CharField(max_length=120, db_index=True)
    woo_variation_id = models.BigIntegerField()
    woo_parent_id = models.BigIntegerField()
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["master", "site", "variation_sku"],
                name="varmap_unique_master_site_sku",
            ),
            models.UniqueConstraint(
                fields=["site", "woo_variation_id"], name="varmap_unique_site_woo"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.master_id}/{self.variation_sku}@{self.site_id}"


class ProductAdoptionScan(models.Model):
    """Records that a ``(master, site)`` pair has been name-scanned for adoption.

    On push, ``services._adopt_by_name`` lists a site's products to "adopt" a
    master that already exists there under a (possibly hand-typed) name — but
    that list is the WHOLE remote catalog, so re-running it every push (whenever
    ANY master is still unmapped) is a heavy, repeated read. A scan row is
    written for every master considered in a scan (adopted, ambiguous, OR no
    match), so the next push only lists the site again when a master has NEVER
    been scanned there. A successful adoption also creates a ``ProductMapping``;
    ambiguous / no-match masters have none, which is exactly why this separate
    marker is needed. ``ambiguous`` remembers a master that matched >1 site
    product by name so later pushes keep EXCLUDING it from create (never
    duplicate) without re-listing the site. Cleared by
    ``clear_product_sync_data --products`` so a re-import re-scans from scratch.
    """

    master = models.ForeignKey(
        MasterProduct,
        on_delete=models.CASCADE,
        related_name="adoption_scans",
    )
    site = models.ForeignKey(
        "sites.Site",
        on_delete=models.CASCADE,
        related_name="adoption_scans",
        db_index=True,
    )
    # True when the scan found >1 site product with the master's name: it was
    # neither adopted nor created, and must stay excluded from create on later
    # pushes until a human resolves it (then clears scan data to re-scan).
    ambiguous = models.BooleanField(default=False)
    scanned_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["master", "site"], name="adoptscan_unique_master_site"),
        ]

    def __str__(self) -> str:
        return f"scan {self.master_id}@{self.site_id}"
