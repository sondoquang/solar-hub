from rest_framework import serializers

from .models import MasterProduct, ProductMapping
from .services import normalize_sku


class ProductMappingSerializer(serializers.ModelSerializer):
    """Read-only per-site mapping shown nested on a product (which site holds it)."""

    site_name = serializers.CharField(source="site.name", read_only=True)

    class Meta:
        model = ProductMapping
        fields = ["site", "site_name", "woo_product_id", "last_synced_at"]


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
