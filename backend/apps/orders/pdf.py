"""Render orders as a printable PDF for the sales team.

One order per page; the whole selection becomes a single PDF (page-break between
orders). Layout mirrors the detail modal: an order header, the customer block,
and the line-items table with a total. All text uses a bundled DejaVu Sans TTF
so Vietnamese diacritics render correctly (reportlab's built-in Type-1 fonts do
not cover them).

PII (customer name/phone/address) appears in the document by design — it is the
point of the export — but is never logged (see CLAUDE.md).
"""

import datetime
import decimal
import io
import os

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FONT_NAME = "DejaVuSans"
_FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans.ttf")
_font_registered = False

# Brand palette (mirrors the dashboard's amber/ink tokens).
BRAND = colors.HexColor("#F59E0B")
INK = colors.HexColor("#1F2937")
MUTED = colors.HexColor("#6B7280")
LINE = colors.HexColor("#E5E7EB")
HEAD_BG = colors.HexColor("#F9FAFB")

# WooCommerce status -> Vietnamese label (matches the frontend badges).
STATUS_LABELS = {
    "pending": "Chờ thanh toán",
    "processing": "Đang xử lý",
    "on-hold": "Tạm giữ",
    "completed": "Hoàn thành",
    "cancelled": "Đã hủy",
    "refunded": "Đã hoàn tiền",
    "failed": "Thất bại",
}


def _ensure_font() -> None:
    """Register the bundled DejaVu Sans TTF once (idempotent)."""
    global _font_registered
    if not _font_registered:
        pdfmetrics.registerFont(TTFont(FONT_NAME, _FONT_PATH))
        _font_registered = True


def _money(value, currency: str = "") -> str:
    """Format an amount the vi-VN way: '1.234.567 ₫' (or '… <CURRENCY>')."""
    try:
        n = decimal.Decimal(value or 0)
    except (decimal.InvalidOperation, TypeError):
        return "—"
    whole = int(n.quantize(decimal.Decimal("1"), rounding=decimal.ROUND_HALF_UP))
    grouped = f"{whole:,}".replace(",", ".")
    if not currency or currency.upper() == "VND":
        return f"{grouped} ₫"
    return f"{grouped} {currency.upper()}"


def _format_dt(value) -> str:
    """Local 'DD/MM/YYYY HH:MM:SS' for the order's creation time."""
    if not value:
        return "—"
    if isinstance(value, datetime.datetime):
        dt = timezone.localtime(value) if timezone.is_aware(value) else value
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    return str(value)


def _styles() -> dict:
    base = getSampleStyleSheet()["Normal"]
    return {
        "value": ParagraphStyle(
            "value", parent=base, fontName=FONT_NAME, fontSize=9, leading=13, textColor=INK
        ),
        "label": ParagraphStyle(
            "label", parent=base, fontName=FONT_NAME, fontSize=9, leading=13, textColor=MUTED
        ),
        "section": ParagraphStyle(
            "section", parent=base, fontName=FONT_NAME, fontSize=11, leading=15, textColor=INK
        ),
        "cell": ParagraphStyle(
            "cell", parent=base, fontName=FONT_NAME, fontSize=9, leading=12, textColor=INK
        ),
        "cell_right": ParagraphStyle(
            "cell_right", parent=base, fontName=FONT_NAME, fontSize=9, leading=12,
            textColor=INK, alignment=TA_RIGHT,
        ),
    }


def _info_table(rows: list[tuple[str, str]], st: dict, *, content_width: float) -> Table:
    """A two-column label/value table (used for order + customer blocks)."""
    data = [
        [Paragraph(label, st["label"]), Paragraph(value or "—", st["value"])]
        for label, value in rows
    ]
    label_w = 34 * mm
    table = Table(data, colWidths=[label_w, content_width - label_w])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
            ]
        )
    )
    return table


def _unit_price(item: dict) -> decimal.Decimal:
    """Woo only gives the line total; derive unit price (đơn giá × SL = thành tiền)."""
    try:
        qty = decimal.Decimal(str(item.get("quantity") or 0))
        total = decimal.Decimal(str(item.get("total") or 0))
    except decimal.InvalidOperation:
        return decimal.Decimal(0)
    return total / qty if qty else total


