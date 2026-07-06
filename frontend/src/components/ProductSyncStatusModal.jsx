import { Button, Input, Modal, Select, Table, Tag } from "antd";
import { Star } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import { useProductSyncStatus, useSyncProducts } from "../api/products.js";
import { useCan } from "../lib/AuthContext.jsx";
import { formatDate } from "../lib/format.js";
import { PUSH_CONFIRM_WORD, PUSH_EMAIL_NOTICE } from "../lib/productSync.js";
import { usePushNotifications } from "../lib/PushNotificationContext.jsx";
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
  const { notifyStarted } = usePushNotifications();
  // Read-only view when the user can't push — hide the push controls.
  const canPush = useCan()("catalog.push_masterproduct");

  const [selected, setSelected] = useState([]);
  const [statusFilter, setStatusFilter] = useState("all"); // "all" | "up" | "down" | "unknown"
  const [primaryFilter, setPrimaryFilter] = useState("all"); // "all" | "true" | "false"
  const [hostingFilter, setHostingFilter] = useState("all"); // "all" | "none" | String(hosting_id)
  const [search, setSearch] = useState(""); // domain search, client-side
  const [confirmOpen, setConfirmOpen] = useState(false); // type-PUSH confirm step
  const [confirmText, setConfirmText] = useState("");

  // Reset selection + filters whenever the panel (re)opens or switches product.
  useEffect(() => {
    if (open) {
      setSelected([]);
      setStatusFilter("all");
      setPrimaryFilter("all");
      setHostingFilter("all");
      setSearch("");
      setConfirmOpen(false);
      setConfirmText("");
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

  // Hosting filter options: distinct hostings (labelled by username since many
  // share a name), sorted by username. "Không có hosting" only appears when some
  // site is unassigned.
  const hostingOptions = useMemo(() => {
    const byId = new Map();
    let hasNone = false;
    for (const r of rows) {
      if (r.hosting_id == null) {
        hasNone = true;
      } else if (!byId.has(r.hosting_id)) {
        byId.set(r.hosting_id, r.hosting_username || "(không tên)");
      }
    }
    const options = [{ value: "all", label: "Tất cả hosting" }];
    [...byId.entries()]
      .sort((a, b) => a[1].localeCompare(b[1]))
      .forEach(([hid, label]) => options.push({ value: String(hid), label }));
    if (hasNone) options.push({ value: "none", label: "Không có hosting" });
    return options;
  }, [rows]);

  // Client-side filters (the list is small and unpaginated): website status,
  // trang chính/thường, hosting, and domain search.
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return sorted.filter(
      (r) =>
        (statusFilter === "all" || r.site_status === statusFilter) &&
        (primaryFilter === "all" || String(!!r.is_primary) === primaryFilter) &&
        (hostingFilter === "all" ||
          (hostingFilter === "none"
            ? r.hosting_id == null
            : String(r.hosting_id) === hostingFilter)) &&
        (!q || domainOf(r.site_url).toLowerCase().includes(q))
    );
  }, [sorted, statusFilter, primaryFilter, hostingFilter, search]);

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

  // Push is long-running (fans out to each site) and reported by email, so the
  // button opens a type-PUSH confirm step instead of pushing directly.
  const openConfirm = () => {
    if (!selected.length) return;
    setConfirmText("");
    setConfirmOpen(true);
  };

  const handleConfirmSync = () => {
    if (confirmText.trim().toUpperCase() !== PUSH_CONFIRM_WORD) return;
    sync.mutate(
      { sites: selected, products: [id] },
      {
        onSuccess: (res) => {
          toast.success("Đã kích hoạt đồng bộ. Kết quả sẽ được gửi qua email.");
          setConfirmOpen(false);
          setConfirmText("");
          setSelected([]);
          notifyStarted(res.run_id);
          // Fire-and-forget: close the panel, no polling — the report arrives by email.
          onClose();
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
          {r.hosting_username && (
            <div className="truncate text-xs text-muted">
              hosting: {r.hosting_username}
            </div>
          )}
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
        <span className="rounded-full bg-blue-500/15 px-2.5 py-0.5 text-xs font-semibold text-info">
          {syncedCount}/{rows.length} site
        </span>
      )}
    </div>
  );

  const footer = (
    <div className="flex items-center justify-between gap-1.5">
      <div className="flex items-center gap-2">
        {canPush && (
          <Button
            type="text"
            size="small"
            disabled={!unsyncedIds.length}
            onClick={selectUnsynced}
          >
            Chọn site chưa đồng bộ
          </Button>
        )}
        {hiddenSelectedCount > 0 && (
          <span className="text-xs text-muted">
            +{hiddenSelectedCount} site đã chọn đang ẩn bởi bộ lọc
          </span>
        )}
      </div>
      <div className="flex gap-1.5">
        <Button onClick={onClose}>Đóng</Button>
        {canPush && (
          <Button
            type="primary"
            disabled={!selected.length}
            loading={sync.isPending}
            onClick={openConfirm}
          >
            Đồng bộ site đã chọn{selected.length ? ` (${selected.length})` : ""}
          </Button>
        )}
      </div>
    </div>
  );

  return (
    <>
    <Modal open={open} onCancel={onClose} footer={footer} title={title} width={1040}>
      {product && (
        <div className="mt-2">
          <p className="mb-2 truncate text-sm text-muted">
            {product.name} — <span className="font-mono">{product.sku}</span>
          </p>
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
            <div className="w-full sm:w-52">
              <label className="mb-1.5 block text-sm font-medium text-muted">
                Hosting
              </label>
              <Select
                size="large"
                showSearch
                optionFilterProp="label"
                value={hostingFilter}
                onChange={setHostingFilter}
                className="w-full"
                options={hostingOptions}
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
            rowSelection={
              canPush
                ? {
                    selectedRowKeys: selected,
                    onChange: setSelected,
                    // Keep keys that leave the filtered dataSource so ticking
                    // sites under one search doesn't drop sites ticked under
                    // another.
                    preserveSelectedRowKeys: true,
                  }
                : undefined
            }
            locale={{ emptyText: "Không có website phù hợp bộ lọc." }}
          />
        </div>
      )}
    </Modal>

    <Modal
      open={confirmOpen}
      onCancel={() => setConfirmOpen(false)}
      title="Xác nhận đồng bộ sản phẩm"
      okText="Đồng bộ ngay"
      cancelText="Hủy"
      okButtonProps={{
        danger: true,
        loading: sync.isPending,
        disabled: confirmText.trim().toUpperCase() !== PUSH_CONFIRM_WORD,
      }}
      onOk={handleConfirmSync}
      maskClosable={false}
      destroyOnClose
    >
      <p className="mb-3 text-sm text-ink">{PUSH_EMAIL_NOTICE}</p>
      <p className="mb-2 text-sm text-muted">
        Nhập <span className="font-mono font-semibold">{PUSH_CONFIRM_WORD}</span> để tiến hành đẩy
        {selected.length ? ` ${selected.length}` : ""} site đã chọn.
      </p>
      <Input
        autoFocus
        value={confirmText}
        placeholder={PUSH_CONFIRM_WORD}
        onChange={(e) => setConfirmText(e.target.value)}
        onPressEnter={handleConfirmSync}
      />
    </Modal>
    </>
  );
}
