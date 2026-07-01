import { useMemo, useState } from "react";
import dayjs from "dayjs";
import {
  AlertTriangle,
  CheckCircle,
  DollarSign,
  Info,
  Package,
  ShoppingCart,
  TrendingDown,
  TrendingUp,
  Users,
  XCircle,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { DatePicker, Select, Skeleton, Table } from "antd";
import { Link } from "react-router-dom";

import { useDashboard } from "../api/dashboard.js";
import ErrorState from "../components/ErrorState.jsx";
import OrderStatusBadge from "../components/OrderStatusBadge.jsx";
import { formatDateTime, formatResponseTime, formatVND, titleCaseName } from "../lib/format.js";

const { RangePicker } = DatePicker;

// ── Stat card ─────────────────────────────────────────────────────────────────
function StatCard({ icon: Icon, iconBg, iconColor, label, value, changePct, loading }) {
  if (loading) {
    return (
      <div className="rounded-lg bg-surface-raised p-4 border border-border">
        <div className="flex items-start gap-4">
          <Skeleton.Avatar active size={52} shape="circle" />
          <div className="flex-1 space-y-2 pt-1">
            <Skeleton.Input active size="small" style={{ width: "60%", height: 14 }} />
            <Skeleton.Input active size="small" style={{ width: "80%", height: 22 }} />
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="rounded-lg bg-surface-raised p-4 border border-border">
      <div className="flex items-start gap-4">
        <div
          className={`flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-full ${iconBg}`}
        >
          <Icon size={24} className={iconColor} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm text-muted">{label}</p>
          <p className="mt-0.5 text-2xl font-bold text-ink">{value}</p>
          {changePct != null && (
            <div className="mt-1 flex items-center gap-1">
              {changePct >= 0 ? (
                <TrendingUp size={13} className="text-success" />
              ) : (
                <TrendingDown size={13} className="text-danger" />
              )}
              <span
                className={`text-xs font-medium ${changePct >= 0 ? "text-success" : "text-danger"}`}
              >
                {changePct >= 0 ? "+" : ""}
                {changePct}% so với kỳ trước
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Chart custom tooltip ──────────────────────────────────────────────────────
function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-surface-muted px-3 py-2 shadow-lg">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-0.5 text-sm font-semibold text-brand">{payload[0].value} đơn</p>
    </div>
  );
}

// ── Health-check status badge ─────────────────────────────────────────────────
function HcStatusBadge({ status, label }) {
  const styles = {
    healthy: "bg-green-500/15 text-green-400",
    warning: "bg-amber-500/15 text-amber-300",
    critical: "bg-red-500/15 text-red-400",
    unknown: "bg-white/10 text-slate-300",
  };
  const dots = {
    healthy: "bg-green-500",
    warning: "bg-amber-500",
    critical: "bg-red-500",
    unknown: "bg-slate-400",
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${styles[status] ?? styles.unknown}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dots[status] ?? dots.unknown}`} />
      {label}
    </span>
  );
}

// ── Notification icon ─────────────────────────────────────────────────────────
function NotifIcon({ type }) {
  const map = {
    success: { Icon: CheckCircle, bg: "bg-green-500/15", color: "text-green-400" },
    warning: { Icon: AlertTriangle, bg: "bg-amber-500/15", color: "text-amber-400" },
    error: { Icon: XCircle, bg: "bg-red-500/15", color: "text-red-400" },
    info: { Icon: Info, bg: "bg-blue-500/15", color: "text-blue-400" },
  };
  const { Icon, bg, color } = map[type] ?? map.info;
  return (
    <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${bg}`}>
      <Icon size={16} className={color} />
    </div>
  );
}

// ── Group chart data by period ────────────────────────────────────────────────
function groupChartData(data, period) {
  if (!data?.length) return [];
  if (period === "day") return data;
  const map = new Map();
  data.forEach(({ date, count }) => {
    const key =
      period === "month"
        ? date.slice(0, 7)
        : dayjs(date).startOf("week").format("YYYY-MM-DD");
    map.set(key, (map.get(key) || 0) + count);
  });
  return Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, count]) => ({ date, count }));
}

