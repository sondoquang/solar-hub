from rest_framework import serializers

from . import services
from .models import MailSettings


class MailSettingsSerializer(serializers.ModelSerializer):
    """Read/update the singleton SMTP config.

    The app password is write-only: it is accepted as plaintext, encrypted on
    save, and never serialized back. A blank/omitted ``password`` on update keeps
    the stored one (mirrors the site ``consumer_secret`` edit flow). ``has_password``
    lets the UI show whether a password is already saved.
    """

    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        style={"input_type": "password"},
    )
    has_password = serializers.BooleanField(read_only=True)
    recipients = serializers.ListField(
        child=serializers.EmailField(), required=False, allow_empty=True
    )
    # Daily send times ("HH:MM"); stored normalized (zero-padded, deduped, sorted).
    digest_times = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True
    )

    def validate_digest_times(self, value):
        try:
            return services.parse_digest_times(value, strict=True)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

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
            "has_password",
            "last_digest_sent_at",
            "updated_at",
        ]
        read_only_fields = ["last_digest_sent_at", "updated_at"]

    def update(self, instance, validated_data):
        # A non-empty password sets/replaces the secret; blank means "unchanged".
        password = validated_data.pop("password", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance
