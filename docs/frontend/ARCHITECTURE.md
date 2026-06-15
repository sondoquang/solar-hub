# ARCHITECTURE.md — Frontend

> Vị trí: `docs/frontend/ARCHITECTURE.md`. Context gốc: `/CLAUDE.md`. Luật code: `docs/frontend/PROJECT_RULE.md`.

Kiến trúc **frontend** của Solar Hub — dashboard quản trị cho đội admin & marketing.

---

## 1. Bối cảnh

Frontend là **client thuần** của backend Solar Hub (Django + DRF). Nó hiển thị đơn hàng gom từ nhiều website WooCommerce, cho phép CRUD master catalog và kích hoạt đồng bộ, và giám sát trạng thái site.

Frontend **không chứa logic nghiệp vụ tích hợp**: không gọi WooCommerce, không build payload sản phẩm Woo, không gom đơn. Tất cả việc đó ở backend (xem `docs/backend/ARCHITECTURE.md`). Frontend chỉ **hiển thị dữ liệu** và **gửi lệnh** tới Hub.

## 2. Sơ đồ tổng thể

```
  ┌──────────────────────────────┐        ┌─────────────────┐        ┌──────────┐
  │  Browser (React + Vite)      │        │  HUB Backend     │        │ WooComm. │
  │  React Query  ──axios──►──────┼─REST──►│  Django + DRF    │──REST─►│  site 1  │
  │  Router · Tailwind           │◄──JSON─┤  (SSOT)          │◄──────►│  site 2  │
  └──────────────────────────────┘        └─────────────────┘        └──────────┘
        ▲ frontend CHỈ nói chuyện với Hub          ▲ Hub mới nói chuyện với WooCommerce
```

Ranh giới then chốt: **frontend ↔ Hub** (REST `/api/...`). Frontend **không** có đường nối tới WooCommerce.

## 3. Cấu trúc & trách nhiệm

| Thư mục | Trách nhiệm |
|---|---|
| `src/api/` | axios instance + hàm gọi endpoint + React Query hooks. Ranh giới dữ liệu duy nhất với backend. |
| `src/pages/` | Màn theo route (Dashboard, Orders, Products, Sites, Login). Lắp ráp, mỏng. |
| `src/components/` | UI tái dùng, presentational (`DataTable`, StatusDot, EmptyState, ErrorState, các Form...). Bảng dữ liệu đi qua `DataTable` (bọc antd `<Table>`): chọn cột + phân trang server-side + ellipsis + refresh — xem PROJECT_RULE §7a. |
| `src/hooks/` | Custom hook UI (filter, debounce). Không fetch data ở đây. |
| `src/lib/` | Helper thuần: format tiền VND, ngày, transform dữ liệu. |
| `src/routes.jsx` | Khai báo router + guard auth. |

## 4. Các màn hình

