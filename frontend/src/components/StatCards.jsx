import { Skeleton } from "antd";

// Generic stat-card grid (icon + label + big value + optional sub-line), shared
// by the category dashboard tabs. Mirrors ProductStats/SiteStats but takes the
// cards as data so each tab can declare its own. `columns` picks the lg layout.
// While `loading` the values render as skeleton blocks instead of flashing 0.
const COL_CLASS = {
  3: "lg:grid-cols-3",
  4: "lg:grid-cols-4",
  5: "lg:grid-cols-5",
};

export default function StatCards({ cards, loading = false, columns = 4 }) {
  return (
    <div className={`grid grid-cols-2 gap-2 ${COL_CLASS[columns] ?? COL_CLASS[4]}`}>
      {cards.map(({ key, label, value, sub, Icon, tint }) => (
        <div key={key} className="flex items-start gap-3 rounded bg-surface-raised p-3 border border-border">
          <span
            className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full ${tint}`}
          >
            <Icon size={22} />
          </span>
          <div className="min-w-0">
            <p className="text-sm text-muted">{label}</p>
            {loading ? (
              <Skeleton.Input active size="small" style={{ width: 80, height: 24 }} />
            ) : (
              <p className="truncate font-display text-2xl font-bold leading-tight">{value}</p>
            )}
            {sub != null && !loading && (
              <p className="mt-0.5 truncate text-xs text-muted">{sub}</p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
