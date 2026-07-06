import { Button, Input, Select } from "antd";
import { Globe, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import { useDomainInfoList, useRefreshAllDomainInfo } from "../api/domainInfo.js";
import { useCan } from "../lib/AuthContext.jsx";
import DataTable from "../components/DataTable.jsx";
import DomainInfoModal from "../components/DomainInfoModal.jsx";
import {
  BlacklistBadge,
  CheckStatusBadge,
  ExpiryBadge,
} from "../components/DomainStatusBadge.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ErrorState from "../components/ErrorState.jsx";
import { formatDate } from "../lib/format.js";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

const VERDICT_OPTIONS = [
  { value: "all", label: "Tất cả blacklist" },
  { value: "clean", label: "Sạch" },
  { value: "listed", label: "Bị liệt kê" },
  { value: "unknown", label: "Không xác định" },
];

// Aggregate "Tên miền" screen: every site's domain snapshot in one table,
// sorted by soonest expiry so renewals surface first. A row opens the per-site
// DomainInfoModal for the full WHOIS/DNS/SSL/blacklist/index detail.
export default function Domains() {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [verdictFilter, setVerdictFilter] = useState("all");
  const [ordering, setOrdering] = useState("ssl_not_after");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [detailSite, setDetailSite] = useState(null);

  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(t);
  }, [searchInput]);

  const params = useMemo(
    () => ({
      search: search || undefined,
      blacklist_verdict: verdictFilter === "all" ? undefined : verdictFilter,
      ordering,
      page,
      page_size: pageSize,
    }),
    [search, verdictFilter, ordering, page, pageSize]
  );

  const { data, isLoading, isFetching, isError, refetch } = useDomainInfoList(params);
  const refreshAll = useRefreshAllDomainInfo();
  const canRefresh = useCan()("domains.refresh_domaininfo");

  const rows = data?.results ?? [];
  const total = data?.count ?? 0;

  const handleRefreshAll = () => {
    refreshAll.mutate(undefined, {
      onSuccess: () =>
        toast.success("Đã kích hoạt kiểm tra lại toàn bộ tên miền."),
      onError: () => toast.error("Kích hoạt thất bại."),
    });
  };

  // Server-sortable columns: ssl_not_after, whois_expires_at, last_refreshed_at.
  const handleTableChange = (pagination, _filters, sorter) => {
    let next = ordering;
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
      key: "site",
      title: "Website / Tên miền",
      width: 260,
      render: (_v, r) => (
        <div className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-500/15 text-info">
            <Globe size={15} />
          </span>
          <div className="min-w-0">
            <p className="truncate font-medium">{r.site_name}</p>
            <p className="truncate font-mono text-xs text-muted">{r.domain}</p>
          </div>
        </div>
      ),
    },
    {
      key: "whois_expires_at",
      dataIndex: "whois_expires_at",
      title: "Hết hạn tên miền",
      width: 200,
      sorter: true,
      sortOrder: sortOrder("whois_expires_at"),
      render: (v, r) =>
        r.whois_status === "unsupported" ? (
          <CheckStatusBadge status="unsupported" />
        ) : (
          <div className="flex flex-col gap-1">
            <span className="tabular-nums text-muted">{formatDate(v)}</span>
            <ExpiryBadge days={r.whois_days_remaining} />
          </div>
        ),
    },
    {
      key: "ssl_not_after",
      dataIndex: "ssl_not_after",
      title: "Hết hạn SSL",
      width: 200,
      sorter: true,
      sortOrder: sortOrder("ssl_not_after"),
      render: (v, r) => (
        <div className="flex flex-col gap-1">
          <span className="tabular-nums text-muted">{formatDate(v)}</span>
          <ExpiryBadge days={r.ssl_days_remaining} />
        </div>
      ),
    },
    {
      key: "blacklist",
      dataIndex: "blacklist_verdict",
      title: "Blacklist",
      width: 150,
      ellipsis: false,
      render: (v) => <BlacklistBadge verdict={v} />,
    },
    {
      key: "gindex",
      dataIndex: "gindex_status",
      title: "Google Index",
      width: 150,
      ellipsis: false,
      render: (status, r) => {
        if (status === "ok") {
          return r.gindex_indexed ? (
            <CheckStatusBadge status="ok" label="Đã index" />
          ) : (
            <CheckStatusBadge status="error" label="Chưa index" />
          );
        }
        return <CheckStatusBadge status={status} />;
      },
    },
    {
      key: "last_refreshed_at",
      dataIndex: "last_refreshed_at",
      title: "Kiểm tra lúc",
      width: 170,
      sorter: true,
      sortOrder: sortOrder("last_refreshed_at"),
      render: (v) => <span className="tabular-nums text-muted">{formatDate(v)}</span>,
    },
    {
      key: "actions",
      title: "Thao tác",
      width: 120,
      align: "right",
      hideable: false,
      ellipsis: false,
      render: (_v, r) => (
        <Button
          type="link"
          size="small"
          onClick={() => setDetailSite({ id: r.site, name: r.site_name })}
        >
          Chi tiết
        </Button>
      ),
    },
  ];

  const filterActive = search !== "" || verdictFilter !== "all";

  return (
    <section className="pt-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-1.5">
        <h1 className="font-display text-2xl font-bold">Quản lý tên miền</h1>
        {canRefresh && (
          <Button
            type="primary"
            ghost
            icon={<RefreshCw size={16} />}
            loading={refreshAll.isPending}
            onClick={handleRefreshAll}
          >
            Kiểm tra lại tất cả
          </Button>
        )}
      </div>

      <div className="mb-2.5 flex flex-wrap items-center gap-2">
        <Select
          value={verdictFilter}
          onChange={(v) => {
            setVerdictFilter(v);
            setPage(1);
          }}
          options={VERDICT_OPTIONS}
          className="min-w-44"
        />
      </div>

      {isError ? (
        <ErrorState message="Không tải được danh sách tên miền" onRetry={refetch} />
      ) : (
        <div className="rounded bg-surface-raised p-2.5 border border-border">
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
                placeholder="Tìm theo tên miền, website…"
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
                  title={filterActive ? "Không có tên miền phù hợp" : "Chưa có dữ liệu tên miền"}
                  hint={
                    filterActive
                      ? "Thử đổi từ khóa hoặc bộ lọc."
                      : "Bấm “Kiểm tra lại tất cả” để bắt đầu tra cứu WHOIS/DNS/SSL cho các website."
                  }
                />
              ),
            }}
          />
        </div>
      )}

      <DomainInfoModal
        site={detailSite}
        open={detailSite != null}
        onClose={() => setDetailSite(null)}
      />
    </section>
  );
}
