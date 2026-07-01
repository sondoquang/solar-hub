import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Modal, Tabs } from "antd";
import { RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";

import { useClearCategorySync, useSyncCategories } from "../api/products.js";
import { useCategoryRun } from "../api/syncReports.js";
import CategoryOverviewTab from "../components/CategoryOverviewTab.jsx";
import CategoryPullModal from "../components/CategoryPullModal.jsx";
import CategorySyncHistoryTab from "../components/CategorySyncHistoryTab.jsx";
import CategoryTreeTab from "../components/CategoryTreeTab.jsx";

// A scoped pull on a few sites finishes in seconds; the safety stop only kicks
// in when a site hangs or the worker is down.
const RUN_POLL_MS = 3000;
const RUN_TIMEOUT_MS = 3 * 60_000;

// "Danh mục" — a three-tab dashboard over the Hub catalog. The pull trigger +
// run polling live here (the primary "Đồng bộ danh mục" button is global across
// tabs); each tab renders dynamically off the backend:
//   - Tổng quan: stat cards + scoped pull + recent runs + cross-site matrix.
//   - Cây danh mục Hub: the parent–child tree + per-node site links.
//   - Lịch sử đồng bộ: run stats + filters + the runs table.
export default function Categories() {
  const [pullOpen, setPullOpen] = useState(false);
  // {runId, expected, startedAt} while a pull this page triggered is running.
  const [activeRun, setActiveRun] = useState(null);

  const qc = useQueryClient();
  const syncCategories = useSyncCategories();
  const clearCategories = useClearCategorySync();

  // Poll the run report while a pull is in flight. The run 404s until the first
  // site's SyncLog row lands → retry:false keeps the interval polling instead of
  // burning react-query retries on an expected 404.
  const run = useCategoryRun(activeRun?.runId, {
    enabled: !!activeRun,
    refetchInterval: RUN_POLL_MS,
    retry: false,
  });

  const doneSites = run.data?.sites?.length ?? 0;

  // Finish: every targeted site reported (or the safety stop fired) → refresh
  // the dashboard queries and drop the progress banner.
  useEffect(() => {
    if (!activeRun) return;
    const finished = doneSites >= activeRun.expected;
    const timedOut = Date.now() - activeRun.startedAt > RUN_TIMEOUT_MS;
    if (!finished && !timedOut) return;
    if (finished) {
      const errors = run.data?.error_count ?? 0;
      errors
        ? toast(`Đồng bộ xong, ${errors} site lỗi — xem tab Lịch sử đồng bộ.`, { icon: "⚠️" })
        : toast.success(`Đã đồng bộ danh mục từ ${activeRun.expected} site.`);
    } else {
      toast("Đồng bộ chạy lâu hơn dự kiến — kiểm tra tab Lịch sử đồng bộ.", { icon: "⏳" });
    }
    qc.invalidateQueries({ queryKey: ["products", "categories"] });
    qc.invalidateQueries({ queryKey: ["sync-reports"] });
    setActiveRun(null);
  }, [activeRun, doneSites, run.data, qc]);

  // Shared by the global modal (multi-site) and the Tổng quan inline panel
  // (single site): kick the async pull + start polling its run.
  const triggerPull = (siteIds) =>
    syncCategories.mutate(
      { sites: siteIds },
      {
        onSuccess: (res) => {
          setPullOpen(false);
          setActiveRun({
            runId: res.run_id,
            expected: siteIds.length,
            startedAt: Date.now(),
          });
          toast.success("Đã kích hoạt đồng bộ danh mục.");
        },
        onError: () => toast.error("Kích hoạt đồng bộ thất bại."),
      }
    );

  // Destructive reset: confirm first, then clear synchronously and report the
  // counts. Soft-delete keeps in-use categories (and their ancestors); the user
  // then re-pulls the primary sites to rebuild the canonical tree.
  const confirmClear = () =>
    Modal.confirm({
      title: "Xóa toàn bộ danh mục đồng bộ?",
      icon: null,
      okText: "Xóa toàn bộ",
      okButtonProps: { danger: true },
      cancelText: "Hủy",
      width: 520,
      content: (
        <div className="space-y-2 text-sm">
          <p>
            Thao tác này sẽ <strong>ẩn toàn bộ danh mục Hub</strong>, xóa mapping với các
            website và dọn lịch sử đồng bộ danh mục.
          </p>
          <p>
            Những danh mục <strong>đang được sản phẩm sử dụng</strong> (kèm danh mục cha của
            chúng) sẽ được giữ lại. Sau khi xóa, hãy <strong>đồng bộ các website chính
            trước</strong> để lấy cây danh mục của chúng làm gốc.
          </p>
        </div>
      ),
      onOk: () =>
        clearCategories.mutateAsync().then(
          (res) => {
            toast.success(
              `Đã dọn danh mục: ẩn ${res.categories_cleared}, giữ ${res.categories_kept}, ` +
                `xóa ${res.mappings_cleared} mapping.`
            );
          },
          () => {
            toast.error("Xóa danh mục thất bại.");
            return Promise.reject();
          }
        ),
    });

  const items = [
    {
      key: "overview",
      label: "Tổng quan",
      children: (
        <CategoryOverviewTab onPull={triggerPull} pulling={syncCategories.isPending} />
      ),
    },
    {
      key: "tree",
      label: "Cây danh mục Hub",
      children: <CategoryTreeTab />,
    },
    {
      key: "history",
      label: "Lịch sử đồng bộ",
      children: <CategorySyncHistoryTab />,
    },
  ];

  return (
    <section className="pt-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-1.5">
        <div>
          <h1 className="font-display text-2xl font-bold">Danh mục</h1>
          <p className="text-sm text-muted">
            Quản lý danh mục dùng chung (Hub) và đối chiếu với danh mục trên các website.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            danger
            icon={<Trash2 size={16} />}
            loading={clearCategories.isPending}
            onClick={confirmClear}
          >
            Xóa toàn bộ danh mục đồng bộ
          </Button>
          <Button type="primary" icon={<RefreshCw size={16} />} onClick={() => setPullOpen(true)}>
            Đồng bộ danh mục
          </Button>
        </div>
      </div>

      {activeRun && (
        <Alert
          type="info"
          showIcon
          className="mb-3"
          message={`Đang đồng bộ danh mục… ${doneSites}/${activeRun.expected} site hoàn tất.`}
        />
      )}

      <Tabs defaultActiveKey="overview" items={items} />

      <CategoryPullModal
        open={pullOpen}
        onClose={() => setPullOpen(false)}
        onConfirm={triggerPull}
        confirming={syncCategories.isPending}
      />
    </section>
  );
}
