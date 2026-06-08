from rest_framework.routers import DefaultRouter

from .views import HostingViewSet, SiteNoteViewSet, SiteViewSet

router = DefaultRouter()
router.register("sites", SiteViewSet, basename="site")
router.register("hostings", HostingViewSet, basename="hosting")
router.register("site-notes", SiteNoteViewSet, basename="site-note")

urlpatterns = router.urls
