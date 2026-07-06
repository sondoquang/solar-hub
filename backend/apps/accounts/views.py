from django.contrib.auth.models import Group, User
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .permission_catalog import build_catalog
from .serializers import (
    ChangePasswordSerializer,
    GroupSerializer,
    ProfileUpdateSerializer,
    SetPasswordSerializer,
    UserAdminSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
    ViTokenObtainPairSerializer,
)


class ViTokenObtainPairView(TokenObtainPairView):
    serializer_class = ViTokenObtainPairSerializer


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = ProfileUpdateSerializer(
            request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserViewSet(viewsets.ModelViewSet):
    """User CRUD for admins. RBACPermission maps the queryset to
    ``auth.view/add/change/delete_user``; DELETE deactivates instead of
    removing the row (audit FKs — SiteNote/HealthCheck/SyncLog — survive).
    SimpleJWT rejects ``is_active=False`` on every request, so deactivation
    cuts access immediately even with a live token.
    """

    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["username", "email", "first_name", "last_name"]
    ordering_fields = ["username", "date_joined", "last_login"]
    ordering = ["-date_joined"]
    action_perms = {
        "activate": ["auth.change_user"],
        "set_password": ["auth.change_user"],
    }

    def get_queryset(self):
        qs = User.objects.prefetch_related("groups").order_by("-date_joined")
        is_active = self.request.query_params.get("is_active")
        if is_active in ("true", "false"):
            qs = qs.filter(is_active=is_active == "true")
        group = self.request.query_params.get("group")
        if group:
            qs = qs.filter(groups__id=group)
        return qs

    def get_serializer_class(self):
        if self.action == "create":
            return UserCreateSerializer
        if self.action == "partial_update":
            return UserUpdateSerializer
        return UserAdminSerializer

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        if user.pk == request.user.pk:
            raise ValidationError(
                "Không thể tự vô hiệu hóa tài khoản của chính mình."
            )
        user.is_active = False
        user.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        user = self.get_object()
        user.is_active = True
        user.save(update_fields=["is_active"])
        return Response(UserAdminSerializer(user).data)

    @action(detail=True, methods=["post"])
    def set_password(self, request, pk=None):
        user = self.get_object()
        serializer = SetPasswordSerializer(
            data=request.data, context={"target_user": user}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class GroupViewSet(viewsets.ModelViewSet):
    """Group CRUD + permission assignment (the RBAC matrix)."""

    serializer_class = GroupSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filter_backends = [SearchFilter]
    search_fields = ["name"]

    def get_queryset(self):
        return Group.objects.prefetch_related("permissions").order_by("name")

    def perform_destroy(self, instance):
        if instance.user_set.exists():
            raise ValidationError("Không thể xóa nhóm đang có người dùng.")
        instance.delete()


class PermissionCatalogView(APIView):
    """Curated permission catalog (VN labels) feeding the group matrix UI."""

    required_perms = {"GET": ["auth.view_group"]}

    def get(self, request):
        return Response(build_catalog())
