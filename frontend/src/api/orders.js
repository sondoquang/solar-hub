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

const clean = (params = {}) =>
  Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
  );

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
