from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


class ViTokenObtainPairSerializer(TokenObtainPairSerializer):
    default_error_messages = {
        "no_active_account": "Tên đăng nhập hoặc mật khẩu không đúng."
    }


def resolve_role(user):
    """Derive a display role from Django permission flags."""
    if user.is_superuser:
        return "Quản trị viên"
    if user.is_staff:
        return "Nhân viên"
    return "Người dùng"


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "username", "email", "full_name", "role")

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_role(self, obj):
        return resolve_role(obj)


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """Writable profile fields. ``full_name`` is split into first/last name."""

    full_name = serializers.CharField(
        required=False, allow_blank=True, max_length=300
    )

    class Meta:
        model = User
        fields = ("email", "full_name")

    def update(self, instance, validated_data):
        full_name = validated_data.pop("full_name", None)
        if full_name is not None:
            first, _, last = full_name.strip().partition(" ")
            instance.first_name = first
            instance.last_name = last
        if "email" in validated_data:
            instance.email = validated_data["email"]
        instance.save()
        return instance


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Mật khẩu hiện tại không đúng.")
        return value

    def validate_new_password(self, value):
        validate_password(value, self.context["request"].user)
        return value

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save()
        return user
