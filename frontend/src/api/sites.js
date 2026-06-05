import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client.js";

// Endpoints (Hub backend only):
//   GET    /sites/                      -> getSites / useSites
//   POST   /sites/                      -> createSite / useCreateSite
//   PATCH  /sites/{id}/                 -> updateSite / useUpdateSite
//   DELETE /sites/{id}/                 -> deleteSite / useDeleteSite
//   POST   /sites/{id}/test_connection/ -> testConnection / useTestConnection
//   POST   /sites/test_connections/     -> testConnections / useTestConnections (bulk)
//   POST   /sites/import_excel/         -> importSitesExcel / useImportSites (.xlsx)

export const getSites = () => api.get("/sites/").then((r) => r.data);
export const createSite = (payload) => api.post("/sites/", payload).then((r) => r.data);
export const updateSite = ({ id, ...payload }) =>
  api.patch(`/sites/${id}/`, payload).then((r) => r.data);
export const deleteSite = (id) => api.delete(`/sites/${id}/`).then((r) => r.data);
export const testConnection = (id) =>
  api.post(`/sites/${id}/test_connection/`).then((r) => r.data);
export const testConnections = (ids) =>
  api.post("/sites/test_connections/", { ids }).then((r) => r.data);
export const importSitesExcel = (file) => {
  const form = new FormData();
  form.append("file", file);
  return api.post("/sites/import_excel/", form).then((r) => r.data);
};

const SITES_KEY = ["sites"];

export function useSites() {
  return useQuery({ queryKey: SITES_KEY, queryFn: getSites });
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
export const useImportSites = () => useInvalidatingMutation(importSitesExcel);
export const useTestConnection = () => useInvalidatingMutation(testConnection, { settle: true });
export const useTestConnections = () => useInvalidatingMutation(testConnections, { settle: true });