def _items_table(order, st: dict, *, content_width: float) -> Table:
    """Line-items table: STT / SKU / Sản phẩm / SL / Đơn giá / Thành tiền."""
    header = ["STT", "SKU", "Sản phẩm", "SL", "Đơn giá", "Thành tiền"]
    head_cells = [Paragraph(h, st["cell"]) for h in header[:3]] + [
        Paragraph(h, st["cell_right"]) for h in header[3:]
    ]
    data = [head_cells]
    currency = order.currency
    for i, item in enumerate(order.line_items or [], start=1):
        data.append(
            [
                Paragraph(str(i), st["cell"]),
                Paragraph(str(item.get("sku") or "—"), st["cell"]),
                Paragraph(str(item.get("name") or "—"), st["cell"]),
                Paragraph(str(item.get("quantity") or 0), st["cell_right"]),
                Paragraph(_money(_unit_price(item), currency), st["cell_right"]),
                Paragraph(_money(item.get("total"), currency), st["cell_right"]),
            ]
        )
    if not (order.line_items or []):
        data.append([Paragraph("Không có sản phẩm", st["cell"]), "", "", "", "", ""])

    # Column widths sum to the content width; SKU/name flex, the rest fixed.
    fixed = [12 * mm, 30 * mm, 14 * mm, 26 * mm, 28 * mm]
    name_w = content_width - sum(fixed)
    col_widths = [fixed[0], fixed[1], name_w, fixed[2], fixed[3], fixed[4]]

    table = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
    ]
    if not (order.line_items or []):
        style.append(("SPAN", (0, 1), (-1, 1)))
    table.setStyle(TableStyle(style))
    return table


def _order_flowables(order, st: dict, *, content_width: float) -> list:
    """Build the flowables for a single order (no trailing page break)."""
    title_style = ParagraphStyle(
        "brand", fontName=FONT_NAME, fontSize=18, leading=22, textColor=BRAND
    )
    sub_style = ParagraphStyle(
        "doc", fontName=FONT_NAME, fontSize=10, leading=14, textColor=MUTED, alignment=TA_RIGHT
    )
    header = Table(
        [[Paragraph("SOLAR HUB", title_style), Paragraph("PHIẾU ĐƠN HÀNG", sub_style)]],
        colWidths=[content_width * 0.5, content_width * 0.5],
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("LINEBELOW", (0, 0), (-1, -1), 1.2, BRAND),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    status_label = STATUS_LABELS.get(order.status, order.status or "—")
    order_rows = [
        ("Số đơn", f"#{order.number}"),
        ("Website", order.site.name if order.site_id else "—"),
        ("Hosting", order.site.hosting.name if order.site_id and order.site.hosting_id else "—"),
        ("Ngày tạo", _format_dt(order.date_created_woo)),
        ("Trạng thái", status_label),
    ]
    customer_rows = [
        ("Khách hàng", order.customer_name),
        ("Điện thoại", order.customer_phone),
        ("Email", order.customer_email),
        ("Địa chỉ giao", order.shipping_address),
        ("Ghi chú", order.customer_note),
    ]

    total_table = Table(
        [[Paragraph("Tổng tiền", st["label"]),
          Paragraph(_money(order.total, order.currency),
                    ParagraphStyle("total", fontName=FONT_NAME, fontSize=13, leading=17,
                                   textColor=BRAND, alignment=TA_RIGHT))]],
        colWidths=[content_width - 50 * mm, 50 * mm],
    )
    total_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("LINEABOVE", (0, 0), (-1, -1), 0.6, LINE),
            ]
        )
    )

    return [
        header,
        Spacer(1, 8),
        _info_table(order_rows, st, content_width=content_width),
        Spacer(1, 12),
        Paragraph("Thông tin khách hàng", st["section"]),
        Spacer(1, 4),
        _info_table(customer_rows, st, content_width=content_width),
        Spacer(1, 12),
        Paragraph("Chi tiết sản phẩm", st["section"]),
        Spacer(1, 4),
        _items_table(order, st, content_width=content_width),
        total_table,
    ]


def build_orders_pdf(orders) -> bytes:
    """Render the given orders into a single PDF (one order per page).

    ``orders`` should have ``site``/``site.hosting`` selected to avoid extra
    queries. Returns the raw PDF bytes for the caller to stream.
    """
    _ensure_font()
    buffer = io.BytesIO()
    margin = 16 * mm
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title="Phiếu đơn hàng",
    )
    content_width = A4[0] - 2 * margin
    st = _styles()

    flowables = []
    orders = list(orders)
    for idx, order in enumerate(orders):
        flowables.extend(_order_flowables(order, st, content_width=content_width))
        if idx < len(orders) - 1:
            flowables.append(PageBreak())

    doc.build(flowables)
    return buffer.getvalue()
