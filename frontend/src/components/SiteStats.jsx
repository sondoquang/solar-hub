import { AlertCircle, CheckCircle2, Globe, XCircle } from "lucide-react";

// Presentational summary cards for the site list. Counts are derived in the
// page (container) and passed in, keeping this component logic-free.
const CARDS = [
  { key: "total", label: "Tổng website", Icon: Globe, tint: "bg-blue-50 text-blue-500" },
  { key: "up", label: "Đang hoạt động", Icon: CheckCircle2, tint: "bg-green-50 text-success" },
  { key: "unknown", label: "Tạm dừng", Icon: AlertCircle, tint: "bg-amber-50 text-warning" },
  { key: "down", label: "Không hoạt động", Icon: XCircle, tint: "bg-red-50 text-danger" },
];

export default function SiteStats({ counts }) {
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {CARDS.map(({ key, label, Icon, tint }) => (
        <div key={key} className="flex items-center gap-4 rounded-xl bg-white p-5 shadow-card">
          <span className={`flex h-12 w-12 items-center justify-center rounded-full ${tint}`}>
            <Icon size={22} />
          </span>
          <div>
            <p className="font-display text-2xl font-bold leading-none">{counts[key] ?? 0}</p>
            <p className="mt-1 text-sm text-muted">{label}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
