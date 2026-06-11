import io
import pathlib

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework import serializers

from .models import Category, MasterProduct, ProductImage, ProductMapping
from .services import normalize_sku

# Upload limits for the product media library (mirrors site-note attachments).
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB per file


def _webp_to_png(upload) -> SimpleUploadedFile:
    """Re-encode a webp upload as PNG (keeps alpha).

    WordPress sideloads product images from the URL the Hub pushes, and many
    (shared-host / older) sites reject webp with ``woocommerce_product_image_
    upload_error`` ("không được phép tải lên định dạng tệp tin này") — which
    kills the WHOLE product item in the batch. PNG/JPEG/GIF are universally
    accepted, so webp is accepted from the user but stored as PNG.
    """
    image = Image.open(upload)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    name = pathlib.PurePosixPath(upload.name or "image.webp").stem + ".png"
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


class ProductImageSerializer(serializers.ModelSerializer):
    """One media-library image. Write: multipart ``image`` file. Read: ``url``
    is absolute (the frontend runs on another origin in dev, and WooCommerce
    sites must be able to download it when the product is pushed).

    ``MEDIA_PUBLIC_BASE_URL`` (settings/.env) wins over the request host: the
    URL gets stored in products and pushed to the sites, so it must use the
    Hub's PUBLIC address — ``http://localhost:8000`` from the dev request only
    resolves on this machine and makes Woo reject the whole product
    (``woocommerce_product_image_upload_error``)."""

    url = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ["id", "image", "url", "original_name", "uploaded_at"]
        extra_kwargs = {"image": {"write_only": True}}
        read_only_fields = ["original_name", "uploaded_at"]

    def get_url(self, obj) -> str | None:
        from django.conf import settings

        if not obj.image:
            return None
        url = obj.image.url
        if settings.MEDIA_PUBLIC_BASE_URL:
            return f"{settings.MEDIA_PUBLIC_BASE_URL}{url}"
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url

    def validate_image(self, upload):
        content_type = getattr(upload, "content_type", "") or ""
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise serializers.ValidationError(
                f"Định dạng ảnh không hỗ trợ: {content_type or 'không rõ'}."
            )
        if upload.size and upload.size > MAX_IMAGE_BYTES:
            raise serializers.ValidationError("Ảnh vượt quá 5MB.")
        return upload

    def create(self, validated_data):
        upload = validated_data["image"]
        validated_data["original_name"] = (upload.name or "")[:255]
        if (getattr(upload, "content_type", "") or "") == "image/webp":
            validated_data["image"] = _webp_to_png(upload)
        return super().create(validated_data)


class ProductMappingSerializer(serializers.ModelSerializer):
    """Read-only per-site mapping shown nested on a product (which site holds it)."""

    site_name = serializers.CharField(source="site.name", read_only=True)

    class Meta:
        model = ProductMapping
        fields = ["site", "site_name", "woo_product_id", "last_synced_at"]


class CategorySerializer(serializers.ModelSerializer):
    """Read-only category for the product-form picker ("tick từ có sẵn").

    ``parent`` is the parent category id (null = root); the frontend builds the
    nested tree from this flat list.
    """

    mapping_count = serializers.IntegerField(source="mappings.count", read_only=True)

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "parent", "mapping_count"]


class ProductSyncStatusSerializer(serializers.Serializer):
    """One row of the per-product sync panel: a site + its sync state."""

    site_id = serializers.IntegerField()
    site_name = serializers.CharField()
    site_url = serializers.CharField()
    site_status = serializers.CharField()
    is_primary = serializers.BooleanField()
    synced = serializers.BooleanField()
    woo_product_id = serializers.IntegerField(allow_null=True)
    last_synced_at = serializers.DateTimeField(allow_null=True)


class MasterProductSerializer(serializers.ModelSerializer):
    """Full CRUD product. ``sku`` is normalized + checked unique on write; the
    per-site ``mappings`` are read-only (populated by the push, not the client)."""

    mappings = ProductMappingSerializer(many=True, read_only=True)
    mapping_count = serializers.IntegerField(source="mappings.count", read_only=True)

    class Meta:
        model = MasterProduct
        fields = [
            "id",
            "sku",
            "name",
            "type",
            "description",
            "short_description",
            "regular_price",
            "sale_price",
            "status",
            "stock_status",
            "weight",
            "images",
            "categories",
            "external_url",
            "button_text",
            "grouped_skus",
            "attributes",
            "variations",
            "mappings",
            "mapping_count",
            "created_at",
            "updated_at",
        ]

    def validate_sku(self, value):
        sku = normalize_sku(value)
        if not sku:
            raise serializers.ValidationError("SKU không được để trống.")
        qs = MasterProduct.objects.filter(sku=sku)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f"SKU đã tồn tại: {sku}")
        return sku

    def validate_grouped_skus(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("grouped_skus phải là danh sách SKU.")
        return [normalize_sku(s) for s in value if str(s).strip()]

    def validate_attributes(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("attributes phải là danh sách.")
        for attr in value:
            if not isinstance(attr, dict) or not str(attr.get("name", "")).strip():
                raise serializers.ValidationError("Mỗi thuộc tính cần có 'name'.")
        return value

    def validate_variations(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("variations phải là danh sách.")
        for variation in value:
            if not isinstance(variation, dict) or not str(variation.get("sku", "")).strip():
                raise serializers.ValidationError("Mỗi biến thể cần có 'sku'.")
            variation["sku"] = normalize_sku(variation["sku"])
        return value

    def validate(self, attrs):
        """Cross-field rules per product type (only the relevant ones)."""
        ptype = attrs.get("type") or getattr(self.instance, "type", "simple")
        if ptype == MasterProduct.Type.EXTERNAL:
            external_url = attrs.get("external_url") or getattr(self.instance, "external_url", "")
            if not external_url:
                raise serializers.ValidationError(
                    {"external_url": "Sản phẩm liên kết ngoài cần có URL."}
                )
        if ptype == MasterProduct.Type.VARIABLE:
            attributes = attrs.get("attributes")
            if attributes is None:
                attributes = getattr(self.instance, "attributes", []) or []
            if not any(a.get("variation") for a in attributes):
                raise serializers.ValidationError(
                    {
                        "attributes": "Sản phẩm biến thể cần ít nhất 1 thuộc tính "
                        "được dùng cho biến thể."
                    }
                )
        return attrs
