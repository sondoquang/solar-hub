from django import forms
from django.contrib import admin, messages

from . import services
from .crypto import encrypt_secret
from .models import Hosting, Site, SiteNote, SiteNoteImage


@admin.register(Hosting)
class HostingAdmin(admin.ModelAdmin):
    list_display = ("name", "provider", "account_username", "check_concurrency")
    list_filter = ("provider",)
    search_fields = ("name", "provider", "account_username")
    readonly_fields = ("created_at", "updated_at")


class SiteAdminForm(forms.ModelForm):
    """Admin form: enter the secret as plaintext (password widget); it is
    encrypted into ``consumer_secret_enc`` on save and never displayed."""

    consumer_secret = forms.CharField(
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="Bắt buộc khi tạo. Để trống khi sửa nếu không đổi secret.",
    )

    class Meta:
        model = Site
        fields = ["name", "base_url", "consumer_key", "consumer_secret", "hosting"]

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk is None and not cleaned.get("consumer_secret"):
            self.add_error("consumer_secret", "Bắt buộc khi tạo site.")
        return cleaned

    def save(self, commit=True):
        site = super().save(commit=False)
        secret = self.cleaned_data.get("consumer_secret")
        if secret:
            site.consumer_secret_enc = encrypt_secret(secret)
        if commit:
            site.save()
        return site


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    form = SiteAdminForm
    list_display = ("name", "base_url", "hosting", "status", "last_checked_at")
    list_filter = ("status", "hosting")
    search_fields = ("name", "base_url")
    readonly_fields = ("status", "last_checked_at", "created_at", "updated_at")
    actions = ["run_test_connection"]

    @admin.action(description="Test connection (selected)")
    def run_test_connection(self, request, queryset):
        up = 0
        for site in queryset:
            if services.test_connection(site)["ok"]:
                up += 1
        self.message_user(
            request,
            f"Đã test {queryset.count()} site, {up} up.",
            level=messages.INFO,
        )


class SiteNoteImageInline(admin.TabularInline):
    model = SiteNoteImage
    extra = 0
    readonly_fields = ("uploaded_at",)


@admin.register(SiteNote)
class SiteNoteAdmin(admin.ModelAdmin):
    list_display = ("id", "site", "created_by", "created_at", "is_deleted")
    list_filter = ("is_deleted",)
    search_fields = ("site__name", "site__base_url", "content")
    readonly_fields = ("created_at", "updated_at", "deleted_at")
    inlines = [SiteNoteImageInline]
