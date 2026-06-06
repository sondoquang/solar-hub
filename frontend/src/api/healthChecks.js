import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "./client.js";

// Endpoints (Hub backend only) — health-check history is read-only:
//   GET /healthchecks/         -> getHealthChecks / useHealthChecks
//       params: ?page, ?page_size, ?ordering, ?search,
//               ?status, ?check_type, ?site, ?hosting, ?date_from, ?date_to
//   GET /healthchecks/stats/   -> getHealthCheckStats / useHealthCheckStats
//   GET /healthchecks/export/  -> exportHealthChecks (CSV blob download)

const clean = (params = {}) =>
  Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
  );

export const getHealthChecks = (params = {}) =>
  api.get("/healthchecks/", { params: clean(params) }).then((r) => r.data);

export const getHealthCheckStats = (params = {}) =>
  api.get("/healthchecks/stats/", { params: clean(params) }).then((r) => r.data);

// Download the filtered report as a CSV file (same filters as the list).
export async function exportHealthChecks(params = {}) {
  const res = await api.get("/healthchecks/export/", {
    params: clean(params),
    responseType: "blob",
  });
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = "health-checks.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

const KEY = ["healthchecks"];

// Server-side pagination/sort/filter: params live in the query key so any
// change (page / size / sort / filter / search) re-fetches from the backend.
export function useHealthChecks(params = {}) {
  return useQuery({
    queryKey: [...KEY, "list", params],
    queryFn: () => getHealthChecks(params),
    placeholderData: keepPreviousData,
  });
}

export function useHealthCheckStats(params = {}) {
  return useQuery({
    queryKey: [...KEY, "stats", params],
    queryFn: () => getHealthCheckStats(params),
    placeholderData: keepPreviousData,
  });
}
