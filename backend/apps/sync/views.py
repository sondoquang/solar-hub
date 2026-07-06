"""Sync report API — read-only views over fan-out runs.

- ``GET /api/sync/category-runs/``               — paginated run list (newest first).
- ``GET /api/sync/category-runs/{run_id}/``      — per-site detail incl. category snapshots.
- ``GET /api/sync/category-runs/{run_id}/export/`` — the run as an .xlsx report.
- ``GET /api/sync/product-runs/``                — paginated product-push run list.
- ``GET /api/sync/product-runs/{run_id}/``       — per-site detail incl. failure reasons.
- ``GET /api/sync/product-runs/{run_id}/export/`` — the run as an .xlsx report.
- ``GET /api/sync/run-progress/{run_id}/?operation=`` — live "X/Y sites done"
  for a freshly-triggered run (orders / products / categories), polled by the
  progress banner until it completes.

Rows are written by the per-site services (``pull_categories_for_site``,
``push_products_to_site``, ``poll_site``); this app only reads them. Runs
predating the ``run_id`` field never appear here.
"""

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from config.pagination import StandardPagination

from . import services
from .models import Notification
from .serializers import (
    CategoryRunDetailSerializer,
    CategoryRunListSerializer,
    NotificationSerializer,
    ProductRunDetailSerializer,
    ProductRunListSerializer,
)

XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


class CategorySyncRunViewSet(viewsets.ViewSet):
    # Constrain the lookup to a UUID so arbitrary strings 404 at the router
    # instead of blowing up the UUIDField filter.
    lookup_value_regex = r"[0-9a-fA-F-]{36}"
    # Plain ViewSet (no queryset) → declare perms explicitly; runs are read
    # views over SyncLog data.
    required_perms = {"GET": ["sync.view_synclog"]}

    def _detail_or_404(self, run_id) -> dict:
        detail = services.run_detail(run_id)
        if detail is None:
            raise NotFound("Không tìm thấy lần đồng bộ.")
        return detail

    def list(self, request):
        paginator = StandardPagination()
        page = paginator.paginate_queryset(
            services.category_runs_queryset(request.query_params), request, view=self
        )
        data = CategoryRunListSerializer(services.summarize_runs(page), many=True).data
        return paginator.get_paginated_response(data)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Stat-card counts (total / success / partial / error + last run) over a
        window (default 30 days). Honours the same site/date/search filters as
        the list so the cards track the active filter."""
        return Response(services.category_run_stats(request.query_params))

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


class ProductSyncRunViewSet(viewsets.ViewSet):
    """Read-only product-push run report (mirror ``CategorySyncRunViewSet``)."""

    # Constrain the lookup to a UUID so arbitrary strings 404 at the router.
    lookup_value_regex = r"[0-9a-fA-F-]{36}"
    required_perms = {"GET": ["sync.view_synclog"]}

    def _detail_or_404(self, run_id) -> dict:
        detail = services.product_run_detail(run_id)
        if detail is None:
            raise NotFound("Không tìm thấy lần đồng bộ.")
        return detail

    def list(self, request):
        paginator = StandardPagination()
        page = paginator.paginate_queryset(
            services.product_runs_queryset(request.query_params), request, view=self
        )
        data = ProductRunListSerializer(
            services.summarize_product_runs(page), many=True
        ).data
        return paginator.get_paginated_response(data)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Stat-card counts (total / success / partial / error + last run) over a
        window (default 30 days), honouring the same filters as the list."""
        return Response(services.product_run_stats(request.query_params))

    def retrieve(self, request, pk=None):
        detail = self._detail_or_404(pk)
        return Response(ProductRunDetailSerializer(detail).data)

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        """Download one product run as a two-sheet Excel report (Tổng quan / Chi tiết)."""
        detail = self._detail_or_404(pk)
        content = services.build_product_run_workbook(detail)
        response = HttpResponse(content, content_type=XLSX_CONTENT_TYPE)
        filename = services.product_run_export_filename(detail)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class RunProgressViewSet(viewsets.ViewSet):
    """Live progress of a fan-out run for the polling banner — ``done``/``expected``
    where ``expected`` is the site count the trigger endpoint returned. Generic
    over ``operation`` (orders / products / categories); unknown operations 404."""

    # Constrain the lookup to a UUID so arbitrary strings 404 at the router.
    lookup_value_regex = r"[0-9a-fA-F-]{36}"

    def retrieve(self, request, pk=None):
        operation = request.query_params.get("operation")
        if operation not in services.PROGRESS_OPERATIONS:
            raise NotFound("Loại đồng bộ không hợp lệ.")
        return Response(services.run_progress(pk, operation))


class NotificationViewSet(viewsets.ViewSet):
    """Persistent push-run notifications for the app-wide modal + bell.

    - ``GET  /api/notifications/``              — recent notifications (paginated),
      with ``unread``/``running`` counts on the envelope. Finalizes any RUNNING
      notification on read (lazy — no chord needed), so a run that finished while
      the user was on another page flips to ``completed`` here and the frontend
      pops the summary modal.
    - ``GET  /api/notifications/unread_count/`` — cheap poll for the bell badge.
    - ``POST /api/notifications/{id}/read/``    — mark one read.
    - ``POST /api/notifications/mark_all_read/``— clear the badge.
    """

    def _counts(self) -> dict:
        return {
            "unread": Notification.objects.filter(read_at__isnull=True).count(),
            "running": Notification.objects.filter(
                status=Notification.Status.RUNNING
            ).count(),
        }

    def list(self, request):
        services.finalize_running_notifications()
        paginator = StandardPagination()
        page = paginator.paginate_queryset(Notification.objects.all(), request, view=self)
        response = paginator.get_paginated_response(
            NotificationSerializer(page, many=True).data
        )
        response.data.update(self._counts())
        return response

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        services.finalize_running_notifications()
        return Response(self._counts())

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        notif = Notification.objects.filter(pk=pk).first()
        if notif is None:
            raise NotFound("Không tìm thấy thông báo.")
        if notif.read_at is None:
            notif.read_at = timezone.now()
            notif.save(update_fields=["read_at"])
        return Response(NotificationSerializer(notif).data)

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        Notification.objects.filter(read_at__isnull=True).update(read_at=timezone.now())
        return Response(self._counts())