- **Dashboard (`/`)** — tổng quan: số đơn mới/đã forward, trạng thái sync gần nhất, đèn up/down từng site.
- **Đơn hàng (menu nhóm, 2 sub-tab)** — sidebar gộp `Đơn hàng` thành `NavGroup` với 2 mục con: **WooCommerce** (`/orders`) và **Sapo** (`/sapo-unpaid-orders`). Mỗi màn ghim cứng `platform` ở cả phần hiển thị (`useOrders`/`useOrderStats`) lẫn nút **Đồng bộ ngay** (`poll_now {platform}`) nên không bao giờ lẫn đơn giữa 2 nền tảng.
- **Orders / WooCommerce (`/orders`)** — *quan trọng nhất* (đã hiện thực, gom đơn theo polling, **ghim `platform=woocommerce`**): bảng đơn gom từ mọi site WooCommerce (read-only), 3 thẻ tổng hợp (tổng đơn / tổng doanh thu / chưa chuyển marketing), lọc theo website-hosting / trạng thái / cờ forwarded / khoảng ngày + tìm kiếm (số đơn, tên/SĐT khách), sort `date_created_woo`/`total`, modal chi tiết (thông tin KH + bảng `line_items`), nút **Đồng bộ ngay** gọi `POST /orders/poll_now/`. API ở `src/api/orders.js` (`useOrders`/`useOrderStats`/`usePollOrders` — poll xong invalidate `["orders"]`); component `OrderStats`/`OrderStatusBadge`/`OrderDetailModal`. **Banner tiến trình:** `poll_now` trả `{run_id, expected}` → `useSyncRunProgress(SYNC_OPS.orders)` (xem `src/api/syncReports.js`) hiện `Alert` "Đang đồng bộ đơn hàng… X/Y site hoàn tất" và poll `/sync/run-progress/` mỗi 3s tới khi xong (hoặc quá hạn 3 phút) → toast + invalidate `["orders"]`, giống cơ chế trang Danh mục — để người dùng biết tiến trình còn chạy và làm việc khác.
- **Orders / Sapo (`/sapo-unpaid-orders`)** — đơn Sapo **chưa thanh toán** (ghim `platform=sapo` + `payment_status=unpaid`): bảng read-only (badge trạng thái thanh toán), lọc theo website Sapo / khoảng ngày + tìm kiếm; nút **Đồng bộ ngay** gọi `poll_now {platform: "sapo"}` (backend tự scope toàn bộ site Sapo, dedup theo store + gate `SAPO_ORDER_POLL_ENABLED`); 2 action mỗi dòng — **Đánh dấu đã thanh toán** (`mark_paid`) và **Hủy đơn** (`cancel`) — đẩy thay đổi lên Sapo rồi re-sync. WooCommerce không bao giờ xuất hiện ở đây.
- **Products (`/products`)** — danh sách + **Drawer form kiểu WooCommerce** (`ProductRegisterForm`): chọn **loại sản phẩm** (simple/grouped/external/variable) → Tabs dữ liệu sản phẩm đổi theo loại (giá/tồn, liên kết ngoài, sản phẩm nhóm theo SKU, hoặc **thuộc tính + bảng biến thể** với nút "Tạo tất cả biến thể" = cartesian); mô tả/mô tả ngắn dùng `RichTextEditor` (TipTap — riêng **mô tả** bật `enableImage`: nút chèn ảnh mở thư viện media, ảnh **chèn vào cuối nội dung đang viết** + paragraph trống để viết tiếp); **ảnh sản phẩm**: ảnh đại diện (`images[0]`) + **album ảnh phụ** (`images[1..]`) đều chọn qua **`MediaLibraryModal`** (kiểu WP Media Library: tab "Tải tệp lên" upload multipart → `POST /products/media/`, tab "Thư viện" tick từ ảnh đã có, search + phân trang; `onSelect` trả URL tuyệt đối do Hub host — **không dán link ngoài**), ảnh biến thể trong bảng variations cũng chọn từ thư viện; API hooks ở `src/api/media.js` (`useMediaImages`/`useUploadMedia`, query key `["media"]`); **danh mục** tick từ danh sách có sẵn (kéo từ site về) + thêm mới, nút "Cập nhật từ site". Nút **Đồng bộ ngay** (đẩy toàn catalog xuống mọi site, kích hoạt task ở backend) + mỗi dòng có nút **Trạng thái đồng bộ** mở `ProductSyncStatusModal` (xem §5.3). **Banner tiến trình** (cả nút trang lẫn nút "Đồng bộ site đã chọn" trong modal): `sync_now` trả `{run_id, expected}` → `useSyncRunProgress(SYNC_OPS.products)` hiện `Alert` "Đang đồng bộ sản phẩm… X/Y site hoàn tất", poll `/sync/run-progress/` tới khi xong → toast + invalidate `["products"]` (modal invalidate `["products","sync_status",id]`).
- **Danh mục (`/categories`)** — xem **mapping danh mục theo từng website**: chọn website (Select showSearch, nguồn `useAllSites`) → bảng danh mục của site đó (Woo ID, **tên trên site** — `woo_name` raw, danh mục Hub nó gộp về + danh mục cha, đồng bộ lần cuối; phân trang/sort/search server-side qua `GET /products/categories/mappings/?site=`). Nút **Đồng bộ danh mục** mở `CategoryPullModal` chọn site rồi gọi `pull_now {sites}` — xem §5.3.
- **Sites (`/sites`)** — danh sách website, trạng thái up/down, **cột Hosting** + hàng bộ lọc: **trạng thái** (`?status=up|down|unknown`), **loại trang** (`?is_primary=` — Trang chính / Trang thường) và **hosting** (gồm "Chưa gán hosting"); form đăng ký site (nhập base_url + key — key chỉ gửi đi, không hiển thị lại; chọn hosting tùy chọn; switch **Trang chính**). **Trang chính** (`is_primary`): icon sao cạnh tên site là nút toggle nhanh (PATCH `is_primary`), backend xếp trang chính lên đầu danh sách mặc định và healthcheck trước trong mỗi round. Mỗi dòng có nút **Ghi chú** mở modal nhật ký ghi chú (rich-text + đính kèm ảnh, mới nhất lên đầu).
- **Hostings (`/hostings`)** — quản lý hosting (nhóm site): CRUD hosting, xem sức khỏe gom theo hosting (số site + đếm up/down/unknown), chỉnh `check_concurrency`, nút **Check ngay** chạy healthcheck cả nhóm (throttle ở backend).
- **Health Checks (`/health-checks`)** — *Lịch sử kiểm tra sức khỏe*: bảng các lần kiểm tra website (read-only), 4 thẻ tổng hợp (tổng/khỏe mạnh/cảnh báo/lỗi nghiêm trọng + % và trend), lọc theo trạng thái / website-hosting / khoảng ngày / tìm kiếm, modal xem chi tiết, nút **Xuất báo cáo** (CSV).
- **Login (`/login`)** — đăng nhập lấy token.

