import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api } from "./client.js";

// Endpoints (Hub backend only) — the master catalog lives here; pushing it to
// each WooCommerce site is an async Celery job triggered by sync_now:
//   GET    /products/           -> getProducts / useProducts
//       params: ?page, ?page_size, ?ordering, ?search, ?status, ?stock_status
//   GET    /products/{id}/      -> getProduct
//   GET    /products/stats/     -> getProductStats / useProductStats
//   POST   /products/           -> createProduct / useCreateProduct
//   PATCH  /products/{id}/      -> updateProduct / useUpdateProduct
//   DELETE /products/{id}/      -> deleteProduct / useDeleteProduct (soft-delete)
//   POST   /products/sync_now/  -> syncProducts / useSyncProducts (Celery fan-out)
//       body: { sites?: number[], products?: number[] }

const clean = (params = {}) =>
  Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
  );

export const getProducts = (params = {}) =>
  api.get("/products/", { params: clean(params) }).then((r) => r.data);

export const getProduct = (id) => api.get(`/products/${id}/`).then((r) => r.data);

export const getProductStats = (params = {}) =>
  api.get("/products/stats/", { params: clean(params) }).then((r) => r.data);

export const createProduct = (payload) =>
  api.post("/products/", payload).then((r) => r.data);

export const updateProduct = ({ id, ...payload }) =>
  api.patch(`/products/${id}/`, payload).then((r) => r.data);

export const deleteProduct = (id) =>
  api.delete(`/products/${id}/`).then((r) => r.data);

export const syncProducts = (body = {}) =>
  api.post("/products/sync_now/", clean(body)).then((r) => r.data);

const KEY = ["products"];

// Server-side pagination/sort/filter: params live in the query key so any
// change (page / size / sort / filter / search) re-fetches from the backend.
export function useProducts(params = {}) {
  return useQuery({
    queryKey: [...KEY, "list", params],
    queryFn: () => getProducts(params),
    placeholderData: keepPreviousData,
  });
}

export function useProductStats(params = {}) {
  return useQuery({
    queryKey: [...KEY, "stats", params],
    queryFn: () => getProductStats(params),
    placeholderData: keepPreviousData,
  });
}

function useInvalidatingMutation(mutationFn) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export const useCreateProduct = () => useInvalidatingMutation(createProduct);
export const useUpdateProduct = () => useInvalidatingMutation(updateProduct);
export const useDeleteProduct = () => useInvalidatingMutation(deleteProduct);

// sync_now only kicks the async push; the catalog rows don't change on success,
// but mappings/last_synced_at update once the task runs — invalidate so a later
// refetch shows them. (The task is async; we don't await its completion here.)
export const useSyncProducts = () => useInvalidatingMutation(syncProducts);
