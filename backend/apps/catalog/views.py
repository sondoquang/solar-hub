"""Catalog API — CRUD over the master catalog + a manual "Sync all" trigger.

- ``GET/POST /api/products/``        — paginated list / create.
- ``GET/PATCH/DELETE /api/products/{id}/`` — retrieve / update / soft-delete.
- ``GET  /api/products/stats/``      — totals (mapped/unmapped) for the filter.
- ``POST /api/products/sync_now/``   — push the catalog to sites (the "Đồng bộ ngay").

Products are edited here (single source of truth); the push to each WooCommerce
site is heavy + per-site, so it runs in Celery (``apps/sync/tasks``), never in
the request cycle.
"""

from django.utils import timezone
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from . import services
from .models import MasterProduct
from .serializers import MasterProductSerializer


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
