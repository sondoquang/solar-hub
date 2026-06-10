from django.contrib import admin

from .models import Order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "site",
        "status",
        "classification",
        "risk_score",
        "total",
        "currency",
        "forwarded",
        "date_created_woo",
    )
    list_filter = ("status", "classification", "forwarded", "site")
    search_fields = ("number", "customer_name", "customer_phone", "site__name")
    date_hierarchy = "date_created_woo"
    autocomplete_fields = ("site",)
    readonly_fields = tuple(f.name for f in Order._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
