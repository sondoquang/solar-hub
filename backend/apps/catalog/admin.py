from django.contrib import admin, messages

from .models import MasterProduct, ProductMapping
from .services import normalize_sku


class ProductMappingInline(admin.TabularInline):
    """Per-site mappings, read-only (written by the push, not by hand)."""

    model = ProductMapping
    extra = 0
    readonly_fields = ("site", "woo_product_id", "last_synced_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(MasterProduct)
class MasterProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "status", "stock_status", "regular_price", "updated_at")
    list_filter = ("status", "stock_status")
    search_fields = ("sku", "name")
    readonly_fields = ("created_at", "updated_at")
    inlines = [ProductMappingInline]
    actions = ["push_selected"]

    def save_model(self, request, obj, form, change):
        obj.sku = normalize_sku(obj.sku)
        super().save_model(request, obj, form, change)

    @admin.action(description="Đồng bộ sản phẩm đã chọn xuống các site")
    def push_selected(self, request, queryset):
        from apps.sync.tasks import push_all_products

        ids = list(queryset.values_list("id", flat=True))
        push_all_products.delay(master_ids=ids)
        self.message_user(
            request,
            f"Đã kích hoạt đồng bộ {len(ids)} sản phẩm xuống các site.",
            level=messages.INFO,
        )
