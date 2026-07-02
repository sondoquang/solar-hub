"""Wipe the Hub's synced product/category data so the system can be re-tested.

Unlike ``services.clear_category_sync_data`` (a *soft* reset that keeps in-use
categories), this HARD-deletes so a re-import/re-push starts from a truly empty
slate. Scoped by flags — nothing runs without an explicit scope (or ``--all``):

    --products    catalog_masterproduct + productmapping + variationmapping
                  + sitemediaasset (everything on the product side)
    --categories  catalog_category + categorymapping (pulled category tree)
    --logs        sync_synclog (push/pull audit trail)
    --all         all three scopes
    --dry-run     count only, delete nothing

The Hub media library (``catalog_productimage`` + uploaded files) is left
untouched — those are Hub uploads, not synced-in data.

    python manage.py clear_product_sync_data --all
    python manage.py clear_product_sync_data --products --dry-run
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.models import (
    Category,
    CategoryMapping,
    MasterProduct,
    ProductAdoptionScan,
    ProductMapping,
    ProductVariationMapping,
    SiteMediaAsset,
)
from apps.sync.models import SyncLog


class Command(BaseCommand):
    help = "Hard-delete synced product/category/log data for a clean re-test."

    def add_arguments(self, parser):
        parser.add_argument("--products", action="store_true", help="Wipe products + mappings.")
        parser.add_argument("--categories", action="store_true", help="Wipe category tree.")
        parser.add_argument("--logs", action="store_true", help="Wipe sync logs.")
        parser.add_argument("--all", action="store_true", help="Wipe all of the above.")
        parser.add_argument(
            "--dry-run", action="store_true", help="Report counts, delete nothing."
        )

    def handle(self, *args, **options):
        do_all = options["all"]
        products = options["products"] or do_all
        categories = options["categories"] or do_all
        logs = options["logs"] or do_all
        dry_run = options["dry_run"]

        if not (products or categories or logs):
            raise CommandError(
                "Chua chon pham vi. Dung --products / --categories / --logs / --all."
            )

        # Children first so an FK never blocks a parent (cascade would cover it,
        # but explicit order keeps the per-table counts honest). Only the picked
        # scopes are included.
        targets: list[tuple[str, type]] = []
        if products:
            targets += [
                ("catalog_productvariationmapping", ProductVariationMapping),
                ("catalog_productmapping", ProductMapping),
                ("catalog_productadoptionscan", ProductAdoptionScan),
                ("catalog_sitemediaasset", SiteMediaAsset),
                ("catalog_masterproduct", MasterProduct),
            ]
        if categories:
            targets += [
                ("catalog_categorymapping", CategoryMapping),
                ("catalog_category", Category),
            ]
        if logs:
            targets += [("sync_synclog", SyncLog)]

        if dry_run:
            total = 0
            for table, model in targets:
                n = model.objects.count()
                total += n
                self.stdout.write(f"[dry-run] {table}: {n} rows")
            self.stdout.write(
                self.style.WARNING(f"[dry-run] Tong {total} rows se bi xoa (chua xoa gi).")
            )
            return

        total = 0
        with transaction.atomic():
            for table, model in targets:
                n, _ = model.objects.all().delete()
                total += n
                self.stdout.write(f"deleted {table}: {n}")

        self.stdout.write(self.style.SUCCESS(f"Da xoa tong cong {total} rows. Slate sach."))
