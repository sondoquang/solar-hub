// Presentational badge for a MasterProduct publish status. Mirrors
// OrderStatusBadge so the catalog reads consistently with the rest of the app.
const MAP = {
  publish: { bg: "bg-green-50", text: "text-success", label: "Đã đăng" },
  draft: { bg: "bg-slate-100", text: "text-slate-600", label: "Nháp" },
  pending: { bg: "bg-amber-50", text: "text-warning", label: "Chờ duyệt" },
  private: { bg: "bg-blue-50", text: "text-blue-600", label: "Riêng tư" },
};

export default function ProductStatusBadge({ status }) {
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