// ── Section wrapper card ──────────────────────────────────────────────────────
function SectionCard({ title, linkTo, extra, children }) {
  return (
    <div className="flex h-full flex-col rounded-lg bg-surface-raised border border-border">
      <div className="flex shrink-0 items-center justify-between border-b border-border px-5 py-3.5">
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        <div className="flex items-center gap-3">
          {extra}
          {linkTo && (
            <Link to={linkTo} className="text-xs font-medium text-brand hover:underline">
              Xem tất cả
            </Link>
          )}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
    </div>
  );
}

// ── Table column definitions ──────────────────────────────────────────────────
const recentOrderCols = [
  {
    title: "Mã đơn",
    key: "number",
    render: (_, row) => (
      <span className="font-medium text-ink">
        #{row.number || row.woo_order_id}
      </span>
    ),
  },
  {
    title: "Khách hàng",
    dataIndex: "customer_name",
    key: "customer_name",
    ellipsis: true,
    render: (v) => titleCaseName(v) || "—",
  },
  {
    title: "Tổng tiền",
    dataIndex: "total",
    key: "total",
    align: "right",
    render: (v) => <span className="font-medium">{formatVND(Number(v))}</span>,
  },
  {
    title: "Trạng thái",
    dataIndex: "status",
    key: "status",
    render: (v) => <OrderStatusBadge status={v} />,
  },
  {
    title: "Thời gian",
    dataIndex: "date_created_woo",
    key: "time",
    render: (v) => <span className="text-muted">{formatDateTime(v)}</span>,
  },
];

const monitorCols = [
  { title: "Tên hệ thống", dataIndex: "name", key: "name", ellipsis: true },
  { title: "Loại", dataIndex: "site_type_label", key: "type", width: 100 },
  {
    title: "Trạng thái",
    dataIndex: "status",
    key: "status",
    render: (v, row) => <HcStatusBadge status={v} label={row.status_label} />,
  },
  {
    title: "Thời gian kiểm tra cuối",
    dataIndex: "hc_checked_at",
    key: "checked_at",
    render: (v) => <span className="text-xs text-muted">{formatDateTime(v)}</span>,
  },
  {
    title: "Phản hồi",
    dataIndex: "hc_response_time",
    key: "response_time",
    align: "right",
    render: (v, row) => (
      <span
        className={
          row.status === "warning" || row.status === "critical"
            ? "font-medium text-danger"
            : "text-text"
        }
      >
        {formatResponseTime(v)}
      </span>
    ),
  },
];

