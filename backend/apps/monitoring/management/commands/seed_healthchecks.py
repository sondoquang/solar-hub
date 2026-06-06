"""Seed sample health-check history so the new screen has data to render.

Local/dev only. Generates random-but-plausible checks across all existing
sites over the last N days (mostly periodic = "Hệ thống"). Usage:

    python manage.py seed_healthchecks --days 30 --per-day 6
"""

import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.monitoring.models import HealthCheck
from apps.monitoring.services import derive_status
from apps.sites.models import Site

# Response-time buckets weighted so most checks are healthy (matches the design's
# ~84% healthy / 12% warning / 4% critical split).
_BUCKETS = [
    ((120, 600), 0.70),  # fast → healthy
    ((1100, 4500), 0.18),  # slow → warning
    ((5200, 8000), 0.08),  # very slow → critical
    ((0, 0), 0.04),  # unreachable → critical
]


def _sample_response():
    """Return (response_time_ms, ok) from the weighted buckets."""
    r = random.random()
    cumulative = 0.0
    for (low, high), weight in _BUCKETS:
        cumulative += weight
        if r <= cumulative:
            if high == 0:
                return random.randint(3000, 9000), False  # timed out
            return random.randint(low, high), True
    return random.randint(120, 600), True


class Command(BaseCommand):
    help = "Seed sample HealthCheck rows for existing sites (dev only)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--per-day", type=int, default=6)
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing health checks first.",
        )

    def handle(self, *args, **opts):
        sites = list(Site.objects.filter(is_deleted=False))
        if not sites:
            self.stderr.write("No sites found — register a site first.")
            return

        if opts["reset"]:
            deleted, _ = HealthCheck.objects.all().delete()
            self.stdout.write(f"Deleted {deleted} existing rows.")

        users = list(User.objects.all())
        now = timezone.now()
        rows = []
        for day in range(opts["days"]):
            day_start = now - timedelta(days=day)
            for _ in range(opts["per_day"]):
                site = random.choice(sites)
                response_time_ms, ok = _sample_response()
                # ~80% periodic (system), the rest manual by a real user.
                manual = bool(users) and random.random() < 0.2
                checked_at = day_start - timedelta(
                    hours=random.randint(0, 23), minutes=random.randint(0, 59)
                )
                rows.append(
                    HealthCheck(
                        site=site,
                        status=derive_status(ok, response_time_ms),
                        check_type=(
                            HealthCheck.CheckType.MANUAL
                            if manual
                            else HealthCheck.CheckType.PERIODIC
                        ),
                        response_time_ms=response_time_ms,
                        ok=ok,
                        detail=(
                            "Kết nối thành công." if ok else "Lỗi kết nối: TimeoutException"
                        ),
                        performed_by=random.choice(users) if manual else None,
                        checked_at=checked_at,
                    )
                )

        HealthCheck.objects.bulk_create(rows)
        self.stdout.write(
            self.style.SUCCESS(f"Created {len(rows)} health-check rows.")
        )
