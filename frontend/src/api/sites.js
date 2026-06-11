import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client.js";

// Endpoints (Hub backend only):
//   GET    /sites/                      -> getSites / useSites (server-side paginated: ?page, ?page_size, ?ordering, ?hosting, ?status, ?is_primary, ?search)
//   GET    /sites/stats/                -> getSiteStats / useSiteStats (global up/down/unknown counts)
//   POST   /sites/                      -> createSite / useCreateSite
//   PATCH  /sites/{id}/                 -> updateSite / useUpdateSite
//   DELETE /sites/{id}/                 -> deleteSite / useDeleteSite
//   POST   /sites/{id}/test_connection/ -> testConnection / useTestConnection
//   POST   /sites/test_connections/     -> testConnections / useTestConnections (bulk)
//   POST   /sites/import_excel/         -> importSitesExcel / useImportSites (.xlsx)

// Drop empty params so the URL only carries meaningful query keys.
const clean = (params = {}) =>
  Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
  );

export const getSites = (params = {}) =>
  api.get("/sites/", { params: clean(params) }).then((r) => r.data);
export const getSiteStats = () => api.get("/sites/stats/").then((r) => r.data);
export const createSite = (payload) => api.post("/sites/", payload).then((r) => r.data);
export const updateSite = ({ id, ...payload }) =>
  api.patch(`/sites/${id}/`, payload).then((r) => r.data);
export const deleteSite = (id) => api.delete(`/sites/${id}/`).then((r) => r.data);
export const testConnection = (id) =>
  api.post(`/sites/${id}/test_connection/`).then((r) => r.data);
export const testConnections = (ids) =>
  api.post("/sites/test_connections/", { ids }).then((r) => r.data);
export const importSitesExcel = ({ file, hosting } = {}) => {
  const form = new FormData();
  form.append("file", file);
  if (hosting != null) form.append("hosting", hosting);
  return api.post("/sites/import_excel/", form).then((r) => r.data);
};

const SITES_KEY = ["sites"];

// Server-side pagination/sort/filter: the query key carries the params so
// changing page / page size / ordering / hosting re-fetches from the backend.
// keepPreviousData avoids a loading flash while paging.
export function useSites(params = {}) {
  return useQuery({
    queryKey: [...SITES_KEY, "list", params],
    queryFn: () => getSites(params),
    placeholderData: keepPreviousData,
  });
}

export function useSiteStats() {
  return useQuery({ queryKey: [...SITES_KEY, "stats"], queryFn: getSiteStats });
}

function useInvalidatingMutation(mutationFn, { settle = false } = {}) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: SITES_KEY });
  return useMutation({
    mutationFn,
    ...(settle ? { onSettled: invalidate } : { onSuccess: invalidate }),
  });
}

export const useCreateSite = () => useInvalidatingMutation(createSite);
export const useUpdateSite = () => useInvalidatingMutation(updateSite);
export const useDeleteSite = () => useInvalidatingMutation(deleteSite);

// Import can assign sites to a hosting → also refresh the hostings list (counts).
export function useImportSites() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: importSitesExcel,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: SITES_KEY });
      qc.invalidateQueries({ queryKey: ["hostings"] });
    },
  });
}
export const useTestConnection = () => useInvalidatingMutation(testConnection, { settle: true });
export const useTestConnections = () => useInvalidatingMutation(testConnections, { settle: true });
