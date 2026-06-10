// Presentational badge for an order's risk classification. Mirrors
// OrderStatusBadge so the dashboard reads consistently. Optionally shows the
// 0–100 risk score next to the label.
const MAP = {
  genuine: { bg: "bg-green-50", text: "text-success", label: "Hợp lệ" },
  suspicious: { bg: "bg-amber-50", text: "text-warning", label: "Nghi ngờ" },
  spam: { bg: "bg-red-50", text: "text-danger", label: "Spam/Bot" },
};

export default function ClassificationBadge({ classification, score }) {
  const { bg, text, label } = MAP[classification] || {
    bg: "bg-slate-100",
    text: "text-slate-600",
    label: classification || "—",
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 ${bg}`}>
      <span className={`text-xs font-medium ${text}`}>{label}</span>
      {typeof score === "number" && score > 0 && (
        <span className={`text-xs tabular-nums opacity-70 ${text}`}>{score}</span>
      )}
    </span>
  );
}
