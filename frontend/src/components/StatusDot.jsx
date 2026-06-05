// Status pill — a colored dot + label, matching the site health palette used
// across the dashboard (green = up, red = down, amber = chưa kiểm tra).
const MAP = {
  up: { dot: "bg-success", text: "text-success", label: "Hoạt động" },
  down: { dot: "bg-danger", text: "text-danger", label: "Không hoạt động" },
  unknown: { dot: "bg-warning", text: "text-warning", label: "Tạm dừng" },
};

export default function StatusDot({ status = "unknown" }) {
  const { dot, text, label } = MAP[status] || MAP.unknown;
  return (
    <span className="inline-flex items-center gap-2">
      <span className={`inline-block h-2.5 w-2.5 rounded-full ${dot}`} aria-hidden="true" />
      <span className={`text-sm font-medium ${text}`} aria-label={`Trạng thái: ${label}`}>
        {label}
      </span>
    </span>
  );
}
