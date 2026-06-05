from rest_framework import serializers

from .models import Hosting, Site


class HostingSerializer(serializers.ModelSerializer):
    """A hosting that groups sites. Exposes aggregated health of its (non-deleted)
    member sites so the UI can show health grouped by hosting."""

    site_count = serializers.SerializerMethodField()
    status_counts = serializers.SerializerMethodField()

    class Meta:
        model = Hosting
        fields = [
            "id",
            "name",
            "provider",
            "account_username",
            "note",
            "check_concurrency",
            "site_count",
            "status_counts",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def _active_sites(self, obj):
        # Uses the prefetched ``sites`` relation; filter in Python to avoid N+1.
        return [s for s in obj.sites.all() if not s.is_deleted]

    def get_site_count(self, obj) -> int:
        return len(self._active_sites(obj))

    def get_status_counts(self, obj) -> dict:
        counts = {"up": 0, "down": 0, "unknown": 0}
        for site in self._active_sites(obj):
            counts[site.status if site.status in counts else "unknown"] += 1
        return counts

    def validate_name(self, value: str) -> str:
        return value.strip()


class SiteSerializer(serializers.ModelSerializer):
    """Read: safe fields only. Write: accepts ``consumer_secret`` (write-only);
    the secret is never echoed back and ``consumer_secret_enc`` is never exposed."""

    name = serializers.CharField(
        max_length=120,
        error_messages={"blank": "Không được để trống.", "required": "Bắt buộc."},
    )
    base_url = serializers.URLField(
        error_messages={
            "blank": "Không được để trống.",
            "required": "Bắt buộc.",
            "invalid": "URL không hợp lệ (ví dụ: https://shop.example.com).",
        },
    )
    consumer_key = serializers.CharField(
        max_length=120,
        error_messages={"blank": "Không được để trống.", "required": "Bắt buộc."},
    )
    consumer_secret = serializers.CharField(write_only=True, required=False, allow_blank=True)
    hosting = serializers.PrimaryKeyRelatedField(
        queryset=Hosting.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    hosting_name = serializers.CharField(source="hosting.name", read_only=True)

    class Meta:
        model = Site
        fields = [
            "id",
            "name",
            "base_url",
            "consumer_key",
            "consumer_secret",
            "hosting",
            "hosting_name",
            "status",
            "last_checked_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "last_checked_at", "created_at", "updated_at"]

    def validate_name(self, value: str) -> str:
        return value.strip()

    def validate_base_url(self, value: str) -> str:
        value = value.strip().rstrip("/")
        qs = Site.objects.filter(base_url=value, is_deleted=False)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("URL này đã được đăng ký.")
        return value

    def validate_consumer_key(self, value: str) -> str:
        return value.strip()

    def validate(self, attrs):
        if self.instance is None and not attrs.get("consumer_secret"):
            raise serializers.ValidationError({"consumer_secret": "Bắt buộc khi tạo site."})
        return attrs
