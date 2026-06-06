from rest_framework.routers import DefaultRouter

from .views import HealthCheckViewSet

router = DefaultRouter()
router.register("healthchecks", HealthCheckViewSet, basename="healthcheck")

urlpatterns = router.urls
