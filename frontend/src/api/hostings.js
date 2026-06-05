import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client.js";

// Endpoints (Hub backend only):
//   GET    /hostings/             -> getHostings / useHostings (server-side paginated: ?page, ?page_size, ?search)
//   POST   /hostings/             -> createHosting / useCreateHosting
//   PATCH  /hostings/{id}/        -> updateHosting / useUpdateHosting
//   DELETE /hostings/{id}/        -> deleteHosting / useDeleteHosting
//   POST   /hostings/{id}/check/  -> checkHosting / useCheckHosting (grouped healthcheck)

// Hostings can share the same name but differ by account, so always show the
// account username alongside the name to disambiguate them in selects.
export const hostingLabel = (h) =>
  h?.account_username ? `${h.name} (${h.account_username})` : h?.name;

const clean = (params = {}) =>
  Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
  );

export const getHostings = (params = {}) =>
  api.get("/hostings/", { params: clean(params) }).then((r) => r.data);
export const createHosting = (payload) => api.post("/hostings/", payload).then((r) => r.data);
export const updateHosting = ({ id, ...payload }) =>
  api.patch(`/hostings/${id}/`, payload).then((r) => r.data);
export const deleteHosting = (id) => api.delete(`/hostings/${id}/`).then((r) => r.data);
export const checkHosting = (id) => api.post(`/hostings/${id}/check/`).then((r) => r.data);

const HOSTINGS_KEY = ["hostings"];
const SITES_KEY = ["sites"];

// Server-side paginated: params (page / page_size) are part of the query key
// so the table's pager re-fetches the matching page from the backend.
export function useHostings(params = {}) {
  return useQuery({
    queryKey: [...HOSTINGS_KEY, "list", params],
    queryFn: () => getHostings(params),
    placeholderData: keepPreviousData,
  });
}

function useHostingMutation(mutationFn, { settle = false } = {}) {
  const qc = useQueryClient();
  // Changes to hostings can affect the sites list (assignment / health), so
  // invalidate both query caches.
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: HOSTINGS_KEY });
    qc.invalidateQueries({ queryKey: SITES_KEY });
  };
  return useMutation({
    mutationFn,
    ...(settle ? { onSettled: invalidate } : { onSuccess: invalidate }),
  });
}

export const useCreateHosting = () => useHostingMutation(createHosting);
export const useUpdateHosting = () => useHostingMutation(updateHosting);
export const useDeleteHosting = () => useHostingMutation(deleteHosting);
export const useCheckHosting = () => useHostingMutation(checkHosting, { settle: true });
