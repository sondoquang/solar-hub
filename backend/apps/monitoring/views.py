"""Monitoring API — read-only health-check history.

- ``GET /api/healthchecks/``         — paginated list (search / filters / sort).
- ``GET /api/healthchecks/{id}/``    — one check (detail modal).
- ``GET /api/healthchecks/stats/``   — status counts + vs-previous-period trend.
- ``GET /api/healthchecks/export/``  — CSV of the current filter selection.

Records are created by ``apps/sites/services.test_connection``; this app only
reads them, so there is no create/update/delete endpoint.
"""

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from . import services
from .models import HealthCheck
from .serializers import HealthCheckSerializer


class HealthCheckViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = HealthCheckSerializer
    filter_backends = [SearchFilter, OrderingFilter]
    # Search across the website name/URL and its hosting name (matches the
    # "Tìm kiếm theo tên website, hosting…" box).
    search_fields = ["site__name", "site__base_url", "site__hosting__name"]
    ordering_fields = ["checked_at", "response_time_ms", "status"]
    ordering = ["-checked_at"]

    def get_queryset(self):
        qs = HealthCheck.objects.select_related(
            "site", "site__hosting", "performed_by"
        )
        return services.filter_health_checks(qs, self.request.query_params)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Status counts for the filtered range (cards), independent of paging."""
        qs = self.filter_queryset(self.get_queryset())
        return Response(services.health_stats(qs, request.query_params))

    @action(detail=False, methods=["get"])
    def export(self, request):
        """Stream the filtered rows as a CSV report (UTF-8 BOM for Excel)."""
        from django.http import StreamingHttpResponse

        qs = self.filter_queryset(self.get_queryset())
        response = StreamingHttpResponse(
            services.stream_health_checks_csv(qs), content_type="text/csv"
        )
        response["Content-Disposition"] = (
            'attachment; filename="health-checks.csv"'
        )
        return response
