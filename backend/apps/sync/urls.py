from rest_framework.routers import DefaultRouter

from .views import CategorySyncRunViewSet, RunProgressViewSet

router = DefaultRouter()
router.register("sync/category-runs", CategorySyncRunViewSet, basename="category-run")
router.register("sync/run-progress", RunProgressViewSet, basename="run-progress")

urlpatterns = router.urls