// ── Dashboard page ────────────────────────────────────────────────────────────
export default function Dashboard() {
  const [dateRange, setDateRange] = useState([
    dayjs().startOf("month"),
    dayjs().endOf("month"),
  ]);
  const [chartPeriod, setChartPeriod] = useState("day");

  const params = useMemo(
    () =>
      dateRange?.[0] && dateRange?.[1]
        ? {
            date_from: dateRange[0].format("YYYY-MM-DD"),
            date_to: dateRange[1].format("YYYY-MM-DD"),
          }
        : undefined,
    [dateRange],
  );

  const { data, isLoading, isError, refetch } = useDashboard(params);

  if (isError)
    return <ErrorState message="Không tải được dữ liệu dashboard" onRetry={refetch} />;

  const stats = data?.stats ?? {};
  const summary = data?.orders_summary ?? {};
  const chartData = groupChartData(data?.orders_chart ?? [], chartPeriod);
  const recentOrders = data?.recent_orders ?? [];
  const siteHealth = data?.site_health ?? {};
  const notifications = data?.notifications ?? [];

  const xFmt =
    chartPeriod === "month"
      ? (d) => dayjs(d).format("MM/YYYY")
      : chartPeriod === "week"
        ? (d) => `T.${dayjs(d).week()}`
        : (d) => dayjs(d).format("DD/MM");

  return (
    <section className="space-y-5 pt-4">
      {/* Page header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-ink">Tổng quan</h1>
        </div>
        <RangePicker
          value={dateRange}
          onChange={(val) => setDateRange(val)}
          format="DD/MM/YYYY"
          allowClear={false}
          className="min-w-56"
        />
      </div>

      {/* ── Stat cards ────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatCard
          icon={ShoppingCart}
          iconBg="bg-amber-500/15"
          iconColor="text-amber-400"
          label="Tổng đơn hàng"
          value={(stats.orders?.total ?? 0).toLocaleString("vi-VN")}
          changePct={stats.orders?.change_pct}
          loading={isLoading}
        />
        <StatCard
          icon={DollarSign}
          iconBg="bg-green-500/15"
          iconColor="text-green-400"
          label="Doanh thu"
          value={formatVND(stats.revenue?.total ?? 0)}
          changePct={stats.revenue?.change_pct}
          loading={isLoading}
        />
        <StatCard
          icon={Package}
          iconBg="bg-blue-500/15"
          iconColor="text-blue-400"
          label="Sản phẩm"
          value={(stats.products?.total ?? 0).toLocaleString("vi-VN")}
          changePct={stats.products?.change_pct}
          loading={isLoading}
        />
        <StatCard
          icon={Users}
          iconBg="bg-purple-500/15"
          iconColor="text-purple-400"
          label="Khách hàng"
          value={(stats.customers?.total ?? 0).toLocaleString("vi-VN")}
          changePct={stats.customers?.change_pct}
          loading={isLoading}
        />
      </div>

      {/* ── Orders chart + Recent orders ──────────────────────────────────── */}
      <div className="grid grid-cols-1 items-stretch gap-4 xl:grid-cols-12">
        <div className="flex flex-col xl:col-span-7">
          <SectionCard
            title="Đơn hàng"
            linkTo="/orders"
            extra={
              <Select
                size="small"
                value={chartPeriod}
                onChange={setChartPeriod}
                options={[
                  { value: "day", label: "Theo ngày" },
                  { value: "week", label: "Theo tuần" },
                  { value: "month", label: "Theo tháng" },
                ]}
                style={{ width: 110 }}
              />
            }
          >
            {isLoading ? (
              <Skeleton active paragraph={{ rows: 6 }} title={false} />
            ) : (
              <>
                <ResponsiveContainer width="100%" height={220}>
                  <AreaChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                    <defs>
                      <linearGradient id="gradOrders" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#978df8" stopOpacity={0.35} />
                        <stop offset="95%" stopColor="#978df8" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#2a2c33" vertical={false} />
                    <XAxis
                      dataKey="date"
                      tickFormatter={xFmt}
                      tick={{ fontSize: 11, fill: "#94a3b8" }}
                      axisLine={false}
                      tickLine={false}
                      interval="preserveStartEnd"
                    />
                    <YAxis
                      tick={{ fontSize: 11, fill: "#94a3b8" }}
                      axisLine={false}
                      tickLine={false}
                      allowDecimals={false}
                    />
                    <Tooltip content={<ChartTooltip />} />
                    <Area
                      type="monotone"
                      dataKey="count"
                      name="Số đơn hàng"
                      stroke="#978df8"
                      strokeWidth={2}
                      fill="url(#gradOrders)"
                      dot={false}
                      activeDot={{ r: 4, strokeWidth: 0 }}
                    />
                  </AreaChart>
                </ResponsiveContainer>

                {/* Status summary */}
                <div className="mt-3 grid grid-cols-4 divide-x divide-border border-t border-border pt-3 text-center">
                  {[
                    { label: "Tổng đơn hàng", value: summary.total ?? 0, cls: "text-ink" },
                    {
                      label: "Hoàn thành",
                      value: summary.completed?.count ?? 0,
                      pct: summary.completed?.pct ?? 0,
                      cls: "text-success",
                    },
                    {
                      label: "Đang xử lý",
                      value: summary.processing?.count ?? 0,
                      pct: summary.processing?.pct ?? 0,
                      cls: "text-warning",
                    },
                    {
                      label: "Đã hủy",
                      value: summary.cancelled?.count ?? 0,
                      pct: summary.cancelled?.pct ?? 0,
                      cls: "text-danger",
                    },
                  ].map(({ label, value, pct, cls }) => (
                    <div key={label}>
                      <p className="text-xs text-muted">{label}</p>
                      <p className={`mt-0.5 text-base font-bold ${cls}`}>
                        {value.toLocaleString("vi-VN")}
                        {pct != null && (
                          <span className="ml-1 text-xs font-normal">({pct}%)</span>
                        )}
                      </p>
                    </div>
                  ))}
                </div>
              </>
            )}
          </SectionCard>
        </div>

        <div className="flex flex-col xl:col-span-5">
          <SectionCard title="Đơn hàng mới nhất" linkTo="/orders">
            {isLoading ? (
              <Skeleton active paragraph={{ rows: 5 }} title={false} />
            ) : (
              <Table
                dataSource={recentOrders}
                columns={recentOrderCols}
                rowKey="id"
                pagination={false}
                size="small"
                locale={{ emptyText: "Chưa có đơn hàng" }}
              />
            )}
          </SectionCard>
        </div>
      </div>

      {/* ── Monitor + Notifications ───────────────────────────────────────── */}
      <div className="grid grid-cols-1 items-stretch gap-4 xl:grid-cols-12">
        <div className="flex flex-col xl:col-span-7">
          <SectionCard title="Monitor hệ thống" linkTo="/sites">
            {isLoading ? (
              <Skeleton active paragraph={{ rows: 6 }} title={false} />
            ) : (
              <>
                {/* Counters row */}
                <div className="mb-4 grid grid-cols-4 gap-2">
                  {[
                    { label: "Tổng hệ thống", value: siteHealth.total ?? 0, dot: null },
                    { label: "Đang hoạt động", value: siteHealth.up ?? 0, dot: "bg-green-500" },
                    { label: "Cảnh báo", value: siteHealth.warning ?? 0, dot: "bg-amber-500" },
                    {
                      label: "Ngừng hoạt động",
                      value: siteHealth.down ?? 0,
                      dot: "bg-red-500",
                    },
                  ].map(({ label, value, dot }) => (
                    <div key={label} className="rounded-lg bg-surface-muted px-3 py-2 text-center">
                      <div className="flex items-center justify-center gap-1">
                        {dot && (
                          <span className={`h-2 w-2 rounded-full ${dot}`} />
                        )}
                        <span className="text-xl font-bold text-ink">{value}</span>
                      </div>
                      <p className="mt-0.5 text-xs text-muted">{label}</p>
                    </div>
                  ))}
                </div>

                <Table
                  dataSource={siteHealth.sites ?? []}
                  columns={monitorCols}
                  rowKey="id"
                  pagination={false}
                  size="small"
                  locale={{ emptyText: "Chưa có hệ thống nào" }}
                />
              </>
            )}
          </SectionCard>
        </div>

        <div className="flex flex-col xl:col-span-5">
          <SectionCard title="Thông báo hệ thống" linkTo="/health-checks">
            {isLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 4 }, (_, i) => (
                  <div key={i} className="flex items-start gap-3">
                    <Skeleton.Avatar active size={32} shape="circle" />
                    <div className="flex-1 space-y-1.5">
                      <Skeleton.Input active size="small" block style={{ height: 13 }} />
                      <Skeleton.Input
                        active
                        size="small"
                        style={{ width: "70%", height: 13 }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            ) : notifications.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted">Không có thông báo</p>
            ) : (
              <ul className="divide-y divide-border">
                {notifications.map((n, i) => (
                  <li key={i} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
                    <NotifIcon type={n.type} />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium leading-tight text-ink">{n.title}</p>
                      <p className="mt-0.5 text-xs leading-relaxed text-muted">
                        {n.message}
                      </p>
                    </div>
                    <span className="shrink-0 text-xs text-muted">
                      {formatDateTime(n.time)?.split(" ")[1] ?? ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>
        </div>
      </div>
    </section>
  );
}
