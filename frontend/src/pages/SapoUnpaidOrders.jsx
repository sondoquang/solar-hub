import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, DatePicker, Input, Popconfirm, Select } from "antd";
import { CheckCircle2, RefreshCw, Store, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import {
  useCancelOrder,
  useMarkOrderPaid,
  useOrders,
  usePollOrders,
} from "../api/orders.js";
import { useSites } from "../api/sites.js";
import { SYNC_OPS, useSyncRunProgress } from "../api/syncReports.js";
import DataTable from "../components/DataTable.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ErrorState from "../components/ErrorState.jsx";
import PaymentStatusBadge from "../components/PaymentStatusBadge.jsx";
import { formatDateTime, formatVND } from "../lib/format.js";

const { RangePicker } = DatePicker;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

// This screen lists only Sapo orders that are not yet paid. The backend poll
// fetches Sapo orders by payment status (financial_status=unpaid), and the two
// row actions — Hủy đơn / Đánh dấu đã thanh toán — push the change to Sapo and
// re-sync the Hub row. WooCommerce orders never appear here (the filters pin
// platform=sapo and payment_status=unpaid).
const PINNED = { platform: "sapo", payment_status: "unpaid" };

export default function SapoUnpaidOrders() {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [scope, setScope] = useState("all"); // "all" | "site:<id>"
  const [range, setRange] = useState(null); // [dayjs, dayjs] | null
  const [ordering, setOrdering] = useState("-date_created_woo");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  // Debounce the search box so we re-query once the user pauses.
  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(t);
  }, [searchInput]);

  const filters = useMemo(() => {
    const [scopeKind, scopeId] = scope.split(":");
    return {
      ...PINNED,
      search: search || undefined,
      site: scopeKind === "site" ? scopeId : undefined,
      date_from: range?.[0]?.format("YYYY-MM-DD"),
      date_to: range?.[1]?.format("YYYY-MM-DD"),
    };
  }, [search, scope, range]);

  const { data, isLoading, isFetching, isError, refetch } = useOrders({
    ...filters,
    ordering,
    page,
    page_size: pageSize,
  });
  // Only Sapo sites are relevant to the scope picker.
  const { data: siteData } = useSites({ page_size: 100, platform: "sapo" });
  const poll = usePollOrders();
  const cancelOrder = useCancelOrder();
  const markPaid = useMarkOrderPaid();
  const qc = useQueryClient();

  const orderRun = useSyncRunProgress(SYNC_OPS.orders, {
    onFinish: ({ finished, timedOut, expected, errorCount }) => {
      if (timedOut) {
        toast("Đồng bộ chạy lâu hơn dự kiến — kiểm tra lại sau.", { icon: "⏳" });
      } else if (errorCount) {
        toast(`Đồng bộ xong, ${errorCount}/${expected} site lỗi.`, { icon: "⚠️" });
      } else if (finished) {
        toast.success(`Đã đồng bộ đơn Sapo từ ${expected} site.`);
      }
      qc.invalidateQueries({ queryKey: ["orders"] });
    },
  });

  const rows = data?.results ?? [];
  const total = data?.count ?? 0;
  const sites = siteData?.results ?? [];

  const scopeOptions = [
    { value: "all", label: "Tất cả website Sapo" },
    ...sites.map((s) => ({ value: `site:${s.id}`, label: s.name })),
  ];

  // Sync the unpaid Sapo orders. ``platform: "sapo"`` scopes the run to every
  // Sapo site server-side (deduped by store); a picked site narrows it further.
  // The backend layers financial_status=unpaid for Sapo.
  const handlePoll = () => {
    const [scopeKind, scopeId] = scope.split(":");
    const pollSites = scopeKind === "site" ? [Number(scopeId)] : undefined;
    poll.mutate(
      {
        platform: "sapo",
        sites: pollSites,
        date_from: range?.[0]?.format("YYYY-MM-DD"),
        date_to: range?.[1]?.format("YYYY-MM-DD"),
      },
      {
        onSuccess: (res) => {
          toast.success("Đã kích hoạt đồng bộ đơn Sapo.");
          orderRun.start({ runId: res.run_id, expected: res.expected });
        },
        onError: () => toast.error("Kích hoạt đồng bộ thất bại."),
      },
    );
  };

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

  const onPaid = (r) =>
    markPaid.mutate(r.id, {
      onSuccess: () => toast.success(`Đã đánh dấu thanh toán đơn #${r.number}.`),
      onError: (err) =>
        toast.error(err?.response?.data?.detail || "Đánh dấu thanh toán thất bại."),
    });

  const onCancel = (r) =>
    cancelOrder.mutate(r.id, {
      onSuccess: () => toast.success(`Đã hủy đơn #${r.number}.`),
      onError: (err) => toast.error(err?.response?.data?.detail || "Hủy đơn thất bại."),
    });

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
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-emerald-500">
            <Store size={15} />
          </span>
          <div className="flex min-w-0 flex-col gap-1">
            <p className="truncate font-medium mb-1">#{r.number}</p>
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
        <div className="min-w-0 flex flex-col gap-1">
          <p className="truncate mb-1">{r.customer_name || "—"}</p>
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
      key: "payment_status",
      dataIndex: "payment_status",
      title: "Trạng thái thanh toán",
      width: 180,
      ellipsis: false,
      render: (status) => <PaymentStatusBadge status={status} />,
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
      width: 230,
      align: "right",
      hideable: false,
      ellipsis: false,
      render: (_v, r) => (
        <div className="flex items-center justify-end gap-1">
          <Popconfirm
            title="Đánh dấu đã thanh toán?"
            description="Ghi nhận thanh toán đủ cho đơn này trên Sapo."
            okText="Xác nhận"
            cancelText="Đóng"
            onConfirm={() => onPaid(r)}
          >
            <Button
              type="link"
              size="small"
              icon={<CheckCircle2 size={14} />}
              loading={markPaid.isPending && markPaid.variables === r.id}
            >
              Đã thanh toán
            </Button>
          </Popconfirm>
          <Popconfirm
            title="Hủy đơn này?"
            description="Đơn sẽ được hủy trên Sapo."
            okText="Xác nhận hủy"
            cancelText="Đóng"
            okButtonProps={{ danger: true }}
            onConfirm={() => onCancel(r)}
          >
            <Button
              type="link"
              size="small"
              danger
              icon={<XCircle size={14} />}
              loading={cancelOrder.isPending && cancelOrder.variables === r.id}
            >
              Hủy đơn
            </Button>
          </Popconfirm>
        </div>
      ),
    },
  ];

  const filterActive = search !== "" || scope !== "all" || range != null;

  return (
    <section className="pt-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-1.5">
        <h1 className="font-display text-2xl font-bold">Đơn Sapo chưa thanh toán</h1>
        <Button
          type="primary"
          icon={<RefreshCw size={16} />}
          loading={poll.isPending}
          onClick={handlePoll}
        >
          Đồng bộ ngay
        </Button>
      </div>

      {orderRun.activeRun && (
        <Alert
          type="info"
          showIcon
          className="mb-3"
          message={`Đang đồng bộ đơn Sapo… ${orderRun.doneSites}/${orderRun.activeRun.expected} site hoàn tất.`}
        />
      )}

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
        <ErrorState message="Không tải được danh sách đơn Sapo" onRetry={refetch} />
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
                  title={
                    filterActive
                      ? "Không có đơn Sapo phù hợp"
                      : "Không có đơn Sapo chưa thanh toán"
                  }
                  hint={
                    filterActive
                      ? "Thử đổi bộ lọc hoặc khoảng thời gian."
                      : 'Nhấn "Đồng bộ ngay" để gom đơn chưa thanh toán từ Sapo.'
                  }
                />
              ),
            }}
          />
        </div>
      )}
    </section>
  );
}
