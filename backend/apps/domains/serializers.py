from django.utils import timezone
from rest_framework import serializers

from .models import DomainInfo


def _days_remaining(value):
    if value is None:
        return None
    return (value - timezone.now()).days


class DomainInfoSerializer(serializers.ModelSerializer):
    """Read-only snapshot. Flattens the site fields the list/modal need and
    computes the expiry countdowns so the frontend never re-derives dates."""

    site_name = serializers.CharField(source="site.name", read_only=True)
    base_url = serializers.CharField(source="site.base_url", read_only=True)
    whois_days_remaining = serializers.SerializerMethodField()
    ssl_days_remaining = serializers.SerializerMethodField()
    blacklist_verdict_display = serializers.CharField(
        source="get_blacklist_verdict_display", read_only=True
    )
    is_pending = serializers.BooleanField(read_only=True)

    class Meta:
        model = DomainInfo
        fields = [
            "id",
            "site",
            "site_name",
            "base_url",
            "host",
            "domain",
            "whois_status",
            "whois_registrar",
            "whois_created_at",
            "whois_expires_at",
            "whois_days_remaining",
            "whois_source",
            "whois_checked_at",
            "dns_status",
            "dns_records",
            "dns_checked_at",
            "ssl_status",
            "ssl_issuer",
            "ssl_subject",
            "ssl_not_before",
            "ssl_not_after",
            "ssl_days_remaining",
            "ssl_checked_at",
            "blacklist_status",
            "blacklist_verdict",
            "blacklist_verdict_display",
            "blacklist_results",
            "blacklist_checked_at",
            "gindex_status",
            "gindex_indexed",
            "gindex_total_results",
            "gindex_checked_at",
            "last_refreshed_at",
            "last_error",
            "is_pending",
        ]

    def get_whois_days_remaining(self, obj):
        return _days_remaining(obj.whois_expires_at)

    def get_ssl_days_remaining(self, obj):
        return _days_remaining(obj.ssl_not_after)
