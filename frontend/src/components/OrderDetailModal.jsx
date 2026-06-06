import { Descriptions, Modal, Table } from "antd";

import { formatDateTime, formatVND } from "../lib/format.js";
import OrderStatusBadge from "./OrderStatusBadge.jsx";

// Read-only detail of a single order (the "Xem chi tiết" action), including the
// line items and customer info (PII — shown in the admin UI, never logged).
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
    key: "total",
    dataIndex: "total",
    title: "Thành tiền",
    width: 120,
    align: "right",
    render: (v) => formatVND(v),
  },
];

export default function OrderDetailModal({ order, open, onClose }) {
  return (
    <Modal open={open} onCancel={onClose} footer={null} title="Chi tiết đơn hàng" width={640}>
      {order && (
        <div className="mt-2 space-y-3">
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="Số đơn">#{order.number}</Descriptions.Item>
            <Descriptions.Item label="Website">{order.site_name}</Descriptions.Item>
            <Descriptions.Item label="Hosting">{order.hosting_name || "—"}</Descriptions.Item>
            <Descriptions.Item label="Trạng thái">
              <OrderStatusBadge status={order.status} />
            </Descriptions.Item>
            <Descriptions.Item label="Ngày tạo">
              {formatDateTime(order.date_created_woo)}
            </Descriptions.Item>
            <Descriptions.Item label="Khách hàng">{order.customer_name || "—"}</Descriptions.Item>
            <Descriptions.Item label="Điện thoại">{order.customer_phone || "—"}</Descriptions.Item>
            <Descriptions.Item label="Email">{order.customer_email || "—"}</Descriptions.Item>
            <Descriptions.Item label="Địa chỉ giao">
              {order.shipping_address || "—"}
            </Descriptions.Item>
            <Descriptions.Item label="Ghi chú">{order.customer_note || "—"}</Descriptions.Item>
            <Descriptions.Item label="Tổng tiền">
              <span className="font-semibold">{formatVND(order.total)}</span>
            </Descriptions.Item>
          </Descriptions>

          <Table
            columns={ITEM_COLUMNS}
            dataSource={(order.line_items || []).map((it, i) => ({ ...it, key: i }))}
            size="small"
            pagination={false}
            locale={{ emptyText: "Không có sản phẩm" }}
          />
        </div>
      )}
    </Modal>
  );
}
