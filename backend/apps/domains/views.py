"""Domain-info API — one snapshot per site (WHOIS / DNS / SSL / blacklist /
Google index).

- ``GET  /api/domain-info/``                   — paginated list ("Tên miền" page).
- ``GET  /api/domain-info/{site_id}/``         — one snapshot (modal); 404 = never checked.
- ``POST /api/domain-info/{site_id}/refresh/`` — enqueue a refresh (202); body
  optionally ``{"checks": ["whois", "dns", "ssl", "blacklist", "gindex"]}``.
- ``POST /api/domain-info/refresh-all/``       — force-refresh every site (202).

Rows are written by apps/domains/services via Celery; this API never runs the
lookups itself (slow network I/O stays out of the request cycle).
"""

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from apps.sites.models import Site

from . import services, tasks
from .models import DomainInfo
from .serializers import DomainInfoSerializer


class DomainInfoViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DomainInfoSerializer
    # The FE always addresses a snapshot by the SITE it belongs to.
    lookup_field = "site_id"
    lookup_value_regex = r"\d+"
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["domain", "host", "site__name", "site__base_url"]
    ordering_fields = [
        "whois_expires_at",
        "ssl_not_after",
        "last_refreshed_at",
        "domain",
    ]
    ordering = ["domain"]
    action_perms = {
        "refresh": ["domains.refresh_domaininfo"],
        "refresh_all": ["domains.refresh_domaininfo"],
    }

    def get_queryset(self):
        qs = DomainInfo.objects.select_related("site").filter(site__is_deleted=False)
        verdict = self.request.query_params.get("blacklist_verdict")
        if verdict:
            qs = qs.filter(blacklist_verdict=verdict)
        return qs

    @action(detail=True, methods=["post"])
    def refresh(self, request, site_id=None):
        site = get_object_or_404(Site, pk=site_id, is_deleted=False)
        checks = request.data.get("checks") or None
        if checks is not None:
            invalid = set(checks) - set(services.ALL_CHECKS)
            if invalid:
                return Response(
                    {"detail": f"checks không hợp lệ: {sorted(invalid)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        info = services.mark_pending(site, checks)
        tasks.refresh_site_domain_info.apply_async(
            args=[site.id, checks], queue="interactive"
        )
        return Response(
            self.get_serializer(info).data, status=status.HTTP_202_ACCEPTED
        )

    @action(detail=False, methods=["post"], url_path="refresh-all")
    def refresh_all(self, request):
        """Force-refresh every non-deleted site. The dispatcher fans out its
        batches onto the interactive queue (user-triggered work must not sit
        behind periodic jobs)."""
        tasks.refresh_all_domain_info.apply_async(
            kwargs={"force": True, "queue": "interactive"}, queue="interactive"
        )
        return Response({"queued": True}, status=status.HTTP_202_ACCEPTED)
