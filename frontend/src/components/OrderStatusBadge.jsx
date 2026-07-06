// Presentational badge for a WooCommerce order status. Mirrors HealthStatusBadge
// so the dashboard reads consistently across screens.
const MAP = {
  processing: { bg: "bg-blue-500/15", text: "text-info", label: "Đang xử lý" },
  completed: { bg: "bg-green-500/15", text: "text-success", label: "Hoàn thành" },
  "on-hold": { bg: "bg-amber-500/15", text: "text-warning", label: "Tạm giữ" },
  pending: { bg: "bg-overlay/10", text: "text-muted", label: "Chờ thanh toán" },
  cancelled: { bg: "bg-red-500/15", text: "text-danger", label: "Đã hủy" },
  refunded: { bg: "bg-overlay/10", text: "text-muted", label: "Đã hoàn tiền" },
  failed: { bg: "bg-red-500/15", text: "text-danger", label: "Thất bại" },
};

export default function OrderStatusBadge({ status }) {
  const { bg, text, label } = MAP[status] || {
    bg: "bg-overlay/10",
    text: "text-muted",
    label: status || "—",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 ${bg}`}>
      <span className={`text-xs font-medium ${text}`}>{label}</span>
    </span>
  );
}
