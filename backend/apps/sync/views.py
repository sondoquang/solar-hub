"""Sync report API — read-only view over category-pull runs.

- ``GET /api/sync/category-runs/``               — paginated run list (newest first).
- ``GET /api/sync/category-runs/{run_id}/``      — per-site detail incl. category snapshots.
- ``GET /api/sync/category-runs/{run_id}/export/`` — the run as an .xlsx report.

Rows are written by ``apps.catalog.services.pull_categories_for_site``; this
app only reads them. Runs predating the ``run_id`` field never appear here.
"""

from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from config.pagination import StandardPagination

from . import services
from .serializers import CategoryRunDetailSerializer, CategoryRunListSerializer

XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


class CategorySyncRunViewSet(viewsets.ViewSet):
    # Constrain the lookup to a UUID so arbitrary strings 404 at the router
    # instead of blowing up the UUIDField filter.
    lookup_value_regex = r"[0-9a-fA-F-]{36}"

    def _detail_or_404(self, run_id) -> dict:
        detail = services.run_detail(run_id)
        if detail is None:
            raise NotFound("Không tìm thấy lần đồng bộ.")
        return detail

    def list(self, request):
        paginator = StandardPagination()
        page = paginator.paginate_queryset(
            services.category_runs_queryset(), request, view=self
        )
        data = CategoryRunListSerializer(services.summarize_runs(page), many=True).data
        return paginator.get_paginated_response(data)

    def retrieve(self, request, pk=None):
        detail = self._detail_or_404(pk)
        return Response(CategoryRunDetailSerializer(detail).data)

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        """Download one run as a two-sheet Excel report (Tổng quan / Chi tiết)."""
        detail = self._detail_or_404(pk)
        content = services.build_run_workbook(detail)
        response = HttpResponse(content, content_type=XLSX_CONTENT_TYPE)
        filename = services.run_export_filename(detail)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
