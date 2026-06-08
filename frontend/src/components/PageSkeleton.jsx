import { Skeleton } from "antd";

// Page-shaped loading placeholder. Used as the Suspense fallback for lazy route
// chunks (the inner menu pages) and anywhere a whole screen is still loading —
// it mirrors the real list layout (header + stat cards + filter row + table) so
// the page keeps its shape while the chunk/data arrives, instead of flashing a
// centered "Đang tải…" spinner. Tune via props to match each page:
//   stats   number of summary cards to mock (0 hides the row)
//   filters render a mock filter/toolbar row
//   rows    number of skeleton table rows
export default function PageSkeleton({ stats = 4, filters = true, rows = 8 }) {
  return (
    <section aria-busy="true" aria-label="Đang tải nội dung trang">
      {/* Header: title + subtitle on the left, an action button on the right. */}
      <div className="mb-3 flex flex-wrap items-start justify-between gap-1.5">
        <div className="space-y-2">
          <Skeleton.Input active size="default" style={{ width: 220, height: 28 }} />
          <Skeleton.Input active size="small" style={{ width: 320, height: 16 }} />
        </div>
        <Skeleton.Button active size="default" style={{ width: 130 }} />
      </div>

      {/* Summary cards — same shell as OrderStats/SiteStats/HealthCheckStats. */}
      {stats > 0 && (
        <div className="mb-3 grid grid-cols-2 gap-2 lg:grid-cols-4">
          {Array.from({ length: stats }, (_, i) => (
            <div key={i} className="flex items-center gap-3 rounded bg-white p-3 shadow-card">
              <Skeleton.Avatar active size={48} shape="circle" />
              <div className="min-w-0 flex-1 space-y-1.5">
                <Skeleton.Input active size="small" block style={{ height: 14 }} />
                <Skeleton.Input active size="small" style={{ width: "60%", height: 20 }} />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Filter / toolbar row. */}
      {filters && (
        <div className="mb-2.5 flex flex-wrap items-center gap-2">
          <Skeleton.Input active size="default" style={{ width: 256 }} />
          <Skeleton.Input active size="default" style={{ width: 176 }} />
          <Skeleton.Input active size="default" style={{ width: 224 }} />
        </div>
      )}

      {/* Table block — toolbar + a stack of shimmering rows. */}
      <div className="rounded bg-white p-2.5 shadow-card">
        <div className="flex items-center justify-between gap-2 px-1 pb-2.5">
          <Skeleton.Input active size="small" style={{ width: 160 }} />
          <div className="flex gap-1.5">
            <Skeleton.Button active size="small" style={{ width: 80 }} />
            <Skeleton.Button active size="small" style={{ width: 90 }} />
          </div>
        </div>
        <div className="divide-y divide-slate-100">
          {Array.from({ length: rows }, (_, i) => (
            <div key={i} className="py-3">
              <Skeleton.Input active size="small" block style={{ height: 18 }} />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
