import { Button, Modal, Table, Tag, Tooltip } from "antd";
import { Download } from "lucide-react";
import { useState } from "react";
import toast from "react-hot-toast";

import { exportCategoryRun, useCategoryRun } from "../api/syncReports.js";
import { formatDateTime, friendlySyncError } from "../lib/format.js";
import ErrorState from "./ErrorState.jsx";

// Run/site status → antd Tag. Shared by the Reports table and this modal.
export function RunStatusTag({ status }) {
  if (status === "success") return <Tag color="success">Thành công</Tag>;
  if (status === "error") return <Tag color="error">Lỗi</Tag>;
  return <Tag color="warning">Một phần</Tag>;
}

const CATEGORY_COLUMNS = [
  {
    key: "woo_id",
    dataIndex: "woo_id",
    title: "Woo ID",
    width: 90,
    align: "right",
    render: (v) => <span className="tabular-nums text-muted">{v}</span>,
  },
  { key: "woo_name", dataIndex: "woo_name", title: "Danh mục trên site" },
  {
    key: "hub_id",
    dataIndex: "hub_id",
    title: "Hub ID",
    width: 90,
    align: "right",
    render: (v) => <span className="tabular-nums text-muted">{v}</span>,
  },
  { key: "hub_name", dataIndex: "hub_name", title: "Danh mục trong Hub" },
];

// Detail of one category-sync run: one row per site (expandable to the
// woo→hub category list snapshotted at pull time), plus the Excel export.
// Mirrors ProductSyncStatusModal's modal shell.
export default function CategoryRunDetailModal({ runId, open, onClose }) {
  const { data, isLoading, isError, refetch } = useCategoryRun(runId, { enabled: open });
  const [exporting, setExporting] = useState(false);

  const handleExport = async () => {
    setExporting(true);
    try {
      await exportCategoryRun(runId);
      toast.success("Đã xuất báo cáo Excel.");
    } catch {
      toast.error("Xuất báo cáo thất bại.");
    } finally {
      setExporting(false);
    }
  };

  const sites = data?.sites ?? [];

  const columns = [
    {
      key: "site",
      title: "Website",
      render: (_v, r) => (
        <div className="min-w-0">
          <p className="truncate font-medium">{r.site_name || "—"}</p>
          <p className="truncate text-xs text-muted">{r.site_url}</p>
        </div>
      ),
    },
    {
      key: "hosting",
      dataIndex: "hosting",
      title: "Hosting",
      width: 140,
      render: (v) => v || "—",
    },
    {
      key: "status",
      dataIndex: "status",
      title: "Kết quả",
      width: 120,
      render: (v) => <RunStatusTag status={v} />,
    },
    {
      key: "pulled",
      dataIndex: "pulled",
      title: "Danh mục",
      width: 100,
      align: "right",
      render: (v) => <span className="tabular-nums">{v}</span>,
    },
    {
      key: "mapped",
      dataIndex: "mapped",
      title: "Ánh xạ Hub",
      width: 110,
      align: "right",
      render: (v) => <span className="tabular-nums">{v}</span>,
    },
    {
      key: "error",
      dataIndex: "error",
      title: "Lỗi",
      width: 210,
      render: (v) =>
        v ? (
          <Tooltip title={`Mã kỹ thuật: ${v}`}>
            <span className="text-xs leading-snug text-danger">{friendlySyncError(v)}</span>
          </Tooltip>
        ) : (
          "—"
        ),
    },
  ];

  const title = (
    <div className="flex items-center gap-2">
      <span>Chi tiết lần đồng bộ danh mục</span>
      {data && (
        <span className="rounded-full bg-blue-500/15 px-2.5 py-0.5 text-xs font-semibold text-blue-300">
          {formatDateTime(data.started_at)}
        </span>
      )}
    </div>
  );

  const footer = (
    <div className="flex items-center justify-end gap-1.5">
      <Button onClick={onClose}>Đóng</Button>
      <Button
        type="primary"
        icon={<Download size={14} />}
        loading={exporting}
        disabled={!data}
        onClick={handleExport}
      >
        Xuất Excel
      </Button>
    </div>
  );

  return (
    <Modal open={open} onCancel={onClose} footer={footer} title={title} width={900}>
      {isError ? (
        <ErrorState message="Không tải được chi tiết lần đồng bộ" onRetry={refetch} />
      ) : (
        <div className="mt-2">
          {data && (
            <p className="mb-2 text-sm text-muted">
              {data.site_count} site — {data.total_pulled} danh mục, đã ánh xạ{" "}
              {data.total_mapped} vào Hub.
            </p>
          )}
          <Table
            rowKey={(r) => r.site_id ?? r.site_name}
            size="small"
            loading={isLoading}
            columns={columns}
            dataSource={sites}
            pagination={false}
            scroll={{ y: 420 }}
            expandable={{
              rowExpandable: (r) => r.categories.length > 0,
              expandedRowRender: (r) => (
                <Table
                  rowKey="woo_id"
                  size="small"
                  columns={CATEGORY_COLUMNS}
                  dataSource={r.categories}
                  pagination={false}
                />
              ),
            }}
            locale={{ emptyText: "Không có site nào trong lần đồng bộ này." }}
          />
        </div>
      )}
    </Modal>
  );
}
