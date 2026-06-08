from django.contrib import admin

from .models import SyncLog


@admin.register(SyncLog)
class SyncLogAdmin(admin.ModelAdmin):
    list_display = (
        "operation",
        "site",
        "status",
        "created_count",
        "updated_count",
        "deleted_count",
        "created_at",
    )
    list_filter = ("operation", "status", "site")
    search_fields = ("site__name", "error")
    date_hierarchy = "created_at"
    readonly_fields = tuple(f.name for f in SyncLog._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
