// Presentational badge for a Sapo order's payment status (financial_status).
// Mirrors OrderStatusBadge so the Sapo orders screen reads consistently.
const MAP = {
  paid: { bg: "bg-green-500/15", text: "text-success", label: "Đã thanh toán" },
  pending: { bg: "bg-amber-500/15", text: "text-warning", label: "Chưa thanh toán" },
  authorized: { bg: "bg-amber-500/15", text: "text-warning", label: "Chờ thanh toán" },
  partially_paid: {
    bg: "bg-amber-500/15",
    text: "text-warning",
    label: "Thanh toán một phần",
  },
  refunded: { bg: "bg-white/10", text: "text-slate-300", label: "Đã hoàn tiền" },
  partially_refunded: {
    bg: "bg-white/10",
    text: "text-slate-300",
    label: "Hoàn tiền một phần",
  },
  voided: { bg: "bg-red-500/15", text: "text-danger", label: "Đã hủy thanh toán" },
};

export default function PaymentStatusBadge({ status }) {
  const { bg, text, label } = MAP[status] || {
    bg: "bg-white/10",
    text: "text-slate-300",
    label: status || "—",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 ${bg}`}>
      <span className={`text-xs font-medium ${text}`}>{label}</span>
    </span>
  );
}
