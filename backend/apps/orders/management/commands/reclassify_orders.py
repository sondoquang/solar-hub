"""Re-run the risk classification over stored orders.

Use it to backfill ``classification``/``risk_score``/``risk_reasons`` after the
feature ships, and to re-score every order whenever the hardcoded rule weights
in ``apps.orders.services`` change. Idempotent — safe to run repeatedly.

    python manage.py reclassify_orders              # all orders
    python manage.py reclassify_orders --site 3     # one site
    python manage.py reclassify_orders --status processing
"""

from django.core.management.base import BaseCommand

from apps.orders import services
from apps.orders.models import Order


class Command(BaseCommand):
    help = "Recompute the risk classification for stored orders."

    def add_arguments(self, parser):
        parser.add_argument("--site", type=int, help="Only orders of this site id.")
        parser.add_argument("--status", help="Only orders of this WooCommerce status.")

    def handle(self, *args, **options):
        qs = Order.objects.all()
        if options.get("site"):
            qs = qs.filter(site_id=options["site"])
        if options.get("status"):
            qs = qs.filter(status=options["status"])

        counts = {services.GENUINE: 0, services.SUSPICIOUS: 0, services.SPAM: 0}
        total = 0
        # iterator() keeps memory flat on large fleets; each save touches only
        # the classification columns.
        for order in qs.iterator():
            services.classify_and_save(order)
            counts[order.classification] = counts.get(order.classification, 0) + 1
            total += 1

        # ASCII output: a Windows console (cp1252) crashes on Vietnamese here.
        self.stdout.write(
            self.style.SUCCESS(
                f"Classified {total} orders - "
                f"genuine: {counts[services.GENUINE]}, "
                f"suspicious: {counts[services.SUSPICIOUS]}, "
                f"spam: {counts[services.SPAM]}."
            )
        )
