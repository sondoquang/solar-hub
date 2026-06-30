import { Button, Modal } from "antd";
import { CircleCheck, CircleX, TriangleAlert } from "lucide-react";

import { useProductRun } from "../api/syncReports.js";
import { friendlySyncError } from "../lib/format.js";

// End-of-run summary shown right after a push finishes: how many sites succeeded
// vs failed (with the failing sites + reason), plus a "Xem chi tiết" jump into
// the full per-site report. The "rõ ràng" feedback the user asked for; the
// history tab keeps the durable record.
export default function ProductSyncSummaryModal({ runId, open, onClose, onViewDetail }) {
  const { data, isLoading } = useProductRun(runId, { enabled: open });

  const sites = data?.sites ?? [];
  const failedSites = sites.filter((s) => s.status === "error" || s.status === "partial");
  const okCount = sites.length - failedSites.length;

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title="Kết quả đồng bộ sản phẩm"
      width={560}
      footer={
        <div className="flex items-center justify-end gap-1.5">
          <Button onClick={onClose}>Đóng</Button>
          <Button type="primary" disabled={!runId} onClick={onViewDetail}>
            Xem chi tiết
          </Button>
        </div>
      }
    >
      {isLoading ? (
        <p className="py-4 text-center text-muted">Đang tải kết quả…</p>
      ) : (
        <div className="mt-1 flex flex-col gap-3">
          <div className="flex flex-wrap gap-3">
            <div className="flex items-center gap-2 rounded bg-green-500/10 px-3 py-2">
              <CircleCheck size={18} className="text-success" />
              <span className="font-medium">{okCount}</span>
              <span className="text-sm text-muted">site thành công</span>
            </div>
            <div className="flex items-center gap-2 rounded bg-red-500/10 px-3 py-2">
              <CircleX size={18} className="text-danger" />
              <span className="font-medium">{failedSites.length}</span>
              <span className="text-sm text-muted">site chưa đồng bộ được</span>
            </div>
          </div>

          {data && (
            <p className="text-sm text-muted">
              Tạo mới {data.total_created}, cập nhật {data.total_updated}, đã nhận theo tên{" "}
              {data.total_adopted}
              {data.total_failed > 0 && (
                <span className="text-danger">, {data.total_failed} mục lỗi</span>
              )}
              .
            </p>
          )}

          {failedSites.length > 0 && (
            <div className="max-h-52 overflow-y-auto rounded border border-border">
              {failedSites.map((s) => (
                <div
                  key={s.site_id ?? s.site_name}
                  className="flex items-start gap-2 border-b border-border px-3 py-2 last:border-0"
                >
                  <TriangleAlert size={15} className="mt-0.5 shrink-0 text-warning" />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{s.site_name || "—"}</p>
                    <p className="truncate text-xs text-muted">
                      {s.error
                        ? friendlySyncError(s.error)
                        : s.failed.length
                          ? `${s.failed.length} sản phẩm lỗi (${s.failed[0]?.code || "?"}…)`
                          : s.ambiguous?.length
                            ? `${s.ambiguous.length} sản phẩm trùng tên — cần xử lý tay`
                            : "Một phần chưa đồng bộ"}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
