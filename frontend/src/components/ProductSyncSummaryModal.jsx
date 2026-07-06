import { Button, Modal, Tooltip } from "antd";
import { Check, Info, RefreshCw, TriangleAlert, X, XCircle } from "lucide-react";

import { useProductRun } from "../api/syncReports.js";
import { friendlySyncError } from "../lib/format.js";

// Tone styling for a problem row — partial (amber, the site synced but some items
// didn't) vs error (red, the whole site couldn't sync at all). Uses literal
// colour tints (so opacity modifiers work) paired with semantic status tokens for
// the icon, so both read correctly in light and dark themes.
const TONE = {
  warning: {
    card: "border-amber-500/25 bg-amber-500/[0.07]",
    iconBox: "bg-amber-500/15",
    icon: "text-warning",
  },
  error: {
    card: "border-red-500/25 bg-red-500/[0.07]",
    iconBox: "bg-red-500/15",
    icon: "text-danger",
  },
};

// Describe one non-successful site: tone/icon + the one-line subtitle shown on the
// card + the rich tooltip explaining *why* on hover. Partial and error are
// deliberately different so the user can tell "chưa xong hẳn" from "hỏng hẳn".
function describeProblem(s) {
  if (s.status === "error") {
    return {
      tone: "error",
      Icon: XCircle,
      title: s.site_name || "—",
      subtitle: friendlySyncError(s.error) || "Không đồng bộ được",
      tooltip: (
        <div className="max-w-xs text-xs leading-relaxed">
          <p className="mb-1 font-semibold">Không đồng bộ được</p>
          <p>
            Không đẩy được sản phẩm nào tới website này — thường do site không phản
            hồi, sai khóa API/kết nối, hoặc plugin WooCommerce lỗi.
          </p>
          {s.error && <p className="mt-1 opacity-80">Mã kỹ thuật: {s.error}</p>}
        </div>
      ),
    };
  }

  // Partial — the site got most products, but a few items were rejected or need
  // a manual decision. Surface the counts in the tooltip.
  const failedN = s.failed?.length ?? 0;
  const ambiguousN = s.ambiguous?.length ?? 0;
  return {
    tone: "warning",
    Icon: TriangleAlert,
    title: s.site_name || "—",
    subtitle: "Một phần chưa đồng bộ",
    tooltip: (
      <div className="max-w-xs text-xs leading-relaxed">
        <p className="mb-1 font-semibold">Đồng bộ một phần</p>
        <p>Website đã nhận phần lớn sản phẩm, nhưng một số mục chưa hoàn tất:</p>
        <ul className="mt-1 list-disc space-y-0.5 pl-4">
          {failedN > 0 && <li>{failedN} sản phẩm bị lỗi khi đẩy</li>}
          {ambiguousN > 0 && (
            <li>{ambiguousN} sản phẩm trùng tên trên site — cần xử lý tay</li>
          )}
          {failedN === 0 && ambiguousN === 0 && <li>Một số mục chưa được ghi nhận đủ</li>}
        </ul>
        <p className="mt-1 opacity-80">Bấm “Xem chi tiết” để xem từng sản phẩm.</p>
      </div>
    ),
  };
}

// One row in the problem list: a tinted card whose whole surface is the tooltip
// target (hover anywhere to read the explanation); a muted "i" hints it's hoverable.
function ProblemRow({ site }) {
  const p = describeProblem(site);
  const tone = TONE[p.tone];
  const { Icon } = p;
  return (
    <Tooltip title={p.tooltip} placement="top">
      <div
        className={`flex cursor-help items-center gap-3 rounded-xl border px-3 py-2.5 transition-colors ${tone.card}`}
      >
        <span
          className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-lg ${tone.iconBox}`}
        >
          <Icon size={20} className={tone.icon} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold text-ink">{p.title}</p>
          <p className="truncate text-sm text-muted">{p.subtitle}</p>
        </div>
        <Info size={16} className="shrink-0 text-muted/60" aria-hidden />
      </div>
    </Tooltip>
  );
}

// Header shown in the modal's title slot: a soft brand icon chip + title/subtitle.
function Header() {
  return (
    <div className="flex items-center gap-3">
      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-brand/10 text-brand">
        <RefreshCw size={24} />
      </span>
      <div className="min-w-0">
        <div className="text-xl font-bold leading-tight text-ink">
          Kết quả đồng bộ sản phẩm
        </div>
        <div className="text-sm font-normal text-muted">Đồng bộ từ Hub xuống các site</div>
      </div>
    </div>
  );
}

// End-of-run summary shown right after a push finishes: how many sites succeeded
// vs didn't, a one-line tally, then the list of sites that need attention —
// each one tinted + tooltip-explained by whether it partially synced (amber) or
// failed outright (red). "Xem chi tiết" jumps into the full per-site report.
export default function ProductSyncSummaryModal({ runId, open, onClose, onViewDetail }) {
  const { data, isLoading } = useProductRun(runId, { enabled: open });

  const sites = data?.sites ?? [];
  const problemSites = sites.filter((s) => s.status === "error" || s.status === "partial");
  const okCount = sites.length - problemSites.length;

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={<Header />}
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
        <p className="py-6 text-center text-muted">Đang tải kết quả…</p>
      ) : (
        <div className="mt-4 flex flex-col gap-4">
          {/* Success / needs-attention tally */}
          <div className="grid grid-cols-2 gap-3">
            <div className="flex items-center gap-3 rounded-xl border border-green-500/20 bg-green-500/[0.08] px-4 py-3.5">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-success text-white">
                <Check size={20} />
              </span>
              <span className="text-2xl font-bold text-success">{okCount}</span>
              <span className="text-sm font-medium text-success">site thành công</span>
            </div>
            <div className="flex items-center gap-3 rounded-xl border border-red-500/20 bg-red-500/[0.06] px-4 py-3.5">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-danger text-white">
                <X size={20} />
              </span>
              <span className="text-2xl font-bold text-danger">{problemSites.length}</span>
              <span className="text-sm font-medium text-danger">site chưa đồng bộ được</span>
            </div>
          </div>

          {/* One-line tally of what changed */}
          {data && (
            <div className="flex items-start gap-2.5 rounded-lg bg-blue-500/[0.08] px-4 py-3">
              <Info size={18} className="mt-0.5 shrink-0 text-info" />
              <p className="text-sm text-text">
                Tạo mới {data.total_created}, cập nhật {data.total_updated}, đã nhận theo
                tên {data.total_adopted}
                {data.total_failed > 0 && (
                  <span className="font-medium text-danger">
                    , {data.total_failed} mục lỗi
                  </span>
                )}
                .
              </p>
            </div>
          )}

          {/* Sites needing attention — partial (amber) vs error (red), each explained
              on hover. All-clear gets a friendly confirmation instead. */}
          {problemSites.length > 0 ? (
            <div className="flex flex-col gap-2 border-t border-border pt-4">
              {problemSites.map((s) => (
                <ProblemRow key={s.site_id ?? s.site_name} site={s} />
              ))}
            </div>
          ) : (
            data &&
            sites.length > 0 && (
              <div className="flex items-center gap-2.5 rounded-xl border border-green-500/20 bg-green-500/[0.06] px-4 py-3 text-sm text-success">
                <Check size={18} className="shrink-0" />
                Tất cả site đã đồng bộ thành công.
              </div>
            )
          )}
        </div>
      )}
    </Modal>
  );
}
