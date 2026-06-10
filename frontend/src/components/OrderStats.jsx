import { Skeleton } from "antd";
import { Banknote, Send, ShieldAlert, ShoppingCart } from "lucide-react";

import { formatVND } from "../lib/format.js";

// Presentational summary cards for the orders screen. Counts come from the
// /orders/stats/ endpoint (independent of the paginated list). While `loading`
// the values render as skeleton blocks instead of flashing 0 → real number.
export default function OrderStats({ stats = {}, loading = false }) {
  const total = stats.total ?? 0;
  const byClass = stats.by_classification ?? {};
  const flagged = (byClass.suspicious ?? 0) + (byClass.spam ?? 0);
  const cards = [
    {
      key: "total",
      label: "Tổng số đơn",
      value: (total).toLocaleString("vi-VN"),
      Icon: ShoppingCart,
      tint: "bg-blue-50 text-blue-500",
    },
    {
      key: "revenue",
      label: "Tổng doanh thu",
      value: formatVND(stats.revenue ?? 0),
      Icon: Banknote,
      tint: "bg-green-50 text-success",
    },
    {
      key: "not_forwarded",
      label: "Chưa chuyển marketing",
      value: (stats.not_forwarded ?? 0).toLocaleString("vi-VN"),
      Icon: Send,
      tint: "bg-amber-50 text-warning",
    },
    {
      key: "flagged",
      label: "Nghi ngờ / Spam",
      value: flagged.toLocaleString("vi-VN"),
      Icon: ShieldAlert,
      tint: "bg-red-50 text-danger",
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map(({ key, label, value, Icon, tint }) => (
        <div key={key} className="flex items-start gap-3 rounded bg-white p-3 shadow-card">
          <span className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full ${tint}`}>
            <Icon size={22} />
          </span>
          <div className="min-w-0">
            <p className="text-sm text-muted">{label}</p>
            {loading ? (
              <Skeleton.Input active size="small" style={{ width: 96, height: 24 }} />
            ) : (
              <p className="truncate font-display text-2xl font-bold leading-tight">{value}</p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
