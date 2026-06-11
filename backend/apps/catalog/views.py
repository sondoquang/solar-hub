"""Catalog API — CRUD over the master catalog + a manual "Sync all" trigger.

- ``GET/POST /api/products/``        — paginated list / create.
- ``GET/PATCH/DELETE /api/products/{id}/`` — retrieve / update / soft-delete.
- ``GET  /api/products/stats/``      — totals (mapped/unmapped) for the filter.
- ``POST /api/products/sync_now/``   — push the catalog to sites (the "Đồng bộ ngay").
- ``GET/POST/DELETE /api/products/media/`` — product media library (upload ảnh).

Products are edited here (single source of truth); the push to each WooCommerce
site is heavy + per-site, so it runs in Celery (``apps/sync/tasks``), never in
the request cycle.
"""

from django.utils import timezone
from rest_framework import mixins
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from . import services
from .models import Category, MasterProduct, ProductImage
from .serializers import (
    CategorySerializer,
    MasterProductSerializer,
    ProductImageSerializer,
    ProductSyncStatusSerializer,
)


class MasterProductViewSet(viewsets.ModelViewSet):
    serializer_class = MasterProductSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["sku", "name"]
    ordering_fields = ["name", "sku", "updated_at"]
    ordering = ["-updated_at"]

    def get_queryset(self):
        qs = MasterProduct.objects.filter(is_deleted=False).prefetch_related("mappings__site")
        return services.list_products_qs(qs, self.request.query_params)

    def perform_destroy(self, instance):
        """Soft-delete so the next push removes the product from each site
        (the per-site ``woo_product_id`` lives on its mappings)."""
        instance.is_deleted = True
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Totals (mapped/unmapped, by status) for the filtered range (cards)."""
        qs = self.filter_queryset(self.get_queryset())
        return Response(services.product_stats(qs))

    @action(detail=False, methods=["post"])
    def sync_now(self, request):
        """Trigger an immediate catalog push (async, via Celery).

        Body (all optional): ``sites`` (list of site ids; the whole fleet when
        omitted) and ``products`` (list of MasterProduct ids; the whole catalog
        when omitted). Validation only — the heavy per-site push runs in the task.
        """
        from apps.sync.tasks import push_all_products

        sites = request.data.get("sites")
        if sites is not None and (
            not isinstance(sites, list) or not all(isinstance(s, int) for s in sites)
        ):
            return Response(
                {"detail": "sites phải là danh sách id (số nguyên)."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        products = request.data.get("products")
        if products is not None and (
            not isinstance(products, list) or not all(isinstance(p, int) for p in products)
        ):
            return Response(
                {"detail": "products phải là danh sách id (số nguyên)."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        result = push_all_products.delay(site_ids=sites or None, master_ids=products or None)
        return Response({"task_id": result.id})

    @action(detail=True, methods=["get"])
    def sync_status(self, request, pk=None):
        """Per-product sync state across every active site (đã/chưa đồng bộ)."""
        master = self.get_object()
        rows = services.product_sync_status(master)
        return Response(ProductSyncStatusSerializer(rows, many=True).data)


class ProductImageViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Product media library (kiểu WP Media Library).

    - ``GET    /api/products/media/``      — newest-first list (search ``?search=``).
    - ``POST   /api/products/media/``      — multipart upload, field ``image``.
    - ``DELETE /api/products/media/{id}/`` — remove file + row (hard delete: the
      library row carries no sync state; URLs already referenced by products
      keep working only while the file exists, so deleting is an admin choice).

    The response's absolute ``url`` is what gets stored in
    ``MasterProduct.images`` / embedded in description HTML — the catalog model
    stays URL-based and the Woo push payload is unchanged.
    """

    queryset = ProductImage.objects.all()
    serializer_class = ProductImageSerializer
    parser_classes = [MultiPartParser, FormParser]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["original_name"]
    ordering_fields = ["uploaded_at"]
    ordering = ["-uploaded_at"]

    def perform_destroy(self, instance):
        # Remove the file from MEDIA_ROOT too, not just the DB row.
        instance.image.delete(save=False)
        instance.delete()


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only category catalog for the form picker, plus a manual pull trigger.

    - ``GET  /api/products/categories/``          — list known categories (search).
    - ``POST /api/products/categories/pull_now/`` — pull categories from the sites.

    Categories are created/synced *down* implicitly through the product push
    (a product carrying a new category name makes Woo create it); this viewset is
    the *up* direction (Woo → Hub) so the picker shows what already exists.
    """

    queryset = Category.objects.filter(is_deleted=False)
    serializer_class = CategorySerializer
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name"]
    ordering = ["name"]

    @action(detail=False, methods=["post"])
    def pull_now(self, request):
        """Trigger an async category pull from sites (validation only here).

        Generates the ``run_id`` here so the response carries it — every
        per-site ``SyncLog`` row of this fan-out is stamped with it and the
        category-run report (``/api/sync/category-runs/``) groups by it.
        """
        import uuid

        from apps.sync.tasks import pull_all_categories

        sites = request.data.get("sites")
        if sites is not None and (
            not isinstance(sites, list) or not all(isinstance(s, int) for s in sites)
        ):
            return Response(
                {"detail": "sites phải là danh sách id (số nguyên)."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        run_id = str(uuid.uuid4())
        result = pull_all_categories.delay(site_ids=sites or None, run_id=run_id)
        return Response({"task_id": result.id, "run_id": run_id})
