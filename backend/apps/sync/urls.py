from rest_framework.routers import DefaultRouter

from .views import CategorySyncRunViewSet

router = DefaultRouter()
router.register("sync/category-runs", CategorySyncRunViewSet, basename="category-run")

urlpatterns = router.urls
