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
//               ?status, ?payment_status, ?platform, ?classification,
//               ?site, ?hosting, ?forwarded, ?date_from, ?date_to
//   GET  /orders/{id}/     -> getOrder / useOrder
//   GET  /orders/stats/    -> getOrderStats / useOrderStats
//   POST /orders/poll_now/ -> pollOrdersNow / usePollOrders (kick the Celery fan-out)
//       body: { status?, sites?: number[], date_from?, date_to?, platform? }
//   POST /orders/{id}/complete/  -> completeOrder / useCompleteOrder (push 'completed' to Woo)
//   POST /orders/{id}/cancel/    -> cancelOrder / useCancelOrder (push 'cancelled' to Woo/Sapo)
//   POST /orders/{id}/mark_paid/ -> markOrderPaid / useMarkOrderPaid (Sapo: record a paid transaction)
//   POST /orders/forward_bulk/  -> forwardOrdersBulk / useForwardOrdersBulk (Hub-internal, one-way)
//       body: { ids: number[] }
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

// Cancel one order on its WooCommerce/Sapo site (only pending/processing/on-hold).
export const cancelOrder = (id) =>
  api.post(`/orders/${id}/cancel/`).then((r) => r.data);

// Mark one Sapo order paid (backend records a 'sale' transaction on Sapo).
export const markOrderPaid = (id) =>
  api.post(`/orders/${id}/mark_paid/`).then((r) => r.data);

// Forward many selected orders to marketing at once; returns { forwarded: <count> }.
// Hub-internal, one-way (a completed order is forwarded automatically server-side).
export const forwardOrdersBulk = (ids) =>
  api.post("/orders/forward_bulk/", { ids }).then((r) => r.data);

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

// Feed for the notification bell: the latest "processing" ("chưa xử lý") orders,
// independent of the Orders page filters. Refetches on an interval and on window
// focus so orders pulled in by the periodic backend poll surface without a manual
// sync; a manual "Đồng bộ ngay" invalidates the ["orders"] key and refreshes this
// too. page_size caps the popover list.
export function useNewOrders({ enabled = true } = {}) {
  return useQuery({
    queryKey: [...KEY, "new", "processing"],
    queryFn: () =>
      getOrders({ status: "processing", ordering: "-date_created_woo", page_size: 20 }),
    enabled,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
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

// Cancel one order (backend pushes 'cancelled' to WooCommerce/Sapo), then refetch.
export function useCancelOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: cancelOrder,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

// Mark one Sapo order paid (backend records a transaction on Sapo), then refetch.
export function useMarkOrderPaid() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: markOrderPaid,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

// Forward the ticked orders to marketing in one request, then refetch.
export function useForwardOrdersBulk() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: forwardOrdersBulk,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
