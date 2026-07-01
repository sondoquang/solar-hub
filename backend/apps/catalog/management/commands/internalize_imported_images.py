"""Backfill: pull a previously-imported product's images into the Hub.

``import_products_from_site`` now internalizes images at import time (download
into the Hub media library, rewrite refs to Hub URLs). Products imported BEFORE
that change still carry the SOURCE site's image URLs in ``MasterProduct.images``
and the description HTML — pushing them to OTHER sites fails to sideload (the
source is usually unreachable from the target), so the images get dropped.
Re-importing does NOT fix them (import is idempotent, skips mapped products).

This command walks imported masters (``source_site`` set) and internalizes any
remaining remote image refs, reusing the exact import-time helpers so the result
matches a fresh import. The Hub must reach each source site (it does — that's
how the products were imported).

Usage::

    python manage.py internalize_imported_images            # all imported masters
    python manage.py internalize_imported_images --site 3    # only source site 3
    python manage.py internalize_imported_images --dry-run   # report, download nothing
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.catalog import services
from apps.catalog.models import MasterProduct


def _remote_refs(master) -> list[str]:
    """Every image ref on ``master`` that is NOT already a Hub URL (gallery +
    ``<img src>`` in description/short_description). Used for --dry-run reporting
    and to skip masters with nothing to do, without downloading anything."""
    refs: list[str] = []
    for url in master.images or []:
        if url and not services._is_hub_media_url(url):
            refs.append(url)
    for field in ("description", "short_description"):
        for match in services._IMG_SRC_RE.finditer(getattr(master, field) or ""):
            src = match.group("src")
            if src and not services._is_hub_media_url(src):
                refs.append(src)
    return refs


class Command(BaseCommand):
    help = "Download remote images of already-imported products into the Hub media library."

    def add_arguments(self, parser):
        parser.add_argument(
            "--site",
            type=int,
            default=None,
            help="Only masters imported from this source site id (default: all).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be internalized without downloading or saving.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        # Internalized URLs use MEDIA_PUBLIC_BASE_URL; without it they would be
        # root-relative (/media/...) — undownloadable by the sites AND not
        # repairable by set_media_public_url (it only rewrites absolute hosts).
        if not getattr(settings, "MEDIA_PUBLIC_BASE_URL", "") and not dry_run:
            raise CommandError(
                "MEDIA_PUBLIC_BASE_URL chưa cấu hình — đặt nó (URL public của Hub) "
                "trước khi chạy, nếu không ảnh nội bộ hóa sẽ không tải được từ các site."
            )

        masters = MasterProduct.objects.filter(source_site__isnull=False, is_deleted=False)
        if options["site"] is not None:
            masters = masters.filter(source_site_id=options["site"])

        cache: dict = {}  # remote src → Hub url, deduped across the whole run
        scanned = changed = 0
        for master in masters.iterator():
            scanned += 1
            refs = _remote_refs(master)
            if not refs:
                continue
            if dry_run:
                changed += 1
                self.stdout.write(f"[dry-run] {master.sku}: {len(refs)} ảnh cần nội bộ hóa")
                continue

            fields = {
                "images": master.images,
                "description": master.description,
                "short_description": master.short_description,
            }
            services._internalize_imported_media(fields, cache)
            update_fields = [
                name
                for name in ("images", "description", "short_description")
                if fields[name] != getattr(master, name)
            ]
            if update_fields:
                for name in update_fields:
                    setattr(master, name, fields[name])
                master.save(update_fields=update_fields + ["updated_at"])
                changed += 1
                self.stdout.write(f"fixed {master.sku}: {', '.join(update_fields)}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"[dry-run] {changed}/{scanned} sản phẩm còn ảnh từ site nguồn "
                    "(chạy lại không kèm --dry-run để tải về)."
                )
            )
            return

        internalized = sum(1 for src, dst in cache.items() if dst != src)
        failures = sum(1 for src, dst in cache.items() if dst == src)
        self.stdout.write(
            self.style.SUCCESS(
                f"Đã cập nhật {changed}/{scanned} sản phẩm — "
                f"{internalized} ảnh nội bộ hóa, {failures} ảnh tải lỗi (giữ URL gốc)."
            )
        )
