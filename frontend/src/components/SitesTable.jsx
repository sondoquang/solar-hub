import { ChevronDown, ChevronUp, ExternalLink, Globe, Pencil, Play, Trash2 } from "lucide-react";

import StatusDot from "./StatusDot.jsx";
import { formatDate } from "../lib/format.js";

const th = "px-5 py-3.5 text-xs font-semibold uppercase tracking-wide text-muted";
const td = "px-5 py-4";

function SortIcon({ active, dir }) {
  return (
    <span className="ml-1 inline-flex flex-col leading-none">
      <ChevronUp size={11} className={active && dir === "asc" ? "text-brand" : "text-slate-300"} />
      <ChevronDown
        size={11}
        className={active && dir === "desc" ? "text-brand" : "text-slate-300"}
      />
    </span>
  );
}

export default function SitesTable({
  sites,
  selectedIds,
  onToggle,
  onToggleAll,
  onTest,
  testingId,
  onEdit,
  onDelete,
  sortDir,
  onToggleSort,
}) {
  const allSelected = sites.length > 0 && sites.every((s) => selectedIds.has(s.id));

  return (
    <table className="w-full text-left text-sm">
      <thead className="border-b border-slate-100">
        <tr>
          <th className={`${th} w-12`}>
            <input
              type="checkbox"
              className="h-4 w-4 cursor-pointer accent-brand"
              checked={allSelected}
              onChange={onToggleAll}
              aria-label="Chọn tất cả"
            />
          </th>
          <th className={th}>
            <button
              type="button"
              onClick={onToggleSort}
              className="inline-flex items-center uppercase tracking-wide hover:text-ink"
            >
              Tên website
              <SortIcon active={!!sortDir} dir={sortDir} />
            </button>
          </th>
          <th className={th}>Base URL</th>
          <th className={th}>Trạng thái</th>
          <th className={th}>Kiểm tra lúc</th>
          <th className={`${th} text-right`}>Hành động</th>
        </tr>
      </thead>
      <tbody>
        {sites.map((site) => {
          const testing = testingId === site.id;
          return (
            <tr
              key={site.id}
              className="border-b border-slate-50 last:border-0 hover:bg-slate-50/60"
            >
              <td className={td}>
                <input
                  type="checkbox"
                  className="h-4 w-4 cursor-pointer accent-brand"
                  checked={selectedIds.has(site.id)}
                  onChange={() => onToggle(site.id)}
                  aria-label={`Chọn ${site.name}`}
                />
              </td>
              <td className={td}>
                <span className="inline-flex items-center gap-2.5 font-medium">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-amber-50 text-brand">
                    <Globe size={15} />
                  </span>
                  {site.name}
                </span>
              </td>
              <td className={td}>
                <a
                  href={site.base_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 text-blue-600 hover:underline"
                >
                  {site.base_url}
                  <ExternalLink size={14} className="text-slate-400" />
                </a>
              </td>
              <td className={td}>
                <StatusDot status={site.status} />
              </td>
              <td className={`${td} tabular-nums text-muted`}>
                {formatDate(site.last_checked_at)}
              </td>
              <td className={td}>
                <div className="flex items-center justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => onTest(site)}
                    disabled={testing}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 font-medium text-ink transition-colors hover:bg-slate-50 disabled:opacity-50"
                  >
                    <Play size={14} />
                    {testing ? "Đang kiểm tra…" : "Test"}
                  </button>
                  <button
                    type="button"
                    onClick={() => onEdit(site)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 font-medium text-ink transition-colors hover:bg-slate-50"
                  >
                    <Pencil size={14} />
                    Sửa
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(site)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-1.5 font-medium text-danger transition-colors hover:bg-red-50"
                  >
                    <Trash2 size={14} />
                    Xóa
                  </button>
                </div>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
