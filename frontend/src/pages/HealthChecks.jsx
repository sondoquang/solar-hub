import { Button, DatePicker, Dropdown, Input, Select } from "antd";
import { Download, Eye, Globe, MoreVertical, Server } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import { exportHealthChecks, useHealthCheckStats, useHealthChecks } from "../api/healthChecks.js";
import { hostingLabel, useHostings } from "../api/hostings.js";
import { useSites } from "../api/sites.js";
import DataTable from "../components/DataTable.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ErrorState from "../components/ErrorState.jsx";
import HealthCheckDetailModal from "../components/HealthCheckDetailModal.jsx";
import HealthCheckStats from "../components/HealthCheckStats.jsx";
import HealthStatusBadge from "../components/HealthStatusBadge.jsx";
import { formatDateTime, formatResponseTime } from "../lib/format.js";

const { RangePicker } = DatePicker;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

const STATUS_OPTIONS = [
  { value: "all", label: "Tất cả trạng thái" },
  { value: "healthy", label: "Khỏe mạnh" },
  { value: "warning", label: "Cảnh báo" },
  { value: "critical", label: "Lỗi nghiêm trọng" },
];

// Response time inherits the row's health colour so the table scans quickly.
const RT_COLOR = { healthy: "text-success", warning: "text-warning", critical: "text-danger" };

