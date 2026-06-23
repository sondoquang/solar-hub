const MAP = {
  up: { dot: "bg-success", bg: "bg-green-500/15", text: "text-success", label: "Hoạt động" },
  down: { dot: "bg-danger", bg: "bg-red-500/15", text: "text-danger", label: "Không hoạt động" },
  unknown: { dot: "bg-warning", bg: "bg-amber-500/15", text: "text-warning", label: "Tạm dừng" },
};

export default function StatusDot({ status = "unknown" }) {
  const { dot, bg, text, label } = MAP[status] || MAP.unknown;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 ${bg}`}
      aria-label={`Trạng thái: ${label}`}
    >
      <span className={`inline-block h-2 w-2 rounded-full ${dot}`} aria-hidden="true" />
      <span className={`text-xs font-medium ${text}`}>{label}</span>
    </span>
  );
}
