from rest_framework.routers import DefaultRouter

from .views import HostingViewSet, SiteViewSet

router = DefaultRouter()
router.register("sites", SiteViewSet, basename="site")
router.register("hostings", HostingViewSet, basename="hosting")

urlpatterns = router.urls
