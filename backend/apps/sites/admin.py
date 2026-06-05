from django import forms
from django.contrib import admin, messages

from . import services
from .crypto import encrypt_secret
from .models import Site


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
        fields = ["name", "base_url", "consumer_key", "consumer_secret"]

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
    list_display = ("name", "base_url", "status", "last_checked_at")
    list_filter = ("status",)
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
