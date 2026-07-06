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
//   GET    /products/categories/overview/     -> getCategoryOverview (stat cards)
//   GET    /products/categories/matrix/       -> getCategoryMatrix (Hub × sites pivot)
//       params: ?search, ?ordering, ?page, ?page_size  (response carries `sites`)
//   GET    /products/categories/{id}/sites/   -> getCategorySiteLinks (per-category)
//   GET    /products/categories/mappings/     -> getCategoryMappings (per-site mapping)
//       params: ?site (bắt buộc), ?search, ?ordering, ?page, ?page_size
//   POST   /products/categories/             -> createCategory / useCreateCategory
//       body: { name, slug?, parent?: number|null }  (parent = tree; null = root)
//   PATCH  /products/categories/{id}/        -> updateCategory / useUpdateCategory
//   DELETE /products/categories/{id}/        -> deleteCategory / useDeleteCategory (soft)
//   POST   /products/categories/pull_now/     -> pullProductCategories (Woo → Hub)
//       body: { sites?: number[] }  (bỏ trống = pull TẤT CẢ site)
//   POST   /products/categories/clear_all/    -> clearCategorySync (reset catalog)

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

// Import a site's products into the Hub catalog ("Nhập từ website chính").
// body: { site: number } (the source site id). Async Celery; returns run_id.
export const importProductsFromSite = (siteId) =>
  api.post("/products/import_from_site/", { site: siteId }).then((r) => r.data);

// Per-product sync state across every active site (đã/chưa đồng bộ + thời gian).
export const getProductSyncStatus = (id) =>
  api.get(`/products/${id}/sync_status/`).then((r) => r.data);

// Known categories for the form picker. The picker needs the FULL catalog
// (the TreeSelect filters client-side), so walk every page — a single request
// silently truncates once the catalog outgrows the server's page-size cap.
export const getProductCategories = async () => {
  const all = [];
  for (let page = 1; ; page += 1) {
    const { data } = await api.get("/products/categories/", {
      params: { page, page_size: 1000 },
    });
    all.push(...(data.results ?? data));
    if (!data.next) break;
  }
  return all;
};

// Trigger the async pull of categories from the sites (Woo → Hub).
// body.sites scopes the pull to those site ids; empty body = all sites.
export const pullProductCategories = (body = {}) =>
  api.post("/products/categories/pull_now/", clean(body)).then((r) => r.data);

// Reset the category catalog (soft-delete + clear mappings/history); keeps any
// category a live product still uses. Returns the cleared/kept counts.
export const clearCategorySync = () =>
  api.post("/products/categories/clear_all/").then((r) => r.data);

// Per-site category mapping rows (site → Hub) for the "Danh mục" page.
export const getCategoryMappings = (params = {}) =>
  api.get("/products/categories/mappings/", { params: clean(params) }).then((r) => r.data);

// Stat-card counts for the Tổng quan + Cây danh mục Hub tabs (independent of paging).
export const getCategoryOverview = () =>
  api.get("/products/categories/overview/").then((r) => r.data);

// Cross-site matrix: paginated Hub categories with per-site `cells`, plus the
// `sites` column headers — the Tổng quan tab renders one column per site.
export const getCategoryMatrix = (params = {}) =>
  api.get("/products/categories/matrix/", { params: clean(params) }).then((r) => r.data);

// One Hub category's link state on every live site (tree-tab detail panel).
export const getCategorySiteLinks = (id) =>
  api.get(`/products/categories/${id}/sites/`).then((r) => r.data);

// Hub-side category CRUD (the tree-management surface). `parent` is sent as-is
// (null = root); `clean()` is NOT used so an explicit `parent: null` reaches the
// backend to move a node to the top level.
export const createCategory = (payload) =>
  api.post("/products/categories/", payload).then((r) => r.data);

export const updateCategory = ({ id, ...payload }) =>
  api.patch(`/products/categories/${id}/`, payload).then((r) => r.data);

export const deleteCategory = (id) =>
  api.delete(`/products/categories/${id}/`).then((r) => r.data);

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

// Per-site mapping table: params (site/search/ordering/page) live in the key
// so every change re-fetches server-side. Disabled until a site is picked.
export function useCategoryMappings(params = {}) {
  return useQuery({
    queryKey: [...CAT_KEY, "mappings", params],
    queryFn: () => getCategoryMappings(params),
    enabled: params.site != null,
    placeholderData: keepPreviousData,
  });
}

// Dashboard stat cards — small, frequently shown; the pull mutation invalidates
// CAT_KEY (which this lives under) so the cards refresh after a sync settles.
export function useCategoryOverview() {
  return useQuery({
    queryKey: [...CAT_KEY, "overview"],
    queryFn: getCategoryOverview,
  });
}

// Cross-site matrix: params (search/ordering/page) live in the key so every
// change re-fetches server-side; keepPreviousData avoids a flash on paging.
export function useCategoryMatrix(params = {}) {
  return useQuery({
    queryKey: [...CAT_KEY, "matrix", params],
    queryFn: () => getCategoryMatrix(params),
    placeholderData: keepPreviousData,
  });
}

// Per-category site links for the tree-tab detail panel; disabled until a node
// is selected.
export function useCategorySiteLinks(id, { enabled = true } = {}) {
  return useQuery({
    queryKey: [...CAT_KEY, "site-links", id],
    queryFn: () => getCategorySiteLinks(id),
    enabled: enabled && id != null,
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

// Importing products from a site is async; the catalog changes once the task
// runs, so invalidate the product caches on settle (the banner polls the run).
export function useImportProductsFromSite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: importProductsFromSite,
    onSettled: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

// Pulling categories from sites is async; invalidate the picker cache on settle
// so it refreshes once the task has run.
export function useSyncCategories() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body) => pullProductCategories(body),
    onSettled: () => qc.invalidateQueries({ queryKey: CAT_KEY }),
  });
}

// Clearing the catalog is synchronous (pure DB on the backend); on success
// refresh both the category caches and the sync-report history (the run table
// is emptied by the clear).
export function useClearCategorySync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: clearCategorySync,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: CAT_KEY });
      qc.invalidateQueries({ queryKey: ["sync-reports"] });
    },
  });
}

// Hub-side category CRUD — each write invalidates the whole `CAT_KEY` prefix so
// the picker list, the tree, and the overview stat cards all refresh.
function useInvalidatingCategoryMutation(mutationFn) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => qc.invalidateQueries({ queryKey: CAT_KEY }),
  });
}

export const useCreateCategory = () => useInvalidatingCategoryMutation(createCategory);
export const useUpdateCategory = () => useInvalidatingCategoryMutation(updateCategory);
export const useDeleteCategory = () => useInvalidatingCategoryMutation(deleteCategory);
