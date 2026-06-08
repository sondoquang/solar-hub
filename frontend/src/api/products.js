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
//   GET    /products/{id}/sync_status/        -> getProductSyncStatus (per-domain)
//   GET    /products/categories/              -> getProductCategories (picker)
//   POST   /products/categories/pull_now/     -> pullProductCategories (Woo → Hub)

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

// Per-product sync state across every active site (đã/chưa đồng bộ + thời gian).
export const getProductSyncStatus = (id) =>
  api.get(`/products/${id}/sync_status/`).then((r) => r.data);

// Known categories for the form picker (a big page so the whole list comes back).
export const getProductCategories = () =>
  api
    .get("/products/categories/", { params: { page_size: 1000 } })
    .then((r) => r.data.results ?? r.data);

// Trigger the async pull of categories from the sites (Woo → Hub).
export const pullProductCategories = () =>
  api.post("/products/categories/pull_now/", {}).then((r) => r.data);

const KEY = ["products"];
const CAT_KEY = [...KEY, "categories"];

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

// One product's full detail (carries nested `mappings`) — used by the sync panel.
export function useProduct(id, { enabled = true } = {}) {
  return useQuery({
    queryKey: [...KEY, "detail", id],
    queryFn: () => getProduct(id),
    enabled: enabled && id != null,
  });
}

// Debounced server-side product search for the grouped-product picker.
export function useProductSearch(search) {
  return useQuery({
    queryKey: [...KEY, "search", search],
    queryFn: () => getProducts({ search, page_size: 20 }),
    enabled: !!search,
    placeholderData: keepPreviousData,
  });
}

// Categories rarely change within a session; cache to avoid refetch churn while
// the form is open. The pull mutation invalidates this on settle.
export function useProductCategories() {
  return useQuery({
    queryKey: CAT_KEY,
    queryFn: getProductCategories,
    staleTime: 5 * 60_000,
  });
}

export function useProductSyncStatus(id, { enabled = true } = {}) {
  return useQuery({
    queryKey: [...KEY, "sync_status", id],
    queryFn: () => getProductSyncStatus(id),
    enabled: enabled && id != null,
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

// Pulling categories from sites is async; invalidate the picker cache on settle
// so it refreshes once the task has run.
export function useSyncCategories() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: pullProductCategories,
    onSettled: () => qc.invalidateQueries({ queryKey: CAT_KEY }),
  });
}
