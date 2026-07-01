from rest_framework import serializers

from . import services
from .models import Order


class OrderSerializer(serializers.ModelSerializer):
    """Read-only order row. Flattens the site/hosting relations the list screen
    needs so the frontend makes no follow-up requests. ``raw`` is intentionally
    excluded (large, internal); the detail modal uses ``line_items``."""

    site_name = serializers.CharField(source="site.name", read_only=True)
    hosting_name = serializers.CharField(
        source="site.hosting.name", read_only=True, default=None
    )
    # "woocommerce" / "sapo" — the Sapo orders page keys its actions off this.
    platform = serializers.CharField(source="site.platform", read_only=True)
    classification_display = serializers.CharField(
        source="get_classification_display", read_only=True
    )
    risk_reasons_display = serializers.SerializerMethodField()

    def get_risk_reasons_display(self, obj) -> list[str]:
        """The fired rule codes mapped to Vietnamese labels for the UI."""
        return [
            services.REASON_LABELS.get(code, code) for code in (obj.risk_reasons or [])
        ]

    class Meta:
        model = Order
        fields = [
            "id",
            "site",
            "site_name",
            "hosting_name",
            "platform",
            "woo_order_id",
            "number",
            "status",
            "payment_status",
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
            "classification",
            "classification_display",
            "risk_score",
            "risk_reasons",
            "risk_reasons_display",
            "date_created_woo",
            "created_at",
        ]