## 5. Luồng dữ liệu

### 5.1. Đọc (queries)

Component gọi React Query hook trong `src/api/` → axios gọi DRF → dữ liệu được cache theo **query key** (`["orders", filters]`, `["products"]`, `["sites"]`, `["hostings"]`). UI render theo 3 trạng thái loading/error/empty. Đơn hàng bật `refetchInterval`/`refetchOnWindowFocus` để cập nhật gần real-time.

### 5.2. Ghi (mutations)

Form (tạo/sửa sản phẩm, đăng ký site, bấm Sync all) gọi mutation hook → POST/PATCH lên DRF → thành công thì **invalidate** query liên quan để UI tự refresh, kèm **toast** báo kết quả. Thất bại thì giữ form và hiển thị lỗi từ server.

### 5.3. Đồng bộ sản phẩm (từ phía FE)

FE **không** tự đẩy sản phẩm xuống site. Bấm "Sync all" chỉ gọi một endpoint backend để **kích hoạt Celery task**; FE sau đó poll/hiển thị trạng thái sync (`SyncLog`/mapping) trả về từ Hub.

**Trạng thái đồng bộ theo domain** (`ProductSyncStatusModal`): mở từ nút "Trạng thái đồng bộ" mỗi sản phẩm → gọi `GET /products/{id}/sync_status/` (backend trả mọi site active kèm cờ `synced` + `last_synced_at` + `woo_product_id` + `site_status` up/down/unknown + `site_url` + `is_primary`), bảng sắp **chưa-đồng-bộ lên trước**, cột Website hiện tên + domain + sao trang chính, có cột **Trạng thái web** (`StatusDot`) + hàng bộ lọc client-side: **tìm theo domain** (Input), **Loại trang** (Trang chính / Trang thường) và **Trạng thái web**; đổi bất kỳ filter nào sẽ bỏ tick các site bị ẩn để không push nhầm, tick chọn site (hoặc "Chọn site chưa đồng bộ" — chỉ trong các site đang hiển thị) rồi **Đồng bộ site đã chọn** → `syncProducts({sites, products:[id]})`. **Danh mục 2 chiều (cây):** picker là antd `TreeSelect` (multiple) dựng **cây như WooCommerce** từ danh sách phẳng `GET /products/categories/` (mỗi item có `parent` id → FE build nested treeData, value = tên danh mục); chọn cha/con độc lập, không cascade. "Cập nhật từ site" gọi `POST /products/categories/pull_now/` (kéo danh mục + quan hệ cha–con Woo→Hub; gọi không body = pull TẤT CẢ site).

