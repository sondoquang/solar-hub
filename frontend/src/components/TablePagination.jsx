import { ChevronLeft, ChevronRight } from "lucide-react";

// Presentational pager for client-side paginated tables. Page math lives in the
// container; this only renders controls and reports intent via callbacks.
export default function TablePagination({
  page,
  pageSize,
  total,
  pageSizeOptions = [10, 20, 50],
  onPageChange,
  onPageSizeChange,
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 text-sm text-muted">
      <div className="flex items-center gap-2">
        Hiển thị
        <select
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          className="rounded-lg border border-slate-200 px-2 py-1 text-ink focus:border-brand focus:outline-none"
          aria-label="Số dòng mỗi trang"
        >
          {pageSizeOptions.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
        trên mỗi trang
      </div>

      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 text-ink transition-colors hover:bg-slate-50 disabled:opacity-40"
          aria-label="Trang trước"
        >
          <ChevronLeft size={16} />
        </button>
        {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => onPageChange(p)}
            aria-current={p === page ? "page" : undefined}
            className={[
              "flex h-8 min-w-8 items-center justify-center rounded-lg px-2 font-medium transition-colors",
              p === page
                ? "bg-brand text-ink"
                : "border border-slate-200 text-ink hover:bg-slate-50",
            ].join(" ")}
          >
            {p}
          </button>
        ))}
        <button
          type="button"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 text-ink transition-colors hover:bg-slate-50 disabled:opacity-40"
          aria-label="Trang sau"
        >
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
}
