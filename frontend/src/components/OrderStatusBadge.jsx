// Presentational badge for a WooCommerce order status. Mirrors HealthStatusBadge
// so the dashboard reads consistently across screens.
const MAP = {
  processing: { bg: "bg-blue-50", text: "text-blue-600", label: "Đang xử lý" },
  completed: { bg: "bg-green-50", text: "text-success", label: "Hoàn thành" },
  "on-hold": { bg: "bg-amber-50", text: "text-warning", label: "Tạm giữ" },
  pending: { bg: "bg-slate-100", text: "text-slate-600", label: "Chờ thanh toán" },
  cancelled: { bg: "bg-red-50", text: "text-danger", label: "Đã hủy" },
  refunded: { bg: "bg-slate-100", text: "text-slate-600", label: "Đã hoàn tiền" },
  failed: { bg: "bg-red-50", text: "text-danger", label: "Thất bại" },
};

export default function OrderStatusBadge({ status }) {
  const { bg, text, label } = MAP[status] || {
    bg: "bg-slate-100",
    text: "text-slate-600",
    label: status || "—",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 ${bg}`}>
      <span className={`text-xs font-medium ${text}`}>{label}</span>
    </span>
  );
}
