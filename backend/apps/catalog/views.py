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
from rest_framework import mixins, viewsets
from rest_framework import status as http_status
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from config.pagination import StandardPagination

from . import services
from .models import Category, MasterProduct, ProductImage
from .serializers import (
    CategoryMappingRowSerializer,
    CategoryMatrixRowSerializer,
    CategorySerializer,
    CategorySiteLinkSerializer,
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
        import uuid

        from apps.sites.models import Site
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

        # ``run_id`` groups this push's per-site SyncLog rows so the progress
        # banner can poll "X/Y site hoàn tất"; ``expected`` is the live-site count
        # the task will push to (same query as push_all_products). Each site
        # writes exactly one row (including no-op sites), so ``done`` reaches it.
        run_id = str(uuid.uuid4())
        triggered_by_id = request.user.id if request.user.is_authenticated else None
        site_qs = Site.objects.filter(is_deleted=False)
        if sites:
            site_qs = site_qs.filter(id__in=sites)
        expected = site_qs.count()

        result = push_all_products.delay(
            site_ids=sites or None,
            master_ids=products or None,
            run_id=run_id,
            triggered_by_id=triggered_by_id,
        )
        return Response({"task_id": result.id, "run_id": run_id, "expected": expected})

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


class CategoryPickerPagination(StandardPagination):
    """The form picker loads the WHOLE catalog in one go (hàng trăm danh mục);
    the default cap (max 100/trang) silently truncated it, making existing
    categories unfindable in the picker."""

    page_size = 1000
    max_page_size = 1000


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only category catalog for the form picker, plus a manual pull trigger.

    - ``GET  /api/products/categories/``          — list known categories (search).
    - ``GET  /api/products/categories/overview/`` — stat-card counts (dashboard).
    - ``GET  /api/products/categories/matrix/``   — cross-site matrix (Hub × sites).
    - ``GET  /api/products/categories/{id}/sites/`` — one category's per-site links.
    - ``GET  /api/products/categories/mappings/`` — per-site mapping (site → Hub).
    - ``POST /api/products/categories/pull_now/`` — pull categories from the sites.
    - ``POST /api/products/categories/clear_all/`` — reset the catalog (soft-delete).

    Categories are created/synced *down* implicitly through the product push
    (a product carrying a new category name makes Woo create it); this viewset is
    the *up* direction (Woo → Hub) so the picker shows what already exists.
    """

    queryset = Category.objects.filter(is_deleted=False)
    serializer_class = CategorySerializer
    pagination_class = CategoryPickerPagination
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name"]
    ordering = ["name"]

    @action(detail=False, methods=["get"])
    def overview(self, request):
        """Counts for the Tổng quan + Cây danh mục Hub stat cards (cards only —
        independent of any paging/list)."""
        return Response(services.category_overview())

    @action(detail=False, methods=["get"])
    def matrix(self, request):
        """Cross-site matrix (paginated). One row per live Hub category with its
        per-site cells; the response carries ``sites`` (the column headers — every
        live site) so the frontend can render the dynamic per-site columns.

        ``GET /api/products/categories/matrix/?search=&ordering=&page=&page_size=``
        """
        qs = services.category_matrix_qs(request.query_params)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        response = paginator.get_paginated_response(
            CategoryMatrixRowSerializer(page, many=True).data
        )
        response.data["sites"] = services.active_sites_columns()
        return response

    @action(detail=True, methods=["get"])
    def sites(self, request, pk=None):
        """Every live site annotated with this category's link state (đã/chưa
        liên kết + woo id/tên RAW/last_synced_at) — the tree-tab detail panel."""
        category = self.get_object()
        rows = services.category_site_links(category)
        return Response(CategorySiteLinkSerializer(rows, many=True).data)

    @action(detail=False, methods=["get"])
    def mappings(self, request):
        """Per-site category mapping (read-only, paginated).

        ``GET /api/products/categories/mappings/?site=<id>[&search=&ordering=&page=&page_size=]``
        — mỗi row là một category trên site đó: ``woo_category_id`` + ``woo_name``
        (tên RAW trên site) và Hub category nó map về. ``site`` là bắt buộc.
        """
        site_id = request.query_params.get("site")
        if not site_id or not str(site_id).isdigit():
            return Response(
                {"detail": "Thiếu hoặc sai tham số site."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        qs = services.list_category_mappings_qs(int(site_id), request.query_params)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(CategoryMappingRowSerializer(page, many=True).data)

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
        triggered_by_id = request.user.id if request.user.is_authenticated else None
        result = pull_all_categories.delay(
            site_ids=sites or None, run_id=run_id, triggered_by_id=triggered_by_id
        )
        return Response({"task_id": result.id, "run_id": run_id})

    @action(detail=False, methods=["post"])
    def clear_all(self, request):
        """Reset the category catalog so it can be re-pulled from scratch.

        Soft-deletes Hub categories + clears their mappings and the pull history,
        keeping any category a live product still uses (and its ancestors). Pure
        DB work (bounded), so it runs synchronously and returns the counts for the
        toast. The intended workflow: clear, then pull the primary sites first so
        their tree becomes the canonical base (a re-pull revives kept names).
        """
        return Response(services.clear_category_sync_data())
