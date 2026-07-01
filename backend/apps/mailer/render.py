"""Render synced orders into the HTML body of the digest / manual email.

The layout mirrors the order-detail modal (and the PDF export): an order header,
the customer block, and the line-items table with a total. Formatting helpers are
reused from ``apps.orders.pdf`` so the email, the PDF and the UI all agree on how
money/names/dates look. The same orders are also attached as a PDF (one per page).

PII (customer name/phone/address) appears in the body by design — it is the point
of the email — but is never logged (see CLAUDE.md).
"""

from django.template.loader import render_to_string
from django.utils import timezone

from apps.orders.models import CLASSIFICATION_CHOICES
from apps.orders.pdf import (
    STATUS_LABELS,
    _format_dt,
    _money,
    _title_case_name,
    _unit_price,
)

_CLASSIFICATION_LABELS = dict(CLASSIFICATION_CHOICES)


def _order_context(order) -> dict:
    """Pre-format one order so the template stays logic-free."""
    currency = order.currency
    items = [
        {
            "index": i,
            "sku": item.get("sku") or "—",
            "name": item.get("name") or "—",
            "quantity": item.get("quantity") or 0,
            "unit_price": _money(_unit_price(item), currency),
            "total": _money(item.get("total"), currency),
        }
        for i, item in enumerate(order.line_items or [], start=1)
    ]
    return {
        "number": order.number or str(order.woo_order_id),
        "site_name": order.site.name if order.site_id else "—",
        "hosting_name": (
            order.site.hosting.name
            if order.site_id and order.site.hosting_id
            else ""
        ),
        "status_label": STATUS_LABELS.get(order.status, order.status or "—"),
        "classification_label": _CLASSIFICATION_LABELS.get(
            order.classification, order.classification
        ),
        "date_created": _format_dt(order.date_created_woo),
        "customer_name": _title_case_name(order.customer_name) or "—",
        "customer_phone": order.customer_phone or "—",
        "customer_email": order.customer_email or "—",
        "shipping_address": order.shipping_address or "—",
        "customer_note": order.customer_note or "—",
        "total": _money(order.total, currency),
        "items": items,
    }


def build_email_context(orders, *, title: str = "Đơn hàng đồng bộ") -> dict:
    orders = list(orders)
    return {
        "title": title,
        "count": len(orders),
        "generated_at": _format_dt(timezone.now()),
        "orders": [_order_context(o) for o in orders],
    }


def render_orders_email_html(orders, *, title: str = "Đơn hàng đồng bộ") -> str:
    """Full HTML body for the given orders."""
    return render_to_string(
        "mailer/orders_email.html", build_email_context(orders, title=title)
    )


def render_orders_email_text(orders) -> str:
    """Plain-text fallback (clients without HTML); one line per order."""
    lines = ["Solar Hub — đơn hàng đồng bộ", ""]
    for order in orders:
        name = _title_case_name(order.customer_name) or "—"
        lines.append(
            f"#{order.number or order.woo_order_id} — {name} "
            f"({order.customer_phone or '—'}) — {_money(order.total, order.currency)}"
        )
    lines.append("")
    lines.append("Chi tiết đầy đủ trong bản HTML và file PDF đính kèm.")
    return "\n".join(lines)