**Trang Danh mục (`/categories`, `src/pages/Categories.jsx`)** — **dashboard 3 tab** (antd `Tabs`, render động từ API): **Tổng quan / Cây danh mục Hub / Lịch sử đồng bộ**. Container giữ **pull trigger + poll run** ở cấp trang (nút primary "Đồng bộ danh mục" toàn cục): `triggerPull(siteIds)` dùng chung cho `CategoryPullModal` (multi-site) lẫn panel PULL inline tab Tổng quan (1 site); `pull_now` trả `{task_id, run_id}` → giữ `activeRun {runId, expected, startedAt}` + poll `useCategoryRun(runId, {refetchInterval: 3s, retry: false})`, banner `Alert` "Đang đồng bộ… x/y site"; xong → toast + invalidate `["products","categories"]` (overview/matrix/site-links) và `["sync-reports"]` (runs/stats); safety stop 3 phút. Cạnh nút primary còn có nút **danger "Xóa toàn bộ danh mục đồng bộ"** → `Modal.confirm` (cảnh báo: ẩn danh mục/mapping/lịch sử, **giữ danh mục đang có sản phẩm dùng**, nên pull site chính trước) → `useClearCategorySync().mutateAsync()` (mutation **đồng bộ**, gọi `POST /products/categories/clear_all/`, `onSuccess` invalidate cả `CAT_KEY` + `["sync-reports"]`) → toast kèm số liệu `{categories_cleared, categories_kept, mappings_cleared}` trả về.
- Hooks mới `src/api/products.js`: `useCategoryOverview` (key `[...CAT_KEY,"overview"]`), `useCategoryMatrix(params)` (`[...CAT_KEY,"matrix",params]`, `keepPreviousData`), `useCategorySiteLinks(id,{enabled})` (`[...CAT_KEY,"site-links",id]`); `src/api/syncReports.js`: `useCategoryRunStats(params)` + `useCategoryRuns` nhận thêm `status/site/date_from/date_to/search`. Helper `formatDuration(seconds)` (mm:ss / hh:mm:ss) ở `src/lib/format.js`.
- **Banner tiến trình dùng chung** (`src/api/syncReports.js`): `useRunProgress(runId, operation, opts)` (query `/sync/run-progress/{runId}/?operation=`, không 404, trả `{done, error_count}`) và hook điều phối `useSyncRunProgress(operation, {onFinish})` (giữ `activeRun {runId, expected, startedAt}`, poll 3s, gọi `onFinish({finished, timedOut, expected, errorCount})` một lần khi `done ≥ expected`/quá hạn 3 phút rồi clear). `SYNC_OPS = {orders:"poll_orders", products:"push_products", categories:"pull_categories"}`. Dùng ở trang Đơn hàng, Sản phẩm và `ProductSyncStatusModal` để hiện `Alert` "Đang đồng bộ… X/Y site" (cùng UX với trang Danh mục).
- **Tổng quan** (`CategoryOverviewTab`): 4 thẻ thống kê (`StatCards` — component grid dùng chung) từ `useCategoryOverview`; panel PULL (`Select` 1 site + nút → `onPull`); "Lịch sử gần đây" (`useCategoryRuns({page_size:5})`); **ma trận cross-site** (`DataTable` cột cố định Danh mục Hub/Cha/Số site + **cột động sinh từ `data.sites`**, mỗi ô = `ID + tên RAW` hoặc "—") — search debounce + sort (name/linked_site_count) + phân trang server-side.
- **Cây danh mục Hub** (`CategoryTreeTab`): 4 thẻ (tổng/gốc/con/đã xóa); cây antd `Tree` dựng client-side từ `useProductCategories()` (số trên node = kích thước subtree, có search highlight + auto-expand); chọn node → panel chi tiết (slug/cha/số con trực tiếp/số site = `mapping_count`) + bảng "Liên kết với website" từ `useCategorySiteLinks(id)` (`StatusDot` + ID/tên RAW trên site + `last_synced_at`).
- **Lịch sử đồng bộ** (`CategorySyncHistoryTab`): 5 thẻ từ `useCategoryRunStats` (tổng/thành công/một phần/thất bại/lần gần nhất); filter bar (`Select` kết quả + `RangePicker` + `Select` site + search debounce — cùng payload cho stats & list); `DataTable` run (Run ID rút gọn `SYNC-…`, Người chạy `triggered_by` (fallback "Hệ thống"), thời gian bắt đầu, Website `site_label`/"N site", `RunStatusTag`, Tổng/Đã ánh xạ/Lỗi, **Thời gian** `formatDuration`); nút Xem chi tiết → `CategoryRunDetailModal` (đã có) + Xuất Excel.
- `CategoryPullModal` (presentational, props `open/onClose/onConfirm(siteIds)/confirming`) giữ nguyên; `src/api/sites.js#useAllSites` dùng cho cả modal + filter site. Đủ loading/error/empty mọi khối.

## 6. Quản lý state

- **Server state** (dữ liệu từ Hub): **React Query** lo cache, refetch, invalidate. Đây là phần lớn state của app.
- **UI state** (filter đang chọn, modal, form): `useState`/`useReducer` cục bộ.
- Không Redux. Nếu phát sinh global UI state phức tạp → Zustand, và ghi lý do tại đây.

## 7. Tầng tích hợp API

`src/api/client.js`: một axios instance, `baseURL` từ `VITE_API_BASE_URL`, interceptor đính token + xử lý lỗi tập trung (401 → login, 5xx → toast). Dữ liệu được parse/validate ở ranh giới này để component nhận shape ổn định.

## 8. Xác thực

Đăng nhập tại `/login` → backend trả token → token đính vào mọi request qua interceptor → route nội bộ bọc guard, chưa auth thì về `/login`. Cách lưu token (cookie httpOnly do backend set, hay giữ trong bộ nhớ + refresh) chốt cùng backend; **không** lưu token nhạy cảm ở `localStorage` thường. *(Cập nhật mục này khi chốt cơ chế với backend.)*

## 9. Quyết định thiết kế (tóm tắt)

