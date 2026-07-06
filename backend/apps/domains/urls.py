from rest_framework.routers import DefaultRouter

from .views import DomainInfoViewSet

router = DefaultRouter()
router.register("domain-info", DomainInfoViewSet, basename="domain-info")

urlpatterns = router.urls
