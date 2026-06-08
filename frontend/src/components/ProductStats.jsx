import { Skeleton } from "antd";
import { Link2, Package, Unlink } from "lucide-react";

// Presentational summary cards for the products screen. Counts come from the
// /products/stats/ endpoint (independent of the paginated list). While `loading`
// the values render as skeleton blocks instead of flashing 0 → real number.
export default function ProductStats({ stats = {}, loading = false }) {
  const cards = [
    {
      key: "total",
      label: "Tổng sản phẩm",
      value: (stats.total ?? 0).toLocaleString("vi-VN"),
      Icon: Package,
      tint: "bg-blue-50 text-blue-500",
    },
    {
      key: "mapped",
      label: "Đã đồng bộ site",
      value: (stats.mapped ?? 0).toLocaleString("vi-VN"),
      Icon: Link2,
      tint: "bg-green-50 text-success",
    },
    {
      key: "unmapped",
      label: "Chưa đồng bộ",
      value: (stats.unmapped ?? 0).toLocaleString("vi-VN"),
      Icon: Unlink,
      tint: "bg-amber-50 text-warning",
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
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
