import { Skeleton } from "antd";
import { Activity, AlertTriangle, ShieldCheck, TrendingDown, TrendingUp, XCircle } from "lucide-react";

// Presentational summary cards for the health-check history. Counts come from
// the /healthchecks/stats/ endpoint (independent of the paginated list); the
// percentages are derived here from total.
const pct = (n, total) => (total > 0 ? `${((n / total) * 100).toFixed(1)}%` : "—");

function Trend({ value }) {
  if (value == null) return null;
  const up = value >= 0;
  const Icon = up ? TrendingUp : TrendingDown;
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium ${up ? "text-success" : "text-danger"}`}>
      <Icon size={13} />
      {Math.abs(value)}% so với kỳ trước
    </span>
  );
}

export default function HealthCheckStats({ stats = {}, loading = false }) {
  const total = stats.total ?? 0;
  const cards = [
    {
      key: "total",
      label: "Tổng số lần kiểm tra",
      value: total,
      Icon: Activity,
      tint: "bg-blue-500/15 text-blue-300",
      sub: <Trend value={stats.trend_pct} />,
    },
    {
      key: "healthy",
      label: "Hệ thống khỏe mạnh",
      value: stats.healthy ?? 0,
      Icon: ShieldCheck,
      tint: "bg-green-500/15 text-success",
      sub: <span className="text-xs text-muted">{pct(stats.healthy ?? 0, total)}</span>,
    },
    {
      key: "warning",
      label: "Cảnh báo",
      value: stats.warning ?? 0,
      Icon: AlertTriangle,
      tint: "bg-amber-500/15 text-warning",
      sub: <span className="text-xs text-muted">{pct(stats.warning ?? 0, total)}</span>,
    },
    {
      key: "critical",
      label: "Lỗi nghiêm trọng",
      value: stats.critical ?? 0,
      Icon: XCircle,
      tint: "bg-red-500/15 text-danger",
      sub: <span className="text-xs text-muted">{pct(stats.critical ?? 0, total)}</span>,
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
      {cards.map(({ key, label, value, Icon, tint, sub }) => (
        <div key={key} className="flex items-start gap-3 rounded bg-surface-raised p-3 border border-border">
          <span className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full ${tint}`}>
            <Icon size={22} />
          </span>
          <div className="min-w-0">
            <p className="text-sm text-muted">{label}</p>
            {loading ? (
              <Skeleton.Input active size="small" style={{ width: 80, height: 24 }} />
            ) : (
              <>
                <p className="font-display text-2xl font-bold leading-tight">
                  {value.toLocaleString("vi-VN")}
                </p>
                {sub}
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
