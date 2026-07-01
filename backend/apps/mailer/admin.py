from django import forms
from django.contrib import admin

from .models import MailSettings


class MailSettingsAdminForm(forms.ModelForm):
    """Enter the app password as plaintext (password widget); it is encrypted
    into ``password_enc`` on save and never displayed."""

    password = forms.CharField(
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="Mật khẩu ứng dụng (app password). Để trống nếu không đổi.",
    )

    class Meta:
        model = MailSettings
        fields = [
            "smtp_host",
            "smtp_port",
            "use_tls",
            "use_ssl",
            "username",
            "from_email",
            "from_name",
            "recipients",
            "digest_enabled",
            "digest_times",
            "password",
        ]

    def save(self, commit=True):
        obj = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            obj.set_password(password)
        if commit:
            obj.save()
        return obj


@admin.register(MailSettings)
class MailSettingsAdmin(admin.ModelAdmin):
    form = MailSettingsAdminForm
    list_display = ("username", "smtp_host", "digest_enabled", "last_digest_sent_at")
    readonly_fields = ("last_digest_sent_at", "updated_at")

    def has_add_permission(self, request):
        # Singleton: only one row, created on first load.
        return not MailSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