| Quyết định | Lý do |
|---|---|
| FE chỉ nói chuyện với Hub | Tách biệt; logic tích hợp WooCommerce thuộc backend (SSOT). |
| React Query cho server state | Cache/refetch/invalidate sẵn; hợp dashboard cần gần real-time. |
| Một axios instance + interceptor | Cấu hình baseURL/token/lỗi tập trung, không lặp. |
| baseURL qua env | Local/prod chỉ khác `.env`, không sửa code. |
| JSX (JS) trước, TS sau | Đi nhanh theo nền tảng hiện có; có lối nâng cấp khi cần. |
| Tailwind + design token | Nhất quán, nhanh; tránh CSS rời rạc. |
| Bắt buộc loading/error/empty | Công cụ vận hành phải đáng tin, không màn trắng. |
| `react-hook-form` + `zod` cho form đăng ký site | Form phức tạp (rule §8); validate client + nhận lỗi server. |
| `react-hot-toast` cho phản hồi mutation | Rule §9 yêu cầu toast; lib nhẹ, dùng chung qua `<Toaster/>` ở `main.jsx`. |
| **Ant Design (antd) làm UI chủ đạo** | Dựng giao diện vận hành nhanh (Table/Form/Modal/Select/DatePicker sẵn, có sort/filter/pagination). Tailwind hạ xuống vai trò tinh chỉnh. Đánh đổi: bundle nặng hơn (~+170 kB gzip). |
| **lucide-react** cho icon | Nhẹ, tree-shakeable, hợp Tailwind; truyền thẳng vào prop `icon` của antd. |
| **TipTap** cho rich-text ghi chú | Headless, output HTML sạch, hợp React 18; tự dựng toolbar bằng antd nên đồng bộ UI. Ảnh để riêng (đính kèm), không inline. |
| **DOMPurify** khi render note HTML | Phòng thủ theo lớp — backend đã sanitize bằng nh3 khi lưu, FE sanitize lần nữa lúc `dangerouslySetInnerHTML`. |
| Tắt Tailwind `preflight`, dùng `antd/dist/reset.css` | Tránh hai reset CSS đá nhau; antd là chủ đạo nên để reset của antd làm nền. |

## 9b. Trạng thái hiện thực (Phase 1 — Sites)

Trang **Sites (`/sites`)** đã hiện thực: `src/api/sites.js` (hooks `useSites/useSiteStats/useCreateSite/useUpdateSite/useDeleteSite/useTestConnection/useTestConnections/useImportSites`; query key danh sách `["sites","list", params]` mang `page/page_size/ordering/hosting`, stats `["sites","stats"]`; mutation invalidate prefix `["sites"]` nên cả list lẫn stats refresh). Components: `StatusDot` (chấm màu + nhãn up/down/tạm dừng), `SiteRegisterForm` (react-hook-form + zod, dùng chung cho **tạo và sửa** — edit thì secret optional), `DataTable` (bảng dùng chung, xem §3 + PROJECT_RULE §7a), `SiteImport` (modal chọn hosting đích + upload `.xlsx`), `SiteStats` (4 thẻ tổng hợp: tổng / hoạt động / tạm dừng / không hoạt động — lấy từ endpoint `/sites/stats/`, đúng kể cả khi list đã phân trang). Tính năng:
- **Import Excel** hàng loạt qua **modal**: chọn hosting đích (tùy chọn) + chọn file rồi bấm import (file parse ở backend, mọi site được gán vào hosting đã chọn) → toast tóm tắt created/errors.
- **Thêm/Sửa** site qua antd `Modal` (form nằm trong modal; PATCH với secret để trống = giữ nguyên).
- Nút **Test** mỗi site có loading ("Đang kiểm tra…") + disable chống spam (dựa `mutation.isPending`/`variables`).
- **Tick chọn nhiều site** (antd `rowSelection`, `preserveSelectedRowKeys` giữ chọn qua các trang) + "Kiểm tra đã chọn" gọi bulk `test_connections`.
- **Phân trang/sort/lọc server-side**: page + page_size + ordering (sort tên qua DRF `OrderingFilter`) + hosting đều là query param → đổi gì cũng gọi lại API. Đổi page size hoặc sort thì reset về trang 1.
- Đủ loading/error/empty (qua `DataTable.loading` + `locale.emptyText` + `ErrorState`); toast cho mọi mutation; `consumer_secret` chỉ gửi đi, không hiển thị lại.
- **Đa nền tảng (WooCommerce | Sapo Web)**: `SiteRegisterForm` có `Select` "Nền tảng" (`platform`, mặc định woocommerce); chọn Sapo thì nhãn credential đổi thành **API key/API secret** (Private App của store Sapo) + placeholder `https://store.mysapo.net`, kèm hint hướng dẫn. Bảng Sites hiển thị `Tag` Woo/Sapo cạnh tên và có dropdown lọc **"Nền tảng"** (server-side, query param `?platform=`). Import Excel nhận thêm cột tùy chọn `platform` (woocommerce | sapo). Field API giữ nguyên tên `consumer_key`/`consumer_secret` — chỉ đổi nhãn hiển thị. Cột "Woo ID" ở `ProductSyncStatusModal` và trang Danh mục đổi nhãn thành **"ID trên site"** (field vẫn là `woo_product_id`/`woo_category_id` — remote id chung mọi nền tảng; row sync_status có thêm `platform` để chú thích "(Sapo)").

