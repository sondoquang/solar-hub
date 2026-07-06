import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api } from "./client.js";

// Domain-info snapshots (Hub backend only) — one per site: WHOIS / DNS / SSL /
// blacklist / Google index. The lookups run in Celery; the API just reads the
// snapshot and enqueues refreshes.
//   GET  /domain-info/                    -> getDomainInfoList / useDomainInfoList
//   GET  /domain-info/{siteId}/           -> getDomainInfo / useDomainInfo (404 → null)
//   POST /domain-info/{siteId}/refresh/   -> refreshDomainInfo / useRefreshDomainInfo
//   POST /domain-info/refresh-all/        -> refreshAllDomainInfo / useRefreshAllDomainInfo

const clean = (params = {}) =>
  Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
  );

const KEY = ["domain-info"];
const detailKey = (siteId) => [...KEY, "detail", siteId];

export const getDomainInfoList = (params = {}) =>
  api.get("/domain-info/", { params: clean(params) }).then((r) => r.data);

// A site never checked has no snapshot row (404) — surface that as null so the
// modal can show a "Chưa kiểm tra" empty state instead of an error.
export const getDomainInfo = (siteId) =>
  api
    .get(`/domain-info/${siteId}/`)
    .then((r) => r.data)
    .catch((err) => {
      if (err.response?.status === 404) return null;
      throw err;
    });

export const refreshDomainInfo = ({ siteId, checks }) =>
  api
    .post(`/domain-info/${siteId}/refresh/`, checks ? { checks } : {})
    .then((r) => r.data);

export const refreshAllDomainInfo = () =>
  api.post("/domain-info/refresh-all/", {}).then((r) => r.data);

export function useDomainInfoList(params = {}) {
  return useQuery({
    queryKey: [...KEY, "list", params],
    queryFn: () => getDomainInfoList(params),
    placeholderData: keepPreviousData,
  });
}

export function useDomainInfo(siteId, { enabled = true } = {}) {
  return useQuery({
    queryKey: detailKey(siteId),
    queryFn: () => getDomainInfo(siteId),
    enabled: enabled && siteId != null,
    // While any check is still running, poll so the snapshot updates live; stop
    // once the worker has finished (is_pending false / no row yet).
    refetchInterval: (query) => (query.state.data?.is_pending ? 4000 : false),
  });
}

// Refresh one site: mark the snapshot pending, then invalidate so the modal +
// the aggregate list both re-fetch.
export function useRefreshDomainInfo(siteId) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: refreshDomainInfo,
    onSuccess: (data) => {
      if (data) qc.setQueryData(detailKey(siteId), data);
      qc.invalidateQueries({ queryKey: detailKey(siteId) });
      qc.invalidateQueries({ queryKey: [...KEY, "list"] });
    },
  });
}

export function useRefreshAllDomainInfo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: refreshAllDomainInfo,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
