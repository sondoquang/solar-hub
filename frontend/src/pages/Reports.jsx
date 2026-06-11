import { Button } from "antd";
import { Download, Eye } from "lucide-react";
import { useState } from "react";
import toast from "react-hot-toast";

import { exportCategoryRun, useCategoryRuns } from "../api/syncReports.js";
import CategoryRunDetailModal, { RunStatusTag } from "../components/CategoryRunDetailModal.jsx";
import DataTable from "../components/DataTable.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ErrorState from "../components/ErrorState.jsx";
import { formatDateTime } from "../lib/format.js";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

// Reports page — v1 holds the category-sync report: one row per "Đồng bộ danh
// mục" click (grouped by run_id server-side), detail modal + Excel export.
// Runs from before the report feature carry no snapshot and are not listed.
export default function Reports() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [detailRunId, setDetailRunId] = useState(null);
  const [exportingId, setExportingId] = useState(null);

  const { data, isLoading, isFetching, isError, refetch } = useCategoryRuns({
    page,
    page_size: pageSize,
  });

  const rows = data?.results ?? [];
  const total = data?.count ?? 0;

  const handleExport = async (runId) => {
    setExportingId(runId);
    try {
      await exportCategoryRun(runId);
      toast.success("Đã xuất báo cáo Excel.");
    } catch {
      toast.error("Xuất báo cáo thất bại.");
    } finally {
      setExportingId(null);
    }
  };

  const handleTableChange = (pagination) => {
    const resets = pagination.pageSize !== pageSize;
    setPageSize(pagination.pageSize);
    setPage(resets ? 1 : pagination.current);
  };

  const columns = [
    {
      key: "stt",
      title: "STT",
      width: 64,
      ellipsis: false,
      align: "center",
      render: (_v, _r, i) => (page - 1) * pageSize + i + 1,
    },
    {
      key: "started_at",
      dataIndex: "started_at",
      title: "Thời gian đồng bộ",
      width: 190,
      render: (v) => <span className="tabular-nums">{formatDateTime(v)}</span>,
    },
    {
      key: "site_count",
      dataIndex: "site_count",
      title: "Số site",
      width: 90,
      align: "right",
      render: (v) => <span className="tabular-nums">{v}</span>,
    },
    {
      key: "total_pulled",
      dataIndex: "total_pulled",
      title: "Tổng danh mục",
      width: 130,
      align: "right",
      render: (v) => <span className="tabular-nums">{v}</span>,
    },
    {
      key: "total_mapped",
      dataIndex: "total_mapped",
      title: "Đã ánh xạ Hub",
      width: 130,
      align: "right",
      render: (v) => <span className="tabular-nums">{v}</span>,
    },
    {
      key: "status",
      dataIndex: "status",
      title: "Trạng thái",
      width: 140,
      ellipsis: false,
      render: (v, r) => (
        <div className="flex items-center gap-1.5">
          <RunStatusTag status={v} />
          {r.error_count > 0 && (
            <span className="text-xs text-danger">{r.error_count} site lỗi</span>
          )}
        </div>
      ),
    },
    {
      key: "actions",
      title: "Thao tác",
      width: 230,
      align: "right",
      hideable: false,
      ellipsis: false,
      render: (_v, r) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            type="link"
            size="small"
            icon={<Eye size={14} />}
            onClick={() => setDetailRunId(r.run_id)}
          >
            Xem chi tiết
          </Button>
          <Button
            size="small"
            icon={<Download size={14} />}
            loading={exportingId === r.run_id}
            onClick={() => handleExport(r.run_id)}
          >
            Xuất Excel
          </Button>
        </div>
      ),
    },
  ];

  return (
    <section className="pt-4">
      <div className="mb-3">
        <h1 className="font-display text-2xl font-bold">Báo cáo</h1>
        <p className="text-sm text-muted">
          Lịch sử đồng bộ danh mục từ các website (mỗi dòng là một lần bấm
          &quot;Đồng bộ danh mục&quot;).
        </p>
      </div>

      {isError ? (
        <ErrorState message="Không tải được lịch sử đồng bộ danh mục" onRetry={refetch} />
      ) : (
        <div className="rounded bg-white p-2.5 shadow-card">
          <DataTable
            columns={columns}
            dataSource={rows}
            rowKey="run_id"
            size="middle"
            loading={isLoading || isFetching}
            onRefresh={refetch}
            refreshing={isFetching}
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
                  title="Chưa có lần đồng bộ nào"
                  hint='Bấm "Đồng bộ danh mục" ở trang Sản phẩm để bắt đầu; các lần đồng bộ trước khi có tính năng báo cáo không được liệt kê.'
                />
              ),
            }}
          />
        </div>
      )}

      <CategoryRunDetailModal
        runId={detailRunId}
        open={detailRunId != null}
        onClose={() => setDetailRunId(null)}
      />
    </section>
  );
}