**Ghi chú website (Site Notes)** đã hiện thực: `src/api/siteNotes.js` (hooks `useSiteNotes/useCreateSiteNote/useUpdateSiteNote/useDeleteSiteNote`; query key `["site-notes", siteId, params]` scope theo từng site; create/update/delete dùng **FormData multipart** — `images` append nhiều lần, `remove_image_ids` để gỡ ảnh khi sửa — và invalidate `["site-notes", siteId]`). Components:
- `RichTextEditor` — trình soạn **TipTap** (`StarterKit` + `Underline` + `Link`, thêm `Image` khi bật), thanh công cụ antd `Button` + icon lucide (đậm/nghiêng/gạch chân/gạch ngang, tiêu đề H2/H3, danh sách, trích dẫn, link, xóa định dạng). Output HTML qua `onChange`. Prop **`enableImage`** (mặc định tắt): thêm nút chèn ảnh mở `MediaLibraryModal`, ảnh chèn vào **cuối** document + paragraph trống (luồng viết → chèn → viết tiếp); ghi chú site **không bật** — ảnh note vẫn là đính kèm riêng. Style nội dung qua class `.richtext` ở `src/index.css` (khôi phục heading/list mà Tailwind preflight đã reset; `.richtext img` max-width 100%).
- `SiteNotesModal` — mở từ nút "Ghi chú" ở bảng Sites: khu **soạn mới/sửa** trên cùng (`RichTextEditor` + antd `Upload listType="picture-card"` giữ file client-side bằng `beforeUpload={() => false}`, nút Lưu/Cập nhật, validate phải có nội dung hoặc ảnh) + **lịch sử** dưới (mới nhất trước, mục đầu gắn nhãn "Mới nhất", phân trang antd `Pagination`). Mỗi note render HTML qua **DOMPurify** (lớp sanitize thứ 2 khi render; backend đã sanitize khi lưu), ảnh xem lớn bằng antd `Image.PreviewGroup`, có nút Sửa (nạp lại nội dung + ảnh, cho thêm/bớt) và Xóa (`Popconfirm`, soft-delete ở backend). Đủ loading (`Skeleton`)/error (`ErrorState`)/empty (`Empty`).

**Hosting (`/hostings`)** đã hiện thực: `src/api/hostings.js` (hooks `useHostings/useCreateHosting/useUpdateHosting/useDeleteHosting/useCheckHosting`, query key danh sách `["hostings","list", params]`; mutation invalidate cả `["hostings"]` và `["sites"]` vì đổi hosting ảnh hưởng danh sách site). Component `HostingRegisterForm` (react-hook-form + zod, dùng chung tạo/sửa) + trang `Hostings` (dùng `DataTable`, phân trang server-side, đếm sức khỏe gom theo nhóm, `Popconfirm` khi xóa, nút "Check ngay"). Trang Sites thêm dropdown lọc theo hosting (server-side, có "Chưa gán hosting") + cột Hosting; `SiteRegisterForm` thêm `Select` chọn hosting (tùy chọn, nguồn từ `useHostings`).

**Health Checks (`/health-checks`)** đã hiện thực: `src/api/healthChecks.js` (hooks `useHealthChecks`/`useHealthCheckStats` + hàm `exportHealthChecks` tải CSV blob; query key `["healthchecks","list",params]` / `["healthchecks","stats",params]` mang đủ filter nên đổi filter là refetch; **read-only**, không mutation). Components: `HealthCheckStats` (4 thẻ, % suy từ total + trend từ `stats.trend_pct`), `HealthStatusBadge` (badge 3 mức healthy/warning/critical), `HealthCheckDetailModal` (antd `Descriptions`). Trang `HealthChecks` dùng `DataTable` (phân trang/sort server-side `checked_at`+`response_time_ms`), filter bar: `RangePicker` (ngày) + `Select` trạng thái + `Select` gộp nhóm website/hosting (value mã hóa `site:<id>`/`hosting:<id>`) + ô search debounce 350ms. Helper format mới ở `src/lib/format.js`: `formatDateTime` (kèm giây) + `formatResponseTime` (`256 ms` / `1.25 s`). Stats + export dùng **chung** payload filter với list. Đủ loading/error/empty.

