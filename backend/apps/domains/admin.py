from django.contrib import admin

from .models import DomainInfo


@admin.register(DomainInfo)
class DomainInfoAdmin(admin.ModelAdmin):
    """Read-mostly ops view; rows are produced by the Celery checks."""

    list_display = (
        "domain",
        "site",
        "whois_registrar",
        "whois_expires_at",
        "ssl_not_after",
        "blacklist_verdict",
        "gindex_status",
        "last_refreshed_at",
    )
    list_filter = ("whois_status", "ssl_status", "blacklist_verdict", "gindex_status")
    search_fields = ("domain", "host", "site__name", "site__base_url")
    ordering = ("whois_expires_at",)

    def has_add_permission(self, request):
        return False
