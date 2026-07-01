import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Input, Modal, Select, Table, Tag } from "antd";
import { Star } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import { useProductSyncStatus, useSyncProducts } from "../api/products.js";
import { SYNC_OPS, useSyncRunProgress } from "../api/syncReports.js";
import { formatDate } from "../lib/format.js";
import StatusDot from "./StatusDot.jsx";

// Hostname for display + domain search; falls back to the raw URL if unparsable.
function domainOf(url) {
  try {
    return new URL(url).hostname;
  } catch {
    return url || "";
  }
}

// Per-product sync panel: lists every active site with its sync state for this
// product (đã/chưa đồng bộ + thời gian), and lets the user push selected sites.
// Mirrors OrderDetailModal's modal shell (title + content + footer buttons).
// Rows come ready-joined from GET /products/{id}/sync_status/ — the backend
// left-joins the product's mappings against all active sites.
export default function ProductSyncStatusModal({ product, open, onClose }) {
  const id = product?.id;
  const { data: rows = [], isLoading } = useProductSyncStatus(id, { enabled: open });
  const sync = useSyncProducts();
  const qc = useQueryClient();

  // "Đang đồng bộ… X/Y site" banner for the per-product push, so the user sees
  // it run to completion before closing; refresh this product's sync state at
  // the end so the đã/chưa-đồng-bộ tags update.
  const pushRun = useSyncRunProgress(SYNC_OPS.products, {
    onFinish: ({ finished, timedOut, expected, errorCount }) => {
      if (timedOut) {
        toast("Đồng bộ chạy lâu hơn dự kiến — kiểm tra lại sau.", { icon: "⏳" });
      } else if (errorCount) {
        toast(`Đồng bộ xong, ${errorCount}/${expected} site lỗi.`, { icon: "⚠️" });
      } else if (finished) {
        toast.success(`Đã đồng bộ xuống ${expected} site.`);
      }
      qc.invalidateQueries({ queryKey: ["products", "sync_status", id] });
    },
  });

  const [selected, setSelected] = useState([]);
  const [statusFilter, setStatusFilter] = useState("all"); // "all" | "up" | "down" | "unknown"
  const [primaryFilter, setPrimaryFilter] = useState("all"); // "all" | "true" | "false"
  const [search, setSearch] = useState(""); // domain search, client-side

  // Reset selection + filters whenever the panel (re)opens or switches product.
  useEffect(() => {
    if (open) {
      setSelected([]);
      setStatusFilter("all");
      setPrimaryFilter("all");
      setSearch("");
    }
  }, [open, id]);

  // Not-synced first (action-oriented), then by site name.
  const sorted = useMemo(
    () =>
      [...rows].sort(
        (a, b) =>
          Number(a.synced) - Number(b.synced) ||
          a.site_name.localeCompare(b.site_name)
      ),
    [rows]
  );

  // Client-side filters (the list is small and unpaginated): website status,
  // trang chính/thường, and domain search.
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return sorted.filter(
      (r) =>
        (statusFilter === "all" || r.site_status === statusFilter) &&
        (primaryFilter === "all" || String(!!r.is_primary) === primaryFilter) &&
        (!q || domainOf(r.site_url).toLowerCase().includes(q))
    );
  }, [sorted, statusFilter, primaryFilter, search]);

  const unsyncedIds = useMemo(
    () => visible.filter((r) => !r.synced).map((r) => r.site_id),
    [visible]
  );

  // Add the currently-visible unsynced sites to the selection (union) instead of
  // replacing it — consistent with the accumulate behavior below.
  const selectUnsynced = () =>
    setSelected((prev) => [...new Set([...prev, ...unsyncedIds])]);

  // Selection accumulates across searches/filters: the user can search, tick a
  // few sites, search again and tick more, and the earlier picks survive. It's
  // only reset when the panel reopens or switches product (the effect above).
  // `hiddenSelectedCount` surfaces in the footer so the user knows the push
  // includes selected sites the current filter is hiding.
  const visibleIds = useMemo(() => new Set(visible.map((r) => r.site_id)), [visible]);
  const hiddenSelectedCount = selected.filter((sid) => !visibleIds.has(sid)).length;

  const handleSync = () => {
    if (!selected.length) return;
    sync.mutate(
      { sites: selected, products: [id] },
      {
        onSuccess: (res) => {
          toast.success("Đã kích hoạt đồng bộ xuống các site đã chọn.");
          setSelected([]);
          pushRun.start({ runId: res.run_id, expected: res.expected });
        },
        onError: () => toast.error("Kích hoạt đồng bộ thất bại."),
      }
    );
  };

  const columns = [
    {
      key: "site",
      title: "Website",
      render: (_v, r) => (
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="font-medium">{r.site_name}</span>
            {r.is_primary && (
              <Star
                size={13}
                aria-label="Trang chính"
                className="shrink-0 fill-amber-400 text-amber-400"
              />
            )}
          </div>
          <div className="truncate text-xs text-muted">{domainOf(r.site_url)}</div>
        </div>
      ),
    },
    {
      key: "site_status",
      title: "Trạng thái web",
      width: 150,
      render: (_v, r) => <StatusDot status={r.site_status} />,
    },
    {
      key: "synced",
      title: "Đồng bộ",
      width: 130,
      render: (_v, r) =>
        r.synced ? (
          <Tag color="success">Đã đồng bộ</Tag>
        ) : (
          <Tag>Chưa đồng bộ</Tag>
        ),
    },
    {
      key: "woo",
      title: "ID trên site",
      width: 110,
      align: "right",
      // woo_product_id is the generic per-site remote id (WooCommerce or Sapo
      // product id) — the API field name is kept for compatibility.
      render: (_v, r) => (
        <span className="tabular-nums text-muted">
          {r.woo_product_id ?? "—"}
          {r.platform === "sapo" && r.woo_product_id != null && (
            <span className="ml-1 text-xs text-muted">(Sapo)</span>
          )}
        </span>
      ),
    },
    {
      key: "last",
      title: "Đồng bộ lần cuối",
      width: 170,
      render: (_v, r) => (
        <span className="tabular-nums text-muted">
          {r.last_synced_at ? formatDate(r.last_synced_at) : "—"}
        </span>
      ),
    },
  ];

  const syncedCount = rows.filter((r) => r.synced).length;

  const title = (
    <div className="flex items-center gap-2">
      <span>Trạng thái đồng bộ</span>
      {product && (
        <span className="rounded-full bg-blue-500/15 px-2.5 py-0.5 text-xs font-semibold text-blue-300">
          {syncedCount}/{rows.length} site
        </span>
      )}
    </div>
  );

  const footer = (
    <div className="flex items-center justify-between gap-1.5">
      <div className="flex items-center gap-2">
        <Button
          type="text"
          size="small"
          disabled={!unsyncedIds.length}
          onClick={selectUnsynced}
        >
          Chọn site chưa đồng bộ
        </Button>
        {hiddenSelectedCount > 0 && (
          <span className="text-xs text-muted">
            +{hiddenSelectedCount} site đã chọn đang ẩn bởi bộ lọc
          </span>
        )}
      </div>
      <div className="flex gap-1.5">
        <Button onClick={onClose}>Đóng</Button>
        <Button
          type="primary"
          disabled={!selected.length}
          loading={sync.isPending}
          onClick={handleSync}
        >
          Đồng bộ site đã chọn{selected.length ? ` (${selected.length})` : ""}
        </Button>
      </div>
    </div>
  );

  return (
    <Modal open={open} onCancel={onClose} footer={footer} title={title} width={1040}>
      {product && (
        <div className="mt-2">
          <p className="mb-2 truncate text-sm text-muted">
            {product.name} — <span className="font-mono">{product.sku}</span>
          </p>
          {pushRun.activeRun && (
            <Alert
              type="info"
              showIcon
              className="mb-2"
              message={`Đang đồng bộ… ${pushRun.doneSites}/${pushRun.activeRun.expected} site hoàn tất.`}
            />
          )}
          <div className="mb-3 flex flex-wrap items-end gap-3">
            <div className="min-w-[240px] flex-1">
              <label className="mb-1.5 block text-sm font-medium text-muted">
                Tìm theo domain
              </label>
              <Input
                size="large"
                allowClear
                placeholder="Tìm theo domain..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full"
              />
            </div>
            <div className="w-full sm:w-52">
              <label className="mb-1.5 block text-sm font-medium text-muted">
                Loại trang
              </label>
              <Select
                size="large"
                value={primaryFilter}
                onChange={setPrimaryFilter}
                className="w-full"
                options={[
                  { value: "all", label: "Tất cả" },
                  { value: "true", label: "Trang chính" },
                  { value: "false", label: "Trang thường" },
                ]}
              />
            </div>
            <div className="w-full sm:w-52">
              <label className="mb-1.5 block text-sm font-medium text-muted">
                Trạng thái web
              </label>
              <Select
                size="large"
                value={statusFilter}
                onChange={setStatusFilter}
                className="w-full"
                options={[
                  { value: "all", label: "Tất cả" },
                  { value: "up", label: "Hoạt động" },
                  { value: "down", label: "Không hoạt động" },
                  { value: "unknown", label: "Chưa kiểm tra" },
                ]}
              />
            </div>
          </div>
          <Table
            rowKey="site_id"
            size="small"
            loading={isLoading}
            columns={columns}
            dataSource={visible}
            pagination={false}
            scroll={{ y: 460 }}
            rowSelection={{
              selectedRowKeys: selected,
              onChange: setSelected,
              // Keep keys that leave the filtered dataSource so ticking sites
              // under one search doesn't drop sites ticked under another.
              preserveSelectedRowKeys: true,
            }}
            locale={{ emptyText: "Không có website phù hợp bộ lọc." }}
          />
        </div>
      )}
    </Modal>
  );
}