**Orders (`/orders`)**: `src/api/orders.js` (hooks `useOrders/useOrderStats/usePollOrders/useCompleteOrder/useCancelOrder/useForwardOrdersBulk` + hàm `exportOrdersPdf` tải PDF blob; list endpoint trả đủ `line_items` + thông tin khách trong mỗi row nên modal chi tiết **không fetch thêm**). Trang dùng `DataTable` (phân trang/sort server-side, filter bar: ngày + trạng thái + marketing + **phân loại** + gộp website/hosting + search debounce). Xem chi tiết theo kiểu **carousel dùng chung một modal** `OrderDetailModal` (nhận **mảng** đơn):
- Thân đơn tách ra component presentational `OrderDetailContent` (Descriptions + bảng line items), dùng cho cả xem 1 đơn lẫn carousel; dòng **"Phân loại"** hiển thị `ClassificationBadge` + điểm rủi ro + danh sách lý do (`risk_reasons_display`).
- **Phân loại đơn (chống bot/spam)**: backend chấm điểm rủi ro mỗi đơn → cột **"Phân loại"** dùng `ClassificationBadge` (3 mức Hợp lệ/Nghi ngờ/Spam-bot, xanh/hổ phách/đỏ + điểm), filter `Select` "Phân loại" (`?classification=`), thẻ stats **"Nghi ngờ / Spam"** đếm từ `stats.by_classification`. Đơn nghi ngờ/spam **không** tự forward marketing (backend gate); admin xem lý do rồi forward tay.
- **Tick chọn nhiều đơn** (antd `rowSelection` + `preserveSelectedRowKeys`; kèm `Map` id→row trong trang để giữ đủ object qua các trang) → nút **"Xem chi tiết (N)"** ở `toolbarExtra` mở modal duyệt lần lượt. Nút "Xem chi tiết" mỗi dòng vẫn mở modal với 1 đơn (ẩn thanh điều hướng).
- Điều hướng carousel: nút Trước/Sau + dot indicators (click) + phím ←/→ + lăn chuột (throttle 350ms); badge "Đơn x/N". "Đánh dấu hoàn thành" (chỉ đơn `processing`) và "Hủy đơn" (chỉ `pending`/`processing`/`on-hold`, nút **danger** bọc `Popconfirm` — **bắt buộc xác nhận** vì đẩy `cancelled` lên WooCommerce, không hoàn tác) áp dụng cho đơn đang xem, xong thì sang đơn kế (hết thì đóng). Đơn hoàn thành **tự động** coi như đã chuyển marketing nên modal không còn nút chuyển marketing.
- **Chuyển marketing hàng loạt**: tick chọn nhiều đơn → nút **"Chuyển marketing (N)"** ở `toolbarExtra` gọi `useForwardOrdersBulk` (POST `/orders/forward_bulk/`), toast số đơn đã chuyển + bỏ chọn; React Query invalidate refresh cột "Marketing" (Đã chuyển/Chưa chuyển).
- **Xuất PDF phiếu đơn hàng** (cho bộ phận kinh doanh) — hai lối vào, cùng gọi `exportOrdersPdf({ ids })` (GET `/orders/export_pdf/?ids=…`, tải blob, tên file lấy từ `Content-Disposition`): (1) tick chọn nhiều đơn → nút **"Xuất PDF (N)"** ở `toolbarExtra` xuất đúng các đơn đã chọn (một file, mỗi đơn một trang); (2) trong `OrderDetailModal` nút **"Xuất PDF"** ở footer xuất đơn đang xem. Có trạng thái `loading` chống double-click + toast thành công/thất bại.

**Đơn Sapo chưa thanh toán (`/sapo-unpaid-orders`)**: trang riêng cho nghiệp vụ Sapo (chỉ quan tâm **trạng thái thanh toán**). Dùng chung `src/api/orders.js` + query key `["orders"]`, ghim filter `platform=sapo` + `payment_status=unpaid` (đơn Woo không bao giờ lọt vào). `DataTable` rút gọn (bỏ phân loại/marketing/PDF), filter bar: ngày + gộp website Sapo (`useSites({platform:"sapo"})`) + search debounce; cột **"Trạng thái thanh toán"** dùng `PaymentStatusBadge` (mirror `OrderStatusBadge`). Mỗi dòng đúng **2 thao tác** bọc `Popconfirm`: **Đánh dấu đã thanh toán** (`useMarkOrderPaid` → POST `/orders/{id}/mark_paid/`, ẩn khi đã paid/đã hủy) và **Hủy đơn** (`useCancelOrder`, nút danger); cả hai invalidate `["orders"]` nên đơn vừa thanh toán/hủy rời danh sách. "Đồng bộ ngay" gọi `usePollOrders` scope các site Sapo (backend tự layer `financial_status=unpaid`). ⚠️ Đơn thanh toán ngoài luồng (trực tiếp trên Sapo) không được kéo về cập nhật — chỉ thao tác qua Hub mới chắc chắn đồng bộ.

**Báo cáo (`/reports`)** đã hiện thực (v1: báo cáo đồng bộ danh mục): `src/api/syncReports.js` (hooks `useCategoryRuns` — query key `["sync-reports","category-runs", params]`, `keepPreviousData` — và `useCategoryRun(runId, {enabled})` — key `["sync-reports","category-run", runId]`; hàm `exportCategoryRun(runId)` tải **Excel .xlsx** blob, tên file từ `Content-Disposition`; **read-only**, không mutation). Trang `Reports` dùng `DataTable` phân trang server-side: mỗi dòng là **một lần bấm "Đồng bộ danh mục"** (group theo `run_id` ở backend) với thời gian (`formatDateTime`), số site, tổng danh mục/đã ánh xạ, `RunStatusTag` (Thành công/Một phần/Lỗi + đếm site lỗi), nút Xem chi tiết + Xuất Excel (loading per-row). `CategoryRunDetailModal` (mirror shell `ProductSyncStatusModal`): bảng per-site (website/hosting/kết quả/số danh mục/lỗi) **expand** ra bảng snapshot danh mục (Woo ID + tên trên site → Hub ID + tên trong Hub), footer Xuất Excel. Đủ loading/error/empty (empty ghi chú: các lần đồng bộ trước khi có tính năng không được liệt kê; run đang chạy hiện dần từng site — bấm refresh).

