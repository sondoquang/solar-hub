import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api } from "./client.js";

// Endpoints (Hub backend only) — orders are pulled in by the poll, read-only here:
//   GET  /orders/          -> getOrders / useOrders
//       params: ?page, ?page_size, ?ordering, ?search,
//               ?status, ?site, ?hosting, ?forwarded, ?date_from, ?date_to
//   GET  /orders/{id}/     -> getOrder / useOrder
//   GET  /orders/stats/    -> getOrderStats / useOrderStats
//   POST /orders/poll_now/ -> pollOrdersNow / usePollOrders (kick the Celery fan-out)
//       body: { status?, sites?: number[], date_from?, date_to? }
//   POST /orders/{id}/complete/ -> completeOrder / useCompleteOrder (push 'completed' to Woo)
//   GET  /orders/export_pdf/ -> exportOrdersPdf (PDF blob download)
//       params: ?ids=1,2,3 (selected orders) — or the active list filters when omitted

const clean = (params = {}) =>
  Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
  );

// Pull the server-suggested filename out of Content-Disposition, else fall back.
const filenameFromDisposition = (disposition, fallback) => {
  const match = /filename="?([^"]+)"?/.exec(disposition || "");
  return match ? match[1] : fallback;
};

// Download the selected orders as a single PDF (one order per page). Pass
// `ids` as an array of selected order ids; omit to export the current filters.
export async function exportOrdersPdf({ ids, ...params } = {}) {
  const query = clean({ ...params, ids: ids?.length ? ids.join(",") : undefined });
  const res = await api.get("/orders/export_pdf/", {
    params: query,
    responseType: "blob",
  });
  const filename = filenameFromDisposition(res.headers["content-disposition"], "don-hang.pdf");
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export const getOrders = (params = {}) =>
  api.get("/orders/", { params: clean(params) }).then((r) => r.data);

export const getOrder = (id) => api.get(`/orders/${id}/`).then((r) => r.data);

export const getOrderStats = (params = {}) =>
  api.get("/orders/stats/", { params: clean(params) }).then((r) => r.data);

export const pollOrdersNow = (body = {}) =>
  api.post("/orders/poll_now/", clean(body)).then((r) => r.data);

export const completeOrder = (id) =>
  api.post(`/orders/${id}/complete/`).then((r) => r.data);

const KEY = ["orders"];

// Server-side pagination/sort/filter: params live in the query key so any
// change (page / size / sort / filter / search) re-fetches from the backend.
export function useOrders(params = {}) {
  return useQuery({
    queryKey: [...KEY, "list", params],
    queryFn: () => getOrders(params),
    placeholderData: keepPreviousData,
  });
}

export function useOrderStats(params = {}) {
  return useQuery({
    queryKey: [...KEY, "stats", params],
    queryFn: () => getOrderStats(params),
    placeholderData: keepPreviousData,
  });
}

// Trigger the poll, then invalidate so the list/stats refetch the new orders.
export function usePollOrders() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: pollOrdersNow,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

// Mark one order completed (backend pushes to WooCommerce), then refetch.
export function useCompleteOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: completeOrder,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
