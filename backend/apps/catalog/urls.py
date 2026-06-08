from rest_framework.routers import DefaultRouter

from .views import MasterProductViewSet

router = DefaultRouter()
router.register("products", MasterProductViewSet, basename="product")

urlpatterns = router.urls
