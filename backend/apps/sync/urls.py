from rest_framework.routers import DefaultRouter

from .views import (
    CategorySyncRunViewSet,
    NotificationViewSet,
    ProductSyncRunViewSet,
    RunProgressViewSet,
)

router = DefaultRouter()
router.register("sync/category-runs", CategorySyncRunViewSet, basename="category-run")
router.register("sync/product-runs", ProductSyncRunViewSet, basename="product-run")
router.register("sync/run-progress", RunProgressViewSet, basename="run-progress")
router.register("notifications", NotificationViewSet, basename="notification")

urlpatterns = router.urls