export default function HealthChecks() {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [scope, setScope] = useState("all"); // "all" | "site:<id>" | "hosting:<id>"
  const [range, setRange] = useState(null); // [dayjs, dayjs] | null
  const [ordering, setOrdering] = useState("-checked_at");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [detail, setDetail] = useState(null);
  const [exporting, setExporting] = useState(false);

  // Debounce the search box so we re-query once the user pauses.
  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(t);
  }, [searchInput]);

  // Shared filter payload — the list, the stats cards and the export all use it.
  const filters = useMemo(() => {
    const [scopeKind, scopeId] = scope.split(":");
    return {
      search: search || undefined,
      status: statusFilter === "all" ? undefined : statusFilter,
      site: scopeKind === "site" ? scopeId : undefined,
      hosting: scopeKind === "hosting" ? scopeId : undefined,
      date_from: range?.[0]?.format("YYYY-MM-DD"),
      date_to: range?.[1]?.format("YYYY-MM-DD"),
    };
  }, [search, statusFilter, scope, range]);

  const { data, isLoading, isFetching, isError, refetch } = useHealthChecks({
    ...filters,
    ordering,
    page,
    page_size: pageSize,
  });
  const { data: stats, isLoading: statsLoading } = useHealthCheckStats(filters);
  const { data: hostingData } = useHostings({ page_size: 100 });
  const { data: siteData } = useSites({ page_size: 100 });

  const rows = data?.results ?? [];
  const total = data?.count ?? 0;
  const hostings = hostingData?.results ?? [];
  const sites = siteData?.results ?? [];

  const scopeOptions = [
    { value: "all", label: "Tất cả website/hosting" },
    {
      label: "Website",
      options: sites.map((s) => ({ value: `site:${s.id}`, label: s.name })),
    },
    {
      label: "Hosting",
      options: hostings.map((h) => ({ value: `hosting:${h.id}`, label: hostingLabel(h) })),
    },
  ];

  const handleExport = async () => {
    setExporting(true);
    try {
      await exportHealthChecks(filters);
      toast.success("Đã xuất báo cáo CSV.");
    } catch {
      toast.error("Xuất báo cáo thất bại.");
    } finally {
      setExporting(false);
    }
  };

  // antd drives sort/page through onChange. checked_at + response_time_ms are
  // server-sortable; a sort or page-size change resets to page 1.
  const handleTableChange = (pagination, _filters, sorter) => {
    let next = "-checked_at";
    if (sorter?.order) {
      const prefix = sorter.order === "descend" ? "-" : "";
      next = `${prefix}${sorter.field}`;
    }
    const resets = pagination.pageSize !== pageSize || next !== ordering;
    setOrdering(next);
    setPageSize(pagination.pageSize);
    setPage(resets ? 1 : pagination.current);
  };

  const sortOrder = (field) =>
    ordering === field ? "ascend" : ordering === `-${field}` ? "descend" : null;

  const columns = [
    {
      key: "stt",
      title: "STT",
      width: 64,
      ellipsis: false,
      align: "center",
      render: (_v, _r, i) => (page - 1) * pageSize + i + 1,
    },
    {
      key: "site",
      title: "Website / Hosting",
      width: 240,
      render: (_v, r) => (
        <div className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-50 text-blue-500">
            <Globe size={15} />
          </span>
          <div className="min-w-0">
            <p className="truncate font-medium">{r.site_name}</p>
            <p className="truncate text-xs text-muted">
              {r.hosting_name ? `Hosting: ${r.hosting_name}` : "Chưa gán hosting"}
            </p>
          </div>
        </div>
      ),
    },
    {
      key: "check_type",
      dataIndex: "check_type_display",
      title: "Loại kiểm tra",
      width: 150,
    },
    {
      key: "checked_at",
      dataIndex: "checked_at",
      title: "Thời gian kiểm tra",
      width: 180,
      sorter: true,
      sortOrder: sortOrder("checked_at"),
      render: (v) => <span className="tabular-nums text-muted">{formatDateTime(v)}</span>,
    },
    {
      key: "status",
      dataIndex: "status",
      title: "Trạng thái",
      width: 160,
      ellipsis: false,
      render: (status, r) => <HealthStatusBadge status={status} label={r.status_display} />,
    },
    {
      key: "response_time_ms",
      dataIndex: "response_time_ms",
      title: "Thời gian phản hồi",
      width: 160,
      sorter: true,
      sortOrder: sortOrder("response_time_ms"),
      render: (v, r) => (
        <span className={`font-medium tabular-nums ${RT_COLOR[r.status] || ""}`}>
          {formatResponseTime(v)}
        </span>
      ),
    },
    {
      key: "performed_by",
      dataIndex: "performed_by_name",
      title: "Người thực hiện",
      width: 150,
      render: (v) => (
        <span className="inline-flex items-center gap-1.5 text-muted">
          <Server size={14} className="text-slate-400" />
          {v}
        </span>
      ),
    },
    {
      key: "actions",
      title: "Thao tác",
      width: 150,
      align: "right",
      hideable: false,
      ellipsis: false,
      render: (_v, r) => (
        <div className="flex items-center justify-end gap-1">
          <Button type="link" size="small" icon={<Eye size={14} />} onClick={() => setDetail(r)}>
            Xem chi tiết
          </Button>
          <Dropdown
            trigger={["click"]}
            menu={{
              items: [{ key: "detail", label: "Xem chi tiết", icon: <Eye size={14} /> }],
              onClick: () => setDetail(r),
            }}
          >
            <Button type="text" size="small" icon={<MoreVertical size={16} />} />
          </Dropdown>
        </div>
      ),
    },
  ];

  const filterActive =
    search !== "" || statusFilter !== "all" || scope !== "all" || range != null;

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-1.5">
        <div>
          <h1 className="font-display text-2xl font-bold">Lịch sử kiểm tra sức khỏe hệ thống</h1>
          <p className="mt-1 text-sm text-muted">
            Theo dõi và quản lý lịch sử kiểm tra sức khỏe của các website và dịch vụ hosting.
          </p>
        </div>
        <Button
          type="primary"
          ghost
          icon={<Download size={16} />}
          loading={exporting}
          onClick={handleExport}
        >
          Xuất báo cáo
        </Button>
      </div>

      <div className="mb-3">
        <HealthCheckStats stats={stats ?? {}} loading={statsLoading} />
      </div>

      <div className="mb-2.5 flex flex-wrap items-center gap-2">
        <RangePicker
          value={range}
          onChange={(v) => {
            setRange(v);
            setPage(1);
          }}
          format="DD/MM/YYYY"
          className="w-64"
          allowClear
        />
        <Select
          value={statusFilter}
          onChange={(v) => {
            setStatusFilter(v);
            setPage(1);
          }}
          options={STATUS_OPTIONS}
          className="min-w-44"
        />
        <Select
          value={scope}
          onChange={(v) => {
            setScope(v);
            setPage(1);
          }}
          options={scopeOptions}
          className="min-w-56"
          showSearch
          optionFilterProp="label"
        />
      </div>

      {isError ? (
        <ErrorState message="Không tải được lịch sử kiểm tra" onRetry={refetch} />
      ) : (
        <div className="rounded bg-white p-2.5 shadow-card">
          <DataTable
            columns={columns}
            dataSource={rows}
            rowKey="id"
            size="middle"
            loading={isLoading || isFetching}
            onRefresh={refetch}
            refreshing={isFetching}
            searchSlot={
              <Input.Search
                allowClear
                placeholder="Tìm theo tên website, hosting…"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="w-64"
              />
            }
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
                  title={filterActive ? "Không có kết quả phù hợp" : "Chưa có lần kiểm tra nào"}
                  hint={
                    filterActive
                      ? "Thử đổi bộ lọc hoặc khoảng thời gian."
                      : "Kiểm tra sức khỏe website ở trang Quản lý website hoặc Hosting."
                  }
                />
              ),
            }}
          />
        </div>
      )}

      <HealthCheckDetailModal
        check={detail}
        open={detail != null}
        onClose={() => setDetail(null)}
      />
    </section>
  );
}
