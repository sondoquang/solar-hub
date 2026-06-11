from rest_framework.routers import DefaultRouter

from .views import CategoryViewSet, MasterProductViewSet, ProductImageViewSet

router = DefaultRouter()
# Register the more specific prefixes first so the router does not treat
# "categories"/"media" as a product pk.
router.register("products/categories", CategoryViewSet, basename="category")
router.register("products/media", ProductImageViewSet, basename="product-media")
router.register("products", MasterProductViewSet, basename="product")

urlpatterns = router.urls
