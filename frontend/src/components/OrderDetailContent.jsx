import { Descriptions, Table } from "antd";

import { formatDateTime, formatVND, titleCaseName } from "../lib/format.js";
import ClassificationBadge from "./ClassificationBadge.jsx";
import OrderStatusBadge from "./OrderStatusBadge.jsx";
import PaymentStatusBadge from "./PaymentStatusBadge.jsx";

// Presentational body of a single order — the Descriptions block + the line
// items table. Shared by OrderDetailModal (single view and the bulk carousel).
// PII (name/phone/address) is shown here in the admin UI but never logged.
const ITEM_COLUMNS = [
  { key: "sku", dataIndex: "sku", title: "SKU", width: 120 },
  { key: "name", dataIndex: "name", title: "Sản phẩm" },
  {
    key: "quantity",
    dataIndex: "quantity",
    title: "SL",
    width: 64,
    align: "center",
  },
  {
    key: "unitPrice",
    dataIndex: "unitPrice",
    title: "Đơn giá",
    width: 120,
    align: "right",
    render: (v) => formatVND(v),
  },
  {
    key: "total",
    dataIndex: "total",
    title: "Thành tiền",
    width: 120,
    align: "right",
    render: (v) => formatVND(v),
  },
];

// Woo only gives us the line total; unit price is the total split over the
// quantity (so đơn giá × SL = thành tiền). Guard against a zero quantity.
const withUnitPrice = (item) => {
  const qty = Number(item.quantity) || 0;
  const total = Number(item.total) || 0;
  return { ...item, unitPrice: qty > 0 ? total / qty : total };
};

export default function OrderDetailContent({ order }) {
  if (!order) return null;

  return (
    <div className="space-y-3">
      <Descriptions column={1} bordered size="small">
        <Descriptions.Item label={<span className="font-semibold text-muted">Số đơn</span>}>
          <span className="text-base font-bold text-ink">#{order.number}</span>
        </Descriptions.Item>
        <Descriptions.Item label={<span className="font-semibold text-muted">Website</span>}>
          <span className="text-base font-bold text-ink">{order.site_name}</span>
        </Descriptions.Item>
        <Descriptions.Item label="Hosting">{order.hosting_name || "—"}</Descriptions.Item>
        <Descriptions.Item label="Trạng thái">
          <OrderStatusBadge status={order.status} />
        </Descriptions.Item>
        {/* Sapo orders carry a payment status (financial_status); Woo orders
            leave it blank, so the row only appears for Sapo. */}
        {order.payment_status ? (
          <Descriptions.Item label="Thanh toán">
            <PaymentStatusBadge status={order.payment_status} />
          </Descriptions.Item>
        ) : null}
        <Descriptions.Item label="Phân loại">
          <div className="space-y-1">
            <ClassificationBadge
              classification={order.classification}
              score={order.risk_score}
            />
            {order.risk_reasons_display?.length > 0 && (
              <ul className="ml-4 list-disc text-xs text-muted">
                {order.risk_reasons_display.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            )}
          </div>
        </Descriptions.Item>
        <Descriptions.Item label="Ngày tạo">
          {formatDateTime(order.date_created_woo)}
        </Descriptions.Item>
        <Descriptions.Item label="Khách hàng">
          {titleCaseName(order.customer_name) || "—"}
        </Descriptions.Item>
        <Descriptions.Item label={<span className="font-semibold text-muted">Điện thoại</span>}>
          <span className="text-base font-bold text-ink">{order.customer_phone || "—"}</span>
        </Descriptions.Item>
        <Descriptions.Item label="Email">{order.customer_email || "—"}</Descriptions.Item>
        <Descriptions.Item label="Địa chỉ giao">{order.shipping_address || "—"}</Descriptions.Item>
        <Descriptions.Item label="Ghi chú">{order.customer_note || "—"}</Descriptions.Item>
        <Descriptions.Item label={<span className="font-semibold text-muted">Tổng tiền</span>}>
          <span className="text-lg font-bold text-brand">{formatVND(order.total)}</span>
        </Descriptions.Item>
      </Descriptions>

      <Table
        columns={ITEM_COLUMNS}
        dataSource={(order.line_items || []).map((it, i) => ({ ...withUnitPrice(it), key: i }))}
        size="small"
        pagination={false}
        locale={{ emptyText: "Không có sản phẩm" }}
      />
    </div>
  );
}
