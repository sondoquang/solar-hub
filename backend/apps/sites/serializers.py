from rest_framework import serializers

from .models import Site


class SiteSerializer(serializers.ModelSerializer):
    """Read: safe fields only. Write: accepts ``consumer_secret`` (write-only);
    the secret is never echoed back and ``consumer_secret_enc`` is never exposed."""

    consumer_secret = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = Site
        fields = [
            "id",
            "name",
            "base_url",
            "consumer_key",
            "consumer_secret",
            "status",
            "last_checked_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "last_checked_at", "created_at", "updated_at"]

    def validate(self, attrs):
        # Secret is mandatory on create, optional on update.
        if self.instance is None and not attrs.get("consumer_secret"):
            raise serializers.ValidationError({"consumer_secret": "Bắt buộc khi tạo site."})
        return attrs
