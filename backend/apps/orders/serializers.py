from rest_framework import serializers

from .models import Order


class OrderSerializer(serializers.ModelSerializer):
    """Read-only order row. Flattens the site/hosting relations the list screen
    needs so the frontend makes no follow-up requests. ``raw`` is intentionally
    excluded (large, internal); the detail modal uses ``line_items``."""

    site_name = serializers.CharField(source="site.name", read_only=True)
    hosting_name = serializers.CharField(
        source="site.hosting.name", read_only=True, default=None
    )

    class Meta:
        model = Order
        fields = [
            "id",
            "site",
            "site_name",
            "hosting_name",
            "woo_order_id",
            "number",
            "status",
            "currency",
            "total",
            "customer_name",
            "customer_phone",
            "customer_email",
            "shipping_address",
            "customer_note",
            "line_items",
            "forwarded",
            "forwarded_at",
            "date_created_woo",
            "created_at",
        ]
