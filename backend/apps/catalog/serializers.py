from rest_framework import serializers

from .models import Category, MasterProduct, ProductMapping
from .services import normalize_sku


class ProductMappingSerializer(serializers.ModelSerializer):
    """Read-only per-site mapping shown nested on a product (which site holds it)."""

    site_name = serializers.CharField(source="site.name", read_only=True)

    class Meta:
        model = ProductMapping
        fields = ["site", "site_name", "woo_product_id", "last_synced_at"]


class CategorySerializer(serializers.ModelSerializer):
    """Read-only category for the product-form picker ("tick từ có sẵn")."""

    mapping_count = serializers.IntegerField(source="mappings.count", read_only=True)

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "parent_name", "mapping_count"]


class ProductSyncStatusSerializer(serializers.Serializer):
    """One row of the per-product sync panel: a site + its sync state."""

    site_id = serializers.IntegerField()
    site_name = serializers.CharField()
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
