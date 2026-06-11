import { Button, Input, Modal, Select, Table, Tag } from "antd";
import { Star } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import { useProductSyncStatus, useSyncProducts } from "../api/products.js";
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

  const selectUnsynced = () => setSelected(unsyncedIds);

  // Changing any filter prunes hidden selections so "Đồng bộ site đã chọn"
  // never pushes to a site the user can no longer see.
  useEffect(() => {
    const ids = new Set(visible.map((r) => r.site_id));
    setSelected((prev) =>
      prev.every((sid) => ids.has(sid)) ? prev : prev.filter((sid) => ids.has(sid))
    );
  }, [visible]);

  const handleSync = () => {
    if (!selected.length) return;
    sync.mutate(
      { sites: selected, products: [id] },
      {
        onSuccess: () => {
          toast.success("Đã kích hoạt đồng bộ xuống các site đã chọn.");
          setSelected([]);
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
      title: "Woo ID",
      width: 100,
      align: "right",
      render: (_v, r) => (
        <span className="tabular-nums text-muted">{r.woo_product_id ?? "—"}</span>
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
        <span className="rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-600">
          {syncedCount}/{rows.length} site
        </span>
      )}
    </div>
  );

  const footer = (
    <div className="flex items-center justify-between gap-1.5">
      <Button
        type="text"
        size="small"
        disabled={!unsyncedIds.length}
        onClick={selectUnsynced}
      >
        Chọn site chưa đồng bộ
      </Button>
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
    <Modal open={open} onCancel={onClose} footer={footer} title={title} width={800}>
      {product && (
        <div className="mt-2">
          <p className="mb-2 truncate text-sm text-muted">
            {product.name} — <span className="font-mono">{product.sku}</span>
          </p>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Input
              size="small"
              allowClear
              placeholder="Tìm theo domain..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-56"
            />
            <div className="ml-auto flex items-center gap-2">
              <span className="text-sm text-muted">Loại trang:</span>
              <Select
                size="small"
                value={primaryFilter}
                onChange={setPrimaryFilter}
                className="min-w-32"
                options={[
                  { value: "all", label: "Tất cả" },
                  { value: "true", label: "Trang chính" },
                  { value: "false", label: "Trang thường" },
                ]}
              />
              <span className="text-sm text-muted">Trạng thái web:</span>
              <Select
                size="small"
                value={statusFilter}
                onChange={setStatusFilter}
                className="min-w-36"
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
            scroll={{ y: 360 }}
            rowSelection={{
              selectedRowKeys: selected,
              onChange: setSelected,
            }}
            locale={{ emptyText: "Không có website phù hợp bộ lọc." }}
          />
        </div>
      )}
    </Modal>
  );
}
