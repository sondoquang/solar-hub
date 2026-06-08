from rest_framework.routers import DefaultRouter

from .views import CategoryViewSet, MasterProductViewSet

router = DefaultRouter()
# Register the more specific prefix first so the router does not treat
# "categories" as a product pk.
router.register("products/categories", CategoryViewSet, basename="category")
router.register("products", MasterProductViewSet, basename="product")

urlpatterns = router.urls
