from rest_framework import serializers

from .models import HealthCheck


class HealthCheckSerializer(serializers.ModelSerializer):
    """Read-only history row. Flattens the site/hosting/user relations the list
    screen needs so the frontend never makes follow-up requests."""

    site_name = serializers.CharField(source="site.name", read_only=True)
    base_url = serializers.CharField(source="site.base_url", read_only=True)
    hosting_name = serializers.CharField(
        source="site.hosting.name", read_only=True, default=None
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    check_type_display = serializers.CharField(
        source="get_check_type_display", read_only=True
    )
    performed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = HealthCheck
        fields = [
            "id",
            "site",
            "site_name",
            "base_url",
            "hosting_name",
            "status",
            "status_display",
            "check_type",
            "check_type_display",
            "response_time_ms",
            "ok",
            "detail",
            "performed_by",
            "performed_by_name",
            "checked_at",
        ]

    def get_performed_by_name(self, obj) -> str:
        if obj.performed_by is None:
            return "Hệ thống"
        return obj.performed_by.get_full_name() or obj.performed_by.get_username()
