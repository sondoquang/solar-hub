import { Button, Input, Modal, Select, Table } from "antd";
import { Star } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useAllSites } from "../api/sites.js";
import StatusDot from "./StatusDot.jsx";

// Hostname for display + domain search; falls back to the raw URL if unparsable.
function domainOf(url) {
  try {
    return new URL(url).hostname;
  } catch {
    return url || "";
  }
}

// Site picker for the scoped category pull (Woo → Hub): tick the websites to
// pull categories from. Mirrors ProductSyncStatusModal's shell (search +
// filters + checkbox table) but stays presentational — the page owns the
// mutation and the run polling, this only reports `onConfirm(siteIds)`.
export default function CategoryPullModal({ open, onClose, onConfirm, confirming }) {
  const { data: sites = [], isLoading } = useAllSites({ enabled: open });
  const [selected, setSelected] = useState([]);
  const [statusFilter, setStatusFilter] = useState("all"); // "all" | "up" | "down" | "unknown"
  const [primaryFilter, setPrimaryFilter] = useState("all"); // "all" | "true" | "false"
  const [search, setSearch] = useState(""); // domain search, client-side

  // Reset selection + filters whenever the panel (re)opens.
  useEffect(() => {
    if (open) {
      setSelected([]);
      setStatusFilter("all");
      setPrimaryFilter("all");
      setSearch("");
    }
  }, [open]);

  // Primary sites first (the ones whose categories matter most), then by name.
  const sorted = useMemo(
    () =>
      [...sites].sort(
        (a, b) =>
          Number(!!b.is_primary) - Number(!!a.is_primary) ||
          a.name.localeCompare(b.name)
      ),
    [sites]
  );

  // Client-side filters (the whole fleet is loaded once): website status,
  // trang chính/thường, and domain search.
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return sorted.filter(
      (s) =>
        (statusFilter === "all" || s.status === statusFilter) &&
        (primaryFilter === "all" || String(!!s.is_primary) === primaryFilter) &&
        (!q || domainOf(s.base_url).toLowerCase().includes(q))
    );
  }, [sorted, statusFilter, primaryFilter, search]);

  // Changing any filter prunes hidden selections so the pull never targets a
  // site the user can no longer see.
  useEffect(() => {
    const ids = new Set(visible.map((s) => s.id));
    setSelected((prev) =>
      prev.every((sid) => ids.has(sid)) ? prev : prev.filter((sid) => ids.has(sid))
    );
  }, [visible]);

  const selectAllVisible = () => setSelected(visible.map((s) => s.id));

  const columns = [
    {
      key: "site",
      title: "Website",
      render: (_v, s) => (
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="font-medium">{s.name}</span>
            {s.is_primary && (
              <Star
                size={13}
                aria-label="Trang chính"
                className="shrink-0 fill-amber-400 text-amber-400"
              />
            )}
          </div>
          <div className="truncate text-xs text-muted">{domainOf(s.base_url)}</div>
        </div>
      ),
    },
    {
      key: "status",
      title: "Trạng thái web",
      width: 150,
      render: (_v, s) => <StatusDot status={s.status} />,
    },
  ];

  const footer = (
    <div className="flex items-center justify-between gap-1.5">
      <Button
        type="text"
        size="small"
        disabled={!visible.length}
        onClick={selectAllVisible}
      >
        Chọn tất cả
      </Button>
      <div className="flex gap-1.5">
        <Button onClick={onClose}>Đóng</Button>
        <Button
          type="primary"
          disabled={!selected.length}
          loading={confirming}
          onClick={() => onConfirm(selected)}
        >
          Đồng bộ danh mục{selected.length ? ` (${selected.length})` : ""}
        </Button>
      </div>
    </div>
  );

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={footer}
      title="Đồng bộ danh mục từ website"
      width={800}
    >
      <div className="mt-2">
        <p className="mb-2 text-sm text-muted">
          Chọn website để kéo danh mục về Hub. Danh mục khớp theo tên (đã chuẩn
          hóa khoảng trắng) — tên giống nhau giữa các site gộp về một danh mục Hub.
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
          rowKey="id"
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
    </Modal>
  );
}
