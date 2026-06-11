"""Re-point every stored Hub-media URL at a new public base URL.

Image URLs are frozen into ``MasterProduct`` (``images``, description HTML,
``variations[].image``) at the moment the image is picked in the form. When the
Hub's public address changes (new cloudflared/ngrok tunnel, real deploy), the
already-saved URLs still carry the old host and WooCommerce can't download them
— this command rewrites the host part of every ``/media/`` URL in one go.

Usage::

    python manage.py set_media_public_url https://hub.example.com
"""

import re

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import MasterProduct

# scheme://host (no path) immediately followed by /media/ — only Hub media
# URLs match; external links (no /media/ path) are left untouched.
_MEDIA_HOST_RE = re.compile(r"https?://[^/\s\"']+(?=/media/)")


class Command(BaseCommand):
    help = "Rewrite the host of every stored /media/ URL (images, description, variations)."

    def add_arguments(self, parser):
        parser.add_argument(
            "base_url",
            help="New public base URL of the Hub, e.g. https://hub.example.com",
        )

    def handle(self, *args, **options):
        base = options["base_url"].strip().rstrip("/")
        if not re.fullmatch(r"https?://[^/\s]+", base):
            raise CommandError("base_url phải có dạng https://host (không kèm path).")

        def sub(text: str) -> str:
            return _MEDIA_HOST_RE.sub(base, text or "")

        changed = 0
        for master in MasterProduct.objects.all():
            fields = []
            images = [sub(u) for u in (master.images or [])]
            if images != master.images:
                master.images = images
                fields.append("images")
            for field in ("description", "short_description"):
                value = getattr(master, field) or ""
                if sub(value) != value:
                    setattr(master, field, sub(value))
                    fields.append(field)
            variations = master.variations or []
            new_variations = [{**v, "image": sub(v.get("image") or "")} for v in variations]
            if new_variations != variations:
                master.variations = new_variations
                fields.append("variations")
            if fields:
                master.save(update_fields=fields + ["updated_at"])
                changed += 1
                self.stdout.write(f"fixed {master.sku}: {', '.join(fields)}")

        self.stdout.write(self.style.SUCCESS(f"Đã cập nhật {changed} sản phẩm → {base}"))
