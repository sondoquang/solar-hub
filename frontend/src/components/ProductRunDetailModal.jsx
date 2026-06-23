import { Button, Modal, Table, Tag } from "antd";
import { Download } from "lucide-react";
import { useState } from "react";
import toast from "react-hot-toast";

import { exportProductRun, useProductRun } from "../api/syncReports.js";
import { formatDateTime } from "../lib/format.js";
import { RunStatusTag } from "./CategoryRunDetailModal.jsx";
import ErrorState from "./ErrorState.jsx";

const OP_LABEL = { create: "Tạo", update: "Cập nhật", delete: "Xóa" };

// One rejected SKU within a site's push. ``kind`` tints a duplicate/already-exists
// reject (amber — expected friction) apart from a genuine error (red).
const FAILED_COLUMNS = [
  {
    key: "sku",
    dataIndex: "sku",
    title: "SKU",
    width: 180,
    render: (v) => <span className="font-medium tabular-nums">{v || "—"}</span>,
  },
  {
    key: "op",
    dataIndex: "op",
    title: "Thao tác",
    width: 110,
    render: (v) => OP_LABEL[v] || v || "—",
  },
  {
    key: "reason",
    title: "Lý do",
    render: (_v, r) => (
      <div className="min-w-0">
        <Tag color={r.kind === "duplicate" ? "warning" : "error"}>{r.code || "lỗi"}</Tag>
        {r.message && <span className="ml-1 text-xs text-muted">{r.message}</span>}
      </div>
    ),
  },
];

// Detail of one product-push run: one row per site (expandable to the rejected
// SKUs + reasons), plus the Excel export. Mirrors CategoryRunDetailModal.
export default function ProductRunDetailModal({ runId, open, onClose }) {
  const { data, isLoading, isError, refetch } = useProductRun(runId, { enabled: open });
  const [exporting, setExporting] = useState(false);

  const handleExport = async () => {
    setExporting(true);
    try {
      await exportProductRun(runId);
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
      key: "created",
      dataIndex: "created",
      title: "Tạo mới",
      width: 90,
      align: "right",
      render: (v) => <span className="tabular-nums">{v}</span>,
    },
    {
      key: "updated",
      dataIndex: "updated",
      title: "Cập nhật",
      width: 90,
      align: "right",
      render: (v) => <span className="tabular-nums">{v}</span>,
    },
    {
      key: "adopted_count",
      dataIndex: "adopted_count",
      title: "Đã nhận",
      width: 90,
      align: "right",
      render: (v) =>
        v ? <span className="tabular-nums text-success">{v}</span> : <span className="text-muted">0</span>,
    },
    {
      key: "failed",
      title: "Lỗi",
      width: 150,
      align: "right",
      render: (_v, r) =>
        r.error ? (
          <span className="text-danger">{r.error}</span>
        ) : (
          <span className={`tabular-nums ${r.failed.length ? "text-danger" : ""}`}>
            {r.failed.length}
          </span>
        ),
    },
  ];

  const title = (
    <div className="flex items-center gap-2">
      <span>Chi tiết lần đồng bộ sản phẩm</span>
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
    <Modal open={open} onCancel={onClose} footer={footer} title={title} width={920}>
      {isError ? (
        <ErrorState message="Không tải được chi tiết lần đồng bộ" onRetry={refetch} />
      ) : (
        <div className="mt-2">
          {data && (
            <p className="mb-2 text-sm text-muted">
              {data.site_count} site — tạo mới {data.total_created}, cập nhật{" "}
              {data.total_updated}, đã nhận theo tên {data.total_adopted}
              {data.total_failed > 0 && (
                <span className="text-danger">, {data.total_failed} lỗi</span>
              )}
              .
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
              rowExpandable: (r) => r.failed.length > 0,
              expandedRowRender: (r) => (
                <Table
                  rowKey={(f) => `${f.sku}-${f.op}`}
                  size="small"
                  columns={FAILED_COLUMNS}
                  dataSource={r.failed}
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
