from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    ChangePasswordView,
    GroupViewSet,
    MeView,
    PermissionCatalogView,
    UserViewSet,
    ViTokenObtainPairView,
)

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")
router.register("groups", GroupViewSet, basename="group")

urlpatterns = [
    path("token/", ViTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("me/", MeView.as_view(), name="auth_me"),
    path("change-password/", ChangePasswordView.as_view(), name="auth_change_password"),
    path("permissions/", PermissionCatalogView.as_view(), name="permission_catalog"),
    *router.urls,
]
