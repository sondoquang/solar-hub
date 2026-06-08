import { Button, Modal, Table, Tag } from "antd";
import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import { useProductSyncStatus, useSyncProducts } from "../api/products.js";
import { formatDate } from "../lib/format.js";

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

  // Reset the selection whenever the panel (re)opens or switches product.
  useEffect(() => {
    if (open) setSelected([]);
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

  const unsyncedIds = useMemo(
    () => sorted.filter((r) => !r.synced).map((r) => r.site_id),
    [sorted]
  );

  const selectUnsynced = () => setSelected(unsyncedIds);

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
      render: (_v, r) => <span className="font-medium">{r.site_name}</span>,
    },
    {
      key: "synced",
      title: "Trạng thái",
      width: 140,
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
    <Modal open={open} onCancel={onClose} footer={footer} title={title} width={720}>
      {product && (
        <div className="mt-2">
          <p className="mb-2 truncate text-sm text-muted">
            {product.name} — <span className="font-mono">{product.sku}</span>
          </p>
          <Table
            rowKey="site_id"
            size="small"
            loading={isLoading}
            columns={columns}
            dataSource={sorted}
            pagination={false}
            scroll={{ y: 360 }}
            rowSelection={{
              selectedRowKeys: selected,
              onChange: setSelected,
            }}
          />
        </div>
      )}
    </Modal>
  );
}
