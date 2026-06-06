from django.contrib import admin

from .models import HealthCheck


@admin.register(HealthCheck)
class HealthCheckAdmin(admin.ModelAdmin):
    list_display = (
        "site",
        "status",
        "check_type",
        "response_time_ms",
        "performed_by",
        "checked_at",
    )
    list_filter = ("status", "check_type", "checked_at")
    search_fields = ("site__name", "site__base_url")
    date_hierarchy = "checked_at"
    autocomplete_fields = ("site",)
    readonly_fields = tuple(f.name for f in HealthCheck._meta.fields)
