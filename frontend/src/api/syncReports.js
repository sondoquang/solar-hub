import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "./client.js";

// Endpoints (Hub backend only) — category-run report, read-only:
//   GET /sync/category-runs/                  -> getCategoryRuns / useCategoryRuns
//       params: ?page, ?page_size  (one row per "Đồng bộ danh mục" click)
//   GET /sync/category-runs/{run_id}/         -> getCategoryRun / useCategoryRun
//       per-site rows incl. the woo→hub category snapshot of that run
//   GET /sync/category-runs/{run_id}/export/  -> exportCategoryRun (.xlsx blob download)

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

export function useCategoryRun(runId, { enabled = true } = {}) {
  return useQuery({
    queryKey: [...KEY, "category-run", runId],
    queryFn: () => getCategoryRun(runId),
    enabled: Boolean(runId) && enabled,
  });
}
