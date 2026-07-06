from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .permission_catalog import curated_permissions_qs


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


def _apply_full_name(user, full_name):
    """Split ``full_name`` into first/last name (first word / remainder)."""
    first, _, last = full_name.strip().partition(" ")
    user.first_name = first
    user.last_name = last


class UserSerializer(serializers.ModelSerializer):
    """Shape of ``/api/auth/me/`` — the FE gates UI on ``permissions``."""

    full_name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    groups = serializers.SlugRelatedField(
        slug_field="name", many=True, read_only=True
    )
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "full_name",
            "role",
            "is_superuser",
            "groups",
            "permissions",
        )

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_role(self, obj):
        return resolve_role(obj)

    def get_permissions(self, obj):
        # "app_label.codename" strings; superusers get every permission.
        return sorted(obj.get_all_permissions())


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
            _apply_full_name(instance, full_name)
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


# --- User CRUD (admin) ----------------------------------------------------


class GroupBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ("id", "name")


class UserAdminSerializer(serializers.ModelSerializer):
    """Read shape for the user management table."""

    full_name = serializers.SerializerMethodField()
    groups = GroupBriefSerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "full_name",
            "is_active",
            "is_superuser",
            "groups",
            "last_login",
            "date_joined",
        )

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username


class UserCreateSerializer(serializers.ModelSerializer):
    username = serializers.CharField(
        max_length=150,
        validators=[
            UnicodeUsernameValidator(),
            UniqueValidator(
                queryset=User.objects.all(), message="Tên đăng nhập đã tồn tại."
            ),
        ],
    )
    password = serializers.CharField(write_only=True)
    full_name = serializers.CharField(
        required=False, allow_blank=True, max_length=300
    )
    group_ids = serializers.PrimaryKeyRelatedField(
        many=True, source="groups", queryset=Group.objects.all(), required=False
    )

    class Meta:
        model = User
        fields = ("username", "email", "password", "full_name", "group_ids")

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        groups = validated_data.pop("groups", [])
        password = validated_data.pop("password")
        full_name = validated_data.pop("full_name", "")
        user = User(
            username=validated_data["username"],
            email=validated_data.get("email", ""),
        )
        if full_name:
            _apply_full_name(user, full_name)
        user.set_password(password)
        user.save()
        user.groups.set(groups)
        return user

    def to_representation(self, instance):
        return UserAdminSerializer(instance, context=self.context).data


class UserUpdateSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(
        required=False, allow_blank=True, max_length=300
    )
    group_ids = serializers.PrimaryKeyRelatedField(
        many=True, source="groups", queryset=Group.objects.all(), required=False
    )

    class Meta:
        model = User
        fields = ("email", "full_name", "group_ids", "is_active")

    def update(self, instance, validated_data):
        groups = validated_data.pop("groups", None)
        full_name = validated_data.pop("full_name", None)
        if full_name is not None:
            _apply_full_name(instance, full_name)
        for field in ("email", "is_active"):
            if field in validated_data:
                setattr(instance, field, validated_data[field])
        instance.save()
        if groups is not None:
            instance.groups.set(groups)
        return instance

    def to_representation(self, instance):
        return UserAdminSerializer(instance, context=self.context).data


class SetPasswordSerializer(serializers.Serializer):
    """Admin resets someone's password (no old password required)."""

    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        validate_password(value, self.context.get("target_user"))
        return value

    def save(self, **kwargs):
        user = self.context["target_user"]
        user.set_password(self.validated_data["password"])
        user.save(update_fields=["password"])
        return user


# --- Groups ----------------------------------------------------------------


class GroupSerializer(serializers.ModelSerializer):
    name = serializers.CharField(
        max_length=150,
        validators=[
            UniqueValidator(
                queryset=Group.objects.all(), message="Tên nhóm đã tồn tại."
            )
        ],
    )
    # Only curated permissions are assignable — internal models (mappings,
    # admin.logentry…) can never be handed to a group through the API.
    permission_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        source="permissions",
        queryset=curated_permissions_qs(),
        required=False,
    )
    permission_count = serializers.SerializerMethodField()
    user_count = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = ("id", "name", "permission_ids", "permission_count", "user_count")

    def get_permission_count(self, obj):
        return obj.permissions.count()

    def get_user_count(self, obj):
        return obj.user_set.count()
