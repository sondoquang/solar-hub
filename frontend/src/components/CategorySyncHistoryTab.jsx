import { Button, DatePicker, Input, Select } from "antd";
import { CalendarClock, CircleCheck, CircleX, ListChecks, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";

import { useAllSites } from "../api/sites.js";
import {
  exportCategoryRun,
  useCategoryRuns,
  useCategoryRunStats,
} from "../api/syncReports.js";
import CategoryRunDetailModal, { RunStatusTag } from "./CategoryRunDetailModal.jsx";
import DataTable from "./DataTable.jsx";
import EmptyState from "./EmptyState.jsx";
import ErrorState from "./ErrorState.jsx";
import { formatDate, formatDateTime, formatDuration } from "../lib/format.js";
import StatCards from "./StatCards.jsx";

const { RangePicker } = DatePicker;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const STATUS_OPTIONS = [
  { value: "all", label: "Tất cả kết quả" },
  { value: "success", label: "Thành công" },
  { value: "partial", label: "Một phần" },
  { value: "error", label: "Thất bại" },
];

// Short, friendly run label from the UUID (the full id stays the row key + is
// what the detail/export use).
const shortRun = (runId) => `SYNC-${String(runId).replace(/-/g, "").slice(0, 12).toUpperCase()}`;

// "Lịch sử đồng bộ" tab: stat cards + filters (kết quả / khoảng ngày / site /
// tìm kiếm) + the runs table (one row per "Đồng bộ danh mục" click) with the
// detail modal + Excel export. Stats + list share the same filters so the cards
// track what the table shows.
export default function CategorySyncHistoryTab() {
  const [statusFilter, setStatusFilter] = useState("all");
  const [siteFilter, setSiteFilter] = useState(null);
  const [range, setRange] = useState(null); // [dayjs, dayjs] | null
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [detailRunId, setDetailRunId] = useState(null);
  const [exportingId, setExportingId] = useState(null);

  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(t);
  }, [searchInput]);

  const { data: sites = [], isLoading: sitesLoading } = useAllSites();

  const filters = {
    status: statusFilter === "all" ? undefined : statusFilter,
    site: siteFilter ?? undefined,
    date_from: range?.[0]?.format("YYYY-MM-DD"),
    date_to: range?.[1]?.format("YYYY-MM-DD"),
    search: search || undefined,
  };

  const stats = useCategoryRunStats(filters);
  const { data, isLoading, isFetching, isError, refetch } = useCategoryRuns({
    page,
    page_size: pageSize,
    ...filters,
  });

  const rows = data?.results ?? [];
  const total = data?.count ?? 0;
  const s = stats.data ?? {};
  const last = s.last_run;

  const cards = [
    {
      key: "total",
      label: "Tổng số lần đồng bộ",
      value: (s.total ?? 0).toLocaleString("vi-VN"),
      sub: "Trong khoảng đã lọc",
      Icon: ListChecks,
      tint: "bg-blue-500/15 text-blue-300",
    },
    {
      key: "success",
      label: "Thành công",
      value: (s.success ?? 0).toLocaleString("vi-VN"),
      Icon: CircleCheck,
      tint: "bg-green-500/15 text-success",
    },
    {
      key: "partial",
      label: "Một phần",
      value: (s.partial ?? 0).toLocaleString("vi-VN"),
      Icon: TriangleAlert,
      tint: "bg-amber-500/15 text-warning",
    },
    {
      key: "error",
      label: "Thất bại",
      value: (s.error ?? 0).toLocaleString("vi-VN"),
      Icon: CircleX,
      tint: "bg-red-500/15 text-danger",
    },
    {
      key: "last",
      label: "Lần gần nhất",
      value: last ? formatDate(last.started_at) : "—",
      sub: last ? (last.site_label ?? `${last.site_count} site`) : "Chưa có",
      Icon: CalendarClock,
      tint: "bg-violet-500/15 text-violet-300",
    },
  ];

  const handleExport = async (runId) => {
    setExportingId(runId);
    try {
      await exportCategoryRun(runId);
      toast.success("Đã xuất báo cáo Excel.");
    } catch {
      toast.error("Xuất báo cáo thất bại.");
    } finally {
      setExportingId(null);
    }
  };

  const handleTableChange = (pagination) => {
    const resets = pagination.pageSize !== pageSize;
    setPageSize(pagination.pageSize);
    setPage(resets ? 1 : pagination.current);
  };

  const columns = [
    {
      key: "run_id",
      dataIndex: "run_id",
      title: "Run ID",
      width: 190,
      render: (v) => <span className="font-medium tabular-nums text-brand">{shortRun(v)}</span>,
    },
    {
      key: "triggered_by",
      dataIndex: "triggered_by",
      title: "Người chạy",
      width: 140,
      render: (v) => v || <span className="text-muted">Hệ thống</span>,
    },
    {
      key: "started_at",
      dataIndex: "started_at",
      title: "Thời gian bắt đầu",
      width: 180,
      render: (v) => <span className="tabular-nums">{formatDateTime(v)}</span>,
    },
    {
      key: "website",
      title: "Website",
      width: 180,
      render: (_v, r) => r.site_label ?? <span className="text-muted">{r.site_count} site</span>,
    },
    {
      key: "status",
      dataIndex: "status",
      title: "Kết quả",
      width: 140,
      ellipsis: false,
      render: (v, r) => (
        <div className="flex items-center gap-1.5">
          <RunStatusTag status={v} />
          {r.error_count > 0 && <span className="text-xs text-danger">{r.error_count} lỗi</span>}
        </div>
      ),
    },
    {
      key: "total_pulled",
      dataIndex: "total_pulled",
      title: "Tổng",
      width: 90,
      align: "right",
      render: (v) => <span className="tabular-nums">{v}</span>,
    },
    {
      key: "total_mapped",
      dataIndex: "total_mapped",
      title: "Đã ánh xạ",
      width: 110,
      align: "right",
      render: (v) => <span className="tabular-nums">{v}</span>,
    },
    {
      key: "error_count",
      dataIndex: "error_count",
      title: "Lỗi",
      width: 80,
      align: "right",
      render: (v) => <span className={`tabular-nums ${v ? "text-danger" : ""}`}>{v}</span>,
    },
    {
      key: "duration_seconds",
      dataIndex: "duration_seconds",
      title: "Thời gian",
      width: 110,
      align: "right",
      render: (v) => <span className="tabular-nums text-muted">{formatDuration(v)}</span>,
    },
    {
      key: "actions",
      title: "Thao tác",
      width: 220,
      align: "right",
      hideable: false,
      ellipsis: false,
      render: (_v, r) => (
        <div className="flex items-center justify-end gap-1">
          <Button type="link" size="small" onClick={() => setDetailRunId(r.run_id)}>
            Xem chi tiết
          </Button>
          <Button
            size="small"
            loading={exportingId === r.run_id}
            onClick={() => handleExport(r.run_id)}
          >
            Xuất Excel
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <StatCards cards={cards} loading={stats.isLoading} columns={5} />

      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={statusFilter}
          onChange={(v) => {
            setStatusFilter(v);
            setPage(1);
          }}
          options={STATUS_OPTIONS}
          className="min-w-40"
        />
        <RangePicker
          value={range}
          format="DD/MM/YYYY"
          onChange={(v) => {
            setRange(v);
            setPage(1);
          }}
        />
        <Select
          showSearch
          allowClear
          loading={sitesLoading}
          value={siteFilter}
          placeholder="Tất cả website"
          optionFilterProp="label"
          className="min-w-48"
          onChange={(v) => {
            setSiteFilter(v ?? null);
            setPage(1);
          }}
          options={sites.map((site) => ({ value: site.id, label: site.name }))}
        />
        <Input.Search
          allowClear
          placeholder="Tìm theo run ID, website, người chạy…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          className="w-72"
        />
      </div>

      {isError ? (
        <ErrorState message="Không tải được lịch sử đồng bộ" onRetry={refetch} />
      ) : (
        <div className="rounded bg-surface-raised p-2.5 border border-border">
          <DataTable
            columns={columns}
            dataSource={rows}
            rowKey="run_id"
            size="middle"
            loading={isLoading || isFetching}
            onRefresh={refetch}
            refreshing={isFetching}
            onChange={handleTableChange}
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              pageSizeOptions: PAGE_SIZE_OPTIONS,
              showTotal: (t, r) => `${r[0]}–${r[1]} trên ${t}`,
            }}
            locale={{
              emptyText: (
                <EmptyState
                  title="Chưa có lần đồng bộ nào phù hợp"
                  hint='Bấm "Đồng bộ danh mục" để bắt đầu, hoặc nới bộ lọc.'
                />
              ),
            }}
          />
        </div>
      )}

      <CategoryRunDetailModal
        runId={detailRunId}
        open={detailRunId != null}
        onClose={() => setDetailRunId(null)}
      />
    </div>
  );
}
