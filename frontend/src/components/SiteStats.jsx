import { Skeleton } from "antd";
import { AlertCircle, CheckCircle2, Globe, XCircle } from "lucide-react";

// Presentational summary cards for the site list. Counts are derived in the
// page (container) and passed in, keeping this component logic-free. While
// `loading` the values render as skeleton blocks instead of flashing 0.
const CARDS = [
  { key: "total", label: "Tổng website", Icon: Globe, tint: "bg-blue-500/15 text-blue-300" },
  { key: "up", label: "Đang hoạt động", Icon: CheckCircle2, tint: "bg-green-500/15 text-success" },
  { key: "unknown", label: "Tạm dừng", Icon: AlertCircle, tint: "bg-amber-500/15 text-warning" },
  { key: "down", label: "Không hoạt động", Icon: XCircle, tint: "bg-red-500/15 text-danger" },
];

export default function SiteStats({ counts = {}, loading = false }) {
  return (
    <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
      {CARDS.map(({ key, label, Icon, tint }) => (
        <div key={key} className="flex items-center gap-2 rounded bg-surface-raised p-2.5 border border-border">
          <span className={`flex h-12 w-12 items-center justify-center rounded-full ${tint}`}>
            <Icon size={22} />
          </span>
          <div>
            {loading ? (
              <Skeleton.Input active size="small" style={{ width: 56, height: 24 }} />
            ) : (
              <p className="font-display text-2xl font-bold leading-none">{counts[key] ?? 0}</p>
            )}
            <p className="mt-1 text-sm text-muted">{label}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
