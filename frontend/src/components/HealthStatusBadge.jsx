import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";

// Presentational badge for a health-check's 3-level status. Mirrors the
// up/down StatusDot style so the two screens read consistently.
const MAP = {
  healthy: {
    Icon: CheckCircle2,
    bg: "bg-green-50",
    text: "text-success",
    label: "Khỏe mạnh",
  },
  warning: {
    Icon: AlertTriangle,
    bg: "bg-amber-50",
    text: "text-warning",
    label: "Cảnh báo",
  },
  critical: {
    Icon: XCircle,
    bg: "bg-red-50",
    text: "text-danger",
    label: "Lỗi nghiêm trọng",
  },
};

export default function HealthStatusBadge({ status, label }) {
  const { Icon, bg, text, label: fallback } = MAP[status] || MAP.healthy;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 ${bg}`}
      aria-label={`Trạng thái: ${label || fallback}`}
    >
      <Icon size={14} className={text} aria-hidden="true" />
      <span className={`text-xs font-medium ${text}`}>{label || fallback}</span>
    </span>
  );
}