**Khung app (`AppLayout`)**: layout dạng **sidebar trái** (logo Solar Hub, nav có icon, thẻ hỗ trợ ở đáy) + **topbar** (chuông thông báo + hồ sơ người dùng). Mục nav có `children` render qua component dùng chung **`NavGroup`** (mở rộng/thu gọn, tự mở khi route hiện tại thuộc nhóm; sidebar collapsed thì chỉ hiện icon link tới route chính của nhóm): **Sản phẩm** gồm Danh sách sản phẩm (`/products`) / Danh mục (`/categories`); **Website** gồm Hosting / Quản lý website / Lịch sử kiểm tra. Các route đã có (`/`, `/orders`, `/sapo-unpaid-orders`, `/products`, `/categories`, `/sites`, `/hostings`, `/health-checks`, `/reports`, `/login`) dùng `NavLink` (mục "Đơn Sapo chưa TT" là `NavRow` phẳng cạnh "Đơn hàng"); mục chưa có route (Khách hàng, Cài đặt hệ thống) là placeholder tĩnh, sẽ nối route khi dựng.

**Hồ sơ người dùng ở topbar (`UserMenu`)**: hiển thị avatar (chữ cái đầu), `full_name` + `role` (lấy từ `/auth/me/`). Click mở **antd `Dropdown`** với 3 mục: **Cập nhật** (modal sửa `full_name`+`email`, gọi `PATCH /auth/me/` qua `api/auth.js#updateProfile`, rồi `useAuth().updateUser` để cập nhật ngay), **Đổi mật khẩu** (modal mật khẩu cũ/mới/xác nhận, gọi `POST /auth/change-password/` qua `changePassword`), **Đăng xuất** (`useAuth().logout`). `AuthContext` expose thêm `updateUser(next)` để thay user đã cache sau khi cập nhật hồ sơ.

## 9c. UI stack — Ant Design chủ đạo + Tailwind tinh chỉnh

Từ phase này, **Ant Design (antd v5) là design system chủ đạo** cho dashboard; **Tailwind** giữ lại để tinh chỉnh spacing/màu lặt vặt và layout nhanh; **lucide-react** là bộ icon.

Cấu hình (xem `src/main.jsx`):

- `<StyleProvider layer>` (`@ant-design/cssinjs`) đưa style antd vào một CSS `@layer` → utility của Tailwind (không layer) luôn thắng khi cần ghi đè antd.
- `<ConfigProvider theme={...} locale={viVN}>` — theme antd nằm ở `src/lib/antdTheme.js`, **ánh xạ đúng design token** trong `src/index.css` (brand amber, success/warning/danger, radius). Đổi token thì sửa cả hai nơi.
- `<App>` của antd bọc app để dùng `message`/`modal`/`notification` tĩnh có context (`react-hot-toast` vẫn dùng cho toast mutation như cũ).
- `import "antd/dist/reset.css"` làm reset nền; Tailwind **tắt `preflight`** (`tailwind.config.js`) để không xung đột.

Quy ước dùng: ưu tiên component antd cho UI mới (Button, Table, Form, Modal, Select, DatePicker…); icon lấy từ `lucide-react` và truyền vào prop `icon`. Bảng dữ liệu đã chuyển sang antd `<Table>` qua component dùng chung `DataTable` (Sites + Hostings). Component cũ tự viết còn lại (`StatusDot`, `SiteRegisterForm`…) vẫn chạy, sẽ chuyển dần sang antd khi đụng tới.

## 10. Local vs Production

- **Local:** `VITE_API_BASE_URL=http://localhost:8000/api`, `npm run dev` ở cổng 5173 (backend đã whitelist CORS cổng này).
- **Production:** đổi `VITE_API_BASE_URL` sang domain Hub thật (HTTPS), `npm run build` ra `dist/` để serve tĩnh. Kiến trúc không đổi.

## 11. Ngoài phạm vi (giai đoạn này)

- Gọi WooCommerce trực tiếp — không bao giờ (thuộc backend).
- Phân quyền nhiều vai trò chi tiết, đa ngôn ngữ, dark/light theme switch — chưa làm.
- Realtime bằng WebSocket — hiện dùng polling của React Query là đủ.
