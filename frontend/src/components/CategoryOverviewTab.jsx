import { Button, Input, Select } from "antd";
import { Boxes, FolderTree, Globe, Link2, Unlink } from "lucide-react";
import { useEffect, useState } from "react";

import { useCategoryMatrix, useCategoryOverview } from "../api/products.js";
import { useAllSites } from "../api/sites.js";
import { useCategoryRuns } from "../api/syncReports.js";
import { formatDate } from "../lib/format.js";
import { RunStatusTag } from "./CategoryRunDetailModal.jsx";
import DataTable from "./DataTable.jsx";
import EmptyState from "./EmptyState.jsx";
import ErrorState from "./ErrorState.jsx";
import StatCards from "./StatCards.jsx";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const SORT_FIELDS = { name: "name", linked_site_count: "linked_site_count" };
const vi = (n) => (n ?? 0).toLocaleString("vi-VN");

// "Tổng quan" tab: dashboard stat cards + a quick scoped pull + recent runs +
// the cross-site matrix (one row per Hub category, one column per site, each
// cell = ID + tên RAW on that site). All four blocks render dynamically off the
// backend (overview / matrix / category-runs). `onPull(siteIds)`/`pulling` are
// owned by the page so the pull + run-polling stays in one place.
export default function CategoryOverviewTab({ onPull, pulling }) {
  const [pullSite, setPullSite] = useState(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [ordering, setOrdering] = useState(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(t);
  }, [searchInput]);

  const overview = useCategoryOverview();
  const { data: sites = [], isLoading: sitesLoading } = useAllSites();
  const recent = useCategoryRuns({ page_size: 5 });
  const matrix = useCategoryMatrix({
    page,
    page_size: pageSize,
    ordering: ordering ?? undefined,
    search: search || undefined,
  });

  const o = overview.data ?? {};
  const cards = [
    {
      key: "hub_used",
      label: "Danh mục Hub (đang dùng)",
      value: vi(o.hub_used),
      sub: `Trong tổng số ${vi(o.hub_total)} danh mục`,
      Icon: Boxes,
      tint: "bg-blue-50 text-blue-500",
    },
    {
      key: "linked",
      label: "Đã liên kết ít nhất 1 site",
      value: vi(o.linked),
      sub: `${o.linked_pct ?? 0}%`,
      Icon: Link2,
      tint: "bg-green-50 text-success",
    },
    {
      key: "unlinked",
      label: "Chưa có trên site nào",
      value: vi(o.unlinked),
      sub: o.hub_used ? `${(100 - (o.linked_pct ?? 0)).toFixed(1)}%` : "—",
      Icon: Unlink,
      tint: "bg-amber-50 text-warning",
    },
    {
      key: "sites",
      label: "Site đang quản lý",
      value: vi(o.site_count),
      sub: "Đã kết nối",
      Icon: Globe,
      tint: "bg-violet-50 text-violet-500",
    },
  ];

  const matrixSites = matrix.data?.sites ?? [];
  const rows = matrix.data?.results ?? [];
  const total = matrix.data?.count ?? 0;

  const handleTableChange = (pagination, _f, sorter) => {
    const field = SORT_FIELDS[sorter?.columnKey];
    const next =
      !sorter?.order || !field ? null : sorter.order === "ascend" ? field : `-${field}`;
    const resets = pagination.pageSize !== pageSize || next !== ordering;
    setOrdering(next);
    setPageSize(pagination.pageSize);
    setPage(resets ? 1 : pagination.current);
  };

  const sortOrderFor = (key) => {
    const field = SORT_FIELDS[key];
    return ordering === field ? "ascend" : ordering === `-${field}` ? "descend" : null;
  };

  const columns = [
    {
      key: "name",
      dataIndex: "name",
      title: "Danh mục Hub",
      width: 220,
      fixed: "left",
      sorter: true,
      sortOrder: sortOrderFor("name"),
      render: (v, r) => (
        <span>
          <span className="font-medium">{v}</span>{" "}
          <span className="text-xs text-muted">#{r.id}</span>
        </span>
      ),
    },
    {
      key: "parent_name",
      dataIndex: "parent_name",
      title: "Cha (Hub)",
      width: 160,
      render: (v) => <span className="text-muted">{v ?? "—"}</span>,
    },
    {
      key: "linked_site_count",
      dataIndex: "linked_site_count",
      title: "Số site",
      width: 100,
      align: "right",
      sorter: true,
      sortOrder: sortOrderFor("linked_site_count"),
      render: (v) => (
        <span className="tabular-nums">
          {v} <span className="text-xs text-muted">/ {matrixSites.length}</span>
        </span>
      ),
    },
    ...matrixSites.map((s) => ({
      key: `site-${s.id}`,
      title: s.name,
      width: 170,
      render: (_v, r) => {
        const cell = r.cells?.[String(s.id)];
        if (!cell) return <span className="text-muted">—</span>;
        return (
          <div className="min-w-0">
            <p className="tabular-nums text-xs text-muted">ID: {cell.woo_id}</p>
            <p className="truncate">{cell.woo_name || "—"}</p>
          </div>
        );
      },
    })),
  ];

  return (
    <div className="flex flex-col gap-3">
      <StatCards cards={cards} loading={overview.isLoading} columns={4} />

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        {/* Scoped pull (Woo → Hub) */}
        <div className="rounded bg-white p-3 shadow-card">
          <h3 className="font-display text-base font-semibold">Đồng bộ danh mục từ website (PULL)</h3>
          <p className="mt-1 text-sm text-muted">
            Kéo danh mục từ một website về Hub. Dữ liệu được gộp, chuẩn hóa và dựng
            cây cha–con.
          </p>
          <p className="mt-3 text-sm text-muted">Chọn website</p>
          <Select
            showSearch
            allowClear
            loading={sitesLoading}
            value={pullSite}
            placeholder="Chọn website"
            optionFilterProp="label"
            className="mt-1 w-full"
            onChange={(v) => setPullSite(v ?? null)}
            options={sites.map((s) => ({ value: s.id, label: s.name }))}
          />
          <Button
            type="primary"
            block
            className="mt-2"
            disabled={!pullSite}
            loading={pulling}
            onClick={() => onPull([pullSite])}
          >
            Đồng bộ ngay
          </Button>
        </div>

        {/* Recent runs */}
        <div className="rounded bg-white p-3 shadow-card lg:col-span-2">
          <h3 className="font-display text-base font-semibold">Lịch sử đồng bộ gần đây</h3>
          {recent.isError ? (
            <ErrorState message="Không tải được lịch sử" onRetry={recent.refetch} />
          ) : (recent.data?.results ?? []).length === 0 && !recent.isLoading ? (
            <EmptyState title="Chưa có lần đồng bộ nào" />
          ) : (
            <ul className="mt-2 divide-y">
              {(recent.data?.results ?? []).map((r) => (
                <li key={r.run_id} className="flex items-center gap-3 py-2">
                  <FolderTree size={18} className="shrink-0 text-muted" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">
                      {r.site_label ?? `${r.site_count} site`}
                    </p>
                    <p className="text-xs text-muted">
                      {r.total_pulled} danh mục · {formatDate(r.started_at)}
                    </p>
                  </div>
                  <RunStatusTag status={r.status} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Cross-site matrix */}
      {matrix.isError ? (
        <ErrorState message="Không tải được ma trận danh mục" onRetry={matrix.refetch} />
      ) : (
        <div className="rounded bg-white p-2.5 shadow-card">
          <DataTable
            columns={columns}
            dataSource={rows}
            rowKey="id"
            size="middle"
            loading={matrix.isLoading || matrix.isFetching}
            onRefresh={matrix.refetch}
            refreshing={matrix.isFetching}
            title={<span className="font-display font-semibold">Danh sách danh mục</span>}
            searchSlot={
              <Input.Search
                allowClear
                placeholder="Tìm theo tên Hub hoặc tên cha…"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="w-72"
              />
            }
            onChange={handleTableChange}
            scroll={{ x: "max-content" }}
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              pageSizeOptions: PAGE_SIZE_OPTIONS,
              showTotal: (t, range) => `${range[0]}–${range[1]} trên ${t}`,
            }}
            locale={{
              emptyText: (
                <EmptyState
                  title={search ? "Không có danh mục phù hợp" : "Chưa có danh mục nào"}
                  hint={
                    search
                      ? "Thử đổi từ khóa tìm kiếm."
                      : "Bấm “Đồng bộ danh mục” và chọn site để kéo danh mục về."
                  }
                />
              ),
            }}
          />
        </div>
      )}
    </div>
  );
}
