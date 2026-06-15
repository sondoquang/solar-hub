import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "./client.js";

// Endpoints (Hub backend only) — category-run report, read-only:
//   GET /sync/category-runs/                  -> getCategoryRuns / useCategoryRuns
//       params: ?page, ?page_size, ?status, ?site, ?date_from, ?date_to, ?search
//       (one row per "Đồng bộ danh mục" click)
//   GET /sync/category-runs/stats/            -> getCategoryRunStats / useCategoryRunStats
//       params: ?site, ?date_from, ?date_to, ?search  (cards: total/success/partial/error + last_run)
//   GET /sync/category-runs/{run_id}/         -> getCategoryRun / useCategoryRun
//       per-site rows incl. the woo→hub category snapshot of that run
//   GET /sync/category-runs/{run_id}/export/  -> exportCategoryRun (.xlsx blob download)
//   GET /sync/run-progress/{run_id}/?operation= -> getRunProgress / useRunProgress
//       live { done, error_count } of a freshly-triggered fan-out (orders /
//       products / categories), polled by the progress banner until done.

const clean = (params = {}) =>
  Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
  );

// Pull the server-suggested filename out of Content-Disposition, else fall back.
const filenameFromDisposition = (disposition, fallback) => {
  const match = /filename="?([^"]+)"?/.exec(disposition || "");
  return match ? match[1] : fallback;
};

export const getCategoryRuns = (params = {}) =>
  api.get("/sync/category-runs/", { params: clean(params) }).then((r) => r.data);

export const getCategoryRunStats = (params = {}) =>
  api.get("/sync/category-runs/stats/", { params: clean(params) }).then((r) => r.data);

export const getCategoryRun = (runId) =>
  api.get(`/sync/category-runs/${runId}/`).then((r) => r.data);

// Download one run as a two-sheet Excel report (Tổng quan / Chi tiết).
export async function exportCategoryRun(runId) {
  const res = await api.get(`/sync/category-runs/${runId}/export/`, {
    responseType: "blob",
  });
  const filename = filenameFromDisposition(
    res.headers["content-disposition"],
    "bao-cao-danh-muc.xlsx"
  );
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

const KEY = ["sync-reports"];

export function useCategoryRuns(params = {}) {
  return useQuery({
    queryKey: [...KEY, "category-runs", params],
    queryFn: () => getCategoryRuns(params),
    placeholderData: keepPreviousData,
  });
}

// Stat cards for the Lịch sử đồng bộ tab; honours the same site/date/search
// filters as the list so the cards track the active filter.
export function useCategoryRunStats(params = {}) {
  return useQuery({
    queryKey: [...KEY, "category-run-stats", params],
    queryFn: () => getCategoryRunStats(params),
    placeholderData: keepPreviousData,
  });
}

// `rest` forwards react-query options (refetchInterval, retry, ...) — the
// Danh mục page polls a fresh run this way (404 until the first site finishes).
export function useCategoryRun(runId, { enabled = true, ...rest } = {}) {
  return useQuery({
    queryKey: [...KEY, "category-run", runId],
    queryFn: () => getCategoryRun(runId),
    enabled: Boolean(runId) && enabled,
    ...rest,
  });
}

// Operation keys for /sync/run-progress/ (must match backend PROGRESS_OPERATIONS).
export const SYNC_OPS = {
  orders: "poll_orders",
  products: "push_products",
  categories: "pull_categories",
};

// A scoped run finishes in seconds; the safety stop only kicks in when a site
// hangs or the worker is down. Mirrors the Danh mục page polling.
const RUN_POLL_MS = 3000;
const RUN_TIMEOUT_MS = 3 * 60_000;

export const getRunProgress = (runId, operation) =>
  api
    .get(`/sync/run-progress/${runId}/`, { params: { operation } })
    .then((r) => r.data);

// Live progress of one fan-out run. Unlike the category-run detail this never
// 404s (returns done=0 until the first site lands), so no retry:false dance.
export function useRunProgress(runId, operation, { enabled = true, ...rest } = {}) {
  return useQuery({
    queryKey: [...KEY, "run-progress", operation, runId],
    queryFn: () => getRunProgress(runId, operation),
    enabled: Boolean(runId) && enabled,
    ...rest,
  });
}

// Drives a "Đang đồng bộ… X/Y site hoàn tất" banner for an async fan-out
// (orders / products / categories), the same pattern as the Danh mục page.
// Call `start({ runId, expected })` with the trigger response; poll the run
// until every targeted site reports (or the safety stop fires), then fire
// `onFinish({ finished, timedOut, expected, errorCount })` once and clear.
// Returns { activeRun, doneSites, errorCount, start } — render the banner while
// `activeRun` is set, showing `doneSites`/`activeRun.expected`.
export function useSyncRunProgress(operation, { onFinish } = {}) {
  const [activeRun, setActiveRun] = useState(null); // {runId, expected, startedAt}

  const run = useRunProgress(activeRun?.runId, operation, {
    enabled: !!activeRun,
    refetchInterval: RUN_POLL_MS,
    retry: false,
  });

  const doneSites = run.data?.done ?? 0;
  const errorCount = run.data?.error_count ?? 0;

  // Keep the latest callback without re-arming the completion effect each render.
  const onFinishRef = useRef(onFinish);
  onFinishRef.current = onFinish;

  useEffect(() => {
    if (!activeRun) return;
    const finished = doneSites >= activeRun.expected;
    const timedOut = Date.now() - activeRun.startedAt > RUN_TIMEOUT_MS;
    if (!finished && !timedOut) return;
    onFinishRef.current?.({
      finished,
      timedOut,
      expected: activeRun.expected,
      errorCount,
    });
    setActiveRun(null);
  }, [activeRun, doneSites, errorCount]);

  // Ignore a trigger that targeted no sites — there is nothing to wait for.
  const start = ({ runId, expected }) => {
    if (!runId || !expected) return;
    setActiveRun({ runId, expected, startedAt: Date.now() });
  };

  return { activeRun, doneSites, errorCount, start };
}
