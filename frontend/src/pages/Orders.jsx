import { Button, DatePicker, Input, Select } from "antd";
import { Eye, FileDown, Globe, RefreshCw, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import { hostingLabel, useHostings } from "../api/hostings.js";
import { exportOrdersPdf, useOrders, useOrderStats, usePollOrders } from "../api/orders.js";
import { useSites } from "../api/sites.js";
import DataTable from "../components/DataTable.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ErrorState from "../components/ErrorState.jsx";
import OrderDetailModal from "../components/OrderDetailModal.jsx";
import OrderStats from "../components/OrderStats.jsx";
import OrderStatusBadge from "../components/OrderStatusBadge.jsx";
import { formatDateTime, formatVND } from "../lib/format.js";

const { RangePicker } = DatePicker;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

const STATUS_OPTIONS = [
  { value: "all", label: "Tất cả trạng thái" },
  { value: "processing", label: "Đang xử lý" },
  { value: "completed", label: "Hoàn thành" },
  { value: "on-hold", label: "Tạm giữ" },
  { value: "pending", label: "Chờ thanh toán" },
  { value: "cancelled", label: "Đã hủy" },
];

const FORWARDED_OPTIONS = [
  { value: "all", label: "Tất cả" },
  { value: "false", label: "Chưa chuyển marketing" },
  { value: "true", label: "Đã chuyển marketing" },
];

export default function Orders() {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [forwardedFilter, setForwardedFilter] = useState("all");
  const [scope, setScope] = useState("all"); // "all" | "site:<id>" | "hosting:<id>"
  const [range, setRange] = useState(null); // [dayjs, dayjs] | null
  const [ordering, setOrdering] = useState("-date_created_woo");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  // Bulk view: the modal takes an array of orders. Per-row "Xem chi tiết" opens
  // it with a single order; the toolbar action opens it with every ticked order.
  const [viewOrders, setViewOrders] = useState([]);
  const [viewOpen, setViewOpen] = useState(false);

  // Row selection. Keys + a separate id→row map so a selection survives paging
  // (antd's onChange `rows` only carries the current page when server-paginated).
  const [selectedKeys, setSelectedKeys] = useState([]);
  const [selectedMap, setSelectedMap] = useState(() => new Map());
  const [exporting, setExporting] = useState(false);

  // Debounce the search box so we re-query once the user pauses.
  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(t);
  }, [searchInput]);

  // Shared filter payload — the list and the stats cards both use it.
  const filters = useMemo(() => {
    const [scopeKind, scopeId] = scope.split(":");
    return {
      search: search || undefined,
      status: statusFilter === "all" ? undefined : statusFilter,
      forwarded: forwardedFilter === "all" ? undefined : forwardedFilter,
      site: scopeKind === "site" ? scopeId : undefined,
      hosting: scopeKind === "hosting" ? scopeId : undefined,
      date_from: range?.[0]?.format("YYYY-MM-DD"),
      date_to: range?.[1]?.format("YYYY-MM-DD"),
    };
  }, [search, statusFilter, forwardedFilter, scope, range]);

  const { data, isLoading, isFetching, isError, refetch } = useOrders({
    ...filters,
    ordering,
    page,
    page_size: pageSize,
  });
  const { data: stats, isLoading: statsLoading } = useOrderStats(filters);
  const { data: hostingData } = useHostings({ page_size: 100 });
  const { data: siteData } = useSites({ page_size: 100 });
  const poll = usePollOrders();

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

  // Sync exactly what the filters describe: the chosen status (the periodic
  // poll only does "processing", so an explicit status is how other statuses
  // get pulled), the scoped site(s) — a hosting scope expands to its sites —
  // and the date range. One run syncs one status; "Tất cả trạng thái" falls
  // back to the backend default (processing).
  const handlePoll = () => {
    const [scopeKind, scopeId] = scope.split(":");
    let pollSites;
    if (scopeKind === "site") {
      pollSites = [Number(scopeId)];
    } else if (scopeKind === "hosting") {
      pollSites = sites.filter((s) => String(s.hosting) === scopeId).map((s) => s.id);
    }
    const payload = {
      status: statusFilter === "all" ? undefined : statusFilter,
      sites: pollSites,
      date_from: range?.[0]?.format("YYYY-MM-DD"),
      date_to: range?.[1]?.format("YYYY-MM-DD"),
    };
    poll.mutate(payload, {
      onSuccess: () => toast.success("Đã kích hoạt đồng bộ đơn hàng."),
      onError: () => toast.error("Kích hoạt đồng bộ thất bại."),
    });
  };

  // antd drives sort/page through onChange. date_created_woo + total are
  // server-sortable; a sort or page-size change resets to page 1.
  const handleTableChange = (pagination, _filters, sorter) => {
    let next = "-date_created_woo";
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

  // Keep the keys in sync and remember each ticked row's full object so the bulk
  // modal has the data even for rows selected on a now-unloaded page.
  const handleSelectChange = useCallback((keys, selectedRows) => {
    setSelectedKeys(keys);
    setSelectedMap((prev) => {
      const next = new Map(prev);
      selectedRows.forEach((r) => r && next.set(r.id, r));
      // Drop rows that are no longer selected so the map stays bounded.
      const keySet = new Set(keys);
      for (const id of next.keys()) if (!keySet.has(id)) next.delete(id);
      return next;
    });
  }, []);

  const clearSelection = () => {
    setSelectedKeys([]);
    setSelectedMap(new Map());
  };

  const openOrders = (list) => {
    setViewOrders(list);
    setViewOpen(true);
  };

  // Bulk view follows the order the rows appear in the current list.
  const openSelected = () => {
    const list = selectedKeys.map((k) => selectedMap.get(k)).filter(Boolean);
    if (list.length) openOrders(list);
  };

  // Export the ticked orders to one PDF (one order per page) for the sales team.
  const exportSelected = async () => {
    if (!selectedKeys.length) return;
    setExporting(true);
    try {
      await exportOrdersPdf({ ids: selectedKeys });
      toast.success(`Đã xuất PDF ${selectedKeys.length} đơn hàng.`);
    } catch {
      toast.error("Xuất PDF thất bại.");
    } finally {
      setExporting(false);
    }
  };

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
      key: "number",
      title: "Đơn hàng",
      width: 200,
      render: (_v, r) => (
        <div className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-50 text-blue-500">
            <Globe size={15} />
          </span>
          <div className="min-w-0">
            <p className="truncate font-medium">#{r.number}</p>
            <p className="truncate text-xs text-muted">{r.site_name}</p>
          </div>
        </div>
      ),
    },
    {
      key: "customer",
      title: "Khách hàng",
      width: 200,
      render: (_v, r) => (
        <div className="min-w-0">
          <p className="truncate">{r.customer_name || "—"}</p>
          <p className="truncate text-xs text-muted">{r.customer_phone || ""}</p>
        </div>
      ),
    },
    {
      key: "total",
      dataIndex: "total",
      title: "Tổng tiền",
      width: 140,
      align: "right",
      sorter: true,
      sortOrder: sortOrder("total"),
      render: (v) => <span className="font-medium tabular-nums">{formatVND(v)}</span>,
    },
    {
      key: "status",
      dataIndex: "status",
      title: "Trạng thái",
      width: 150,
      ellipsis: false,
      render: (status) => <OrderStatusBadge status={status} />,
    },
    {
      key: "forwarded",
      dataIndex: "forwarded",
      title: "Marketing",
      width: 130,
      render: (v) =>
        v ? (
          <span className="text-xs font-medium text-success">Đã chuyển</span>
        ) : (
          <span className="text-xs text-muted">Chưa chuyển</span>
        ),
    },
    {
      key: "date_created_woo",
      dataIndex: "date_created_woo",
      title: "Ngày tạo",
      width: 170,
      sorter: true,
      sortOrder: sortOrder("date_created_woo"),
      render: (v) => <span className="tabular-nums text-muted">{formatDateTime(v)}</span>,
    },
    {
      key: "actions",
      title: "Thao tác",
      width: 130,
      align: "right",
      hideable: false,
      ellipsis: false,
      render: (_v, r) => (
        <Button type="link" size="small" icon={<Eye size={14} />} onClick={() => openOrders([r])}>
          Xem chi tiết
        </Button>
      ),
    },
  ];

  const filterActive =
    search !== "" ||
    statusFilter !== "all" ||
    forwardedFilter !== "all" ||
    scope !== "all" ||
    range != null;

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-1.5">
        <div>
          <h1 className="font-display text-2xl font-bold">Đơn hàng</h1>
          <p className="mt-1 text-sm text-muted">
            Đơn hàng được gom tự động từ các website WooCommerce về Hub.
          </p>
        </div>
        <Button
          type="primary"
          icon={<RefreshCw size={16} />}
          loading={poll.isPending}
          onClick={handlePoll}
        >
          Đồng bộ ngay
        </Button>
      </div>

      <div className="mb-3">
        <OrderStats stats={stats ?? {}} loading={statsLoading} />
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
          value={forwardedFilter}
          onChange={(v) => {
            setForwardedFilter(v);
            setPage(1);
          }}
          options={FORWARDED_OPTIONS}
          className="min-w-48"
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
        <ErrorState message="Không tải được danh sách đơn hàng" onRetry={refetch} />
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
            rowSelection={{
              selectedRowKeys: selectedKeys,
              preserveSelectedRowKeys: true,
              onChange: handleSelectChange,
            }}
            toolbarExtra={
              selectedKeys.length > 0 && (
                <div className="flex items-center gap-1.5">
                  <Button
                    type="primary"
                    size="small"
                    icon={<Eye size={14} />}
                    onClick={openSelected}
                  >
                    Xem chi tiết ({selectedKeys.length})
                  </Button>
                  <Button
                    size="small"
                    icon={<FileDown size={14} />}
                    loading={exporting}
                    onClick={exportSelected}
                  >
                    Xuất PDF ({selectedKeys.length})
                  </Button>
                  <Button size="small" icon={<X size={14} />} onClick={clearSelection}>
                    Bỏ chọn
                  </Button>
                </div>
              )
            }
            searchSlot={
              <Input.Search
                allowClear
                placeholder="Tìm theo số đơn, tên/SĐT khách…"
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
                  title={filterActive ? "Không có đơn hàng phù hợp" : "Chưa có đơn hàng nào"}
                  hint={
                    filterActive
                      ? "Thử đổi bộ lọc hoặc khoảng thời gian."
                      : 'Nhấn "Đồng bộ ngay" để gom đơn từ các website.'
                  }
                />
              ),
            }}
          />
        </div>
      )}

      <OrderDetailModal
        orders={viewOrders}
        open={viewOpen}
        onClose={() => setViewOpen(false)}
      />
    </section>
  );
}
