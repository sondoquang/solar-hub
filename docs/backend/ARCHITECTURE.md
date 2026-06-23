# ARCHITECTURE.md — Backend

> Vị trí: `docs/backend/ARCHITECTURE.md`. Context gốc: `/CLAUDE.md`. Luật code: `docs/backend/PROJECT_RULE.md`.

Kiến trúc **backend** của Solar Hub — hệ thống trung tâm quản lý nhiều website WooCommerce.

---

## 1. Bối cảnh

Công ty vận hành nhiều website WooCommerce (host trên shared host TenTen). Việc thủ công gây mệt mỏi: gom đơn từng web để gửi marketing, và đăng/sửa sản phẩm lặp lại trên từng web (chậm, không đồng bộ).

Backend (Hub) giải quyết bằng cách trở thành **single source of truth (SSOT)**: thao tác một nơi, đồng bộ ra mọi site qua WooCommerce REST API. Hub **không** can thiệp code WordPress — chỉ là một consumer của API ở phía ngoài. Frontend là client riêng, chỉ nói chuyện với backend này (không chạm WooCommerce).

## 2. Sơ đồ tổng thể

```
                          ┌──────────────────────────────┐
   Web 1  ◄── REST/Webhook │       BACKEND (Hub)           │
   Web 2  ◄── REST/Webhook │  Django + DRF                 │──► Forward đơn
   Web 3  ◄── REST/Webhook │  PostgreSQL (SSOT)            │    (Telegram/Sheet)
   ...                      │  Celery worker + beat ◄─Redis │──► Django Admin
                          └──────────────────────────────┘──► REST /api/ ──► Frontend
```

Hai chiều dữ liệu:
- **Vào Hub:** đơn hàng (webhook real-time + poll dự phòng), trạng thái site (healthcheck).
- **Ra site:** sản phẩm (create/update/delete qua batch).
- **Ra frontend:** REST `/api/` cho dashboard.

## 3. Thành phần (Django apps)

| App | Trách nhiệm |
|---|---|
| `sites` | Đăng ký site, lưu `base_url` + `consumer_key` + `consumer_secret` (mã hóa). Test kết nối. Nhóm site theo `Hosting` (1 hosting = 1 server/tài khoản, nhiều domain). |
| `catalog` | `MasterProduct` (catalog gốc, 4 loại Woo + biến thể) + `ProductMapping`/`ProductVariationMapping` (master/biến thể ↔ id từng site) + `Category`/`CategoryMapping` (danh mục kéo từ site về). |
| `orders` | `Order` (đơn đã chuẩn hóa) + endpoint webhook + logic forward marketing. |
| `sync` | Celery tasks: push sản phẩm xuống site (batch), poll đơn định kỳ, kéo danh mục từ site. |
| `monitoring` | Healthcheck site **theo nhóm hosting** (fan-out 1 task/hosting, throttle song song trong mỗi hosting), cập nhật `Site.status`. Lưu **lịch sử kiểm tra** (`HealthCheck`) mỗi lần test kết nối + API đọc lịch sử cho dashboard. |
| `integrations` | `WooClient` — lớp trừu tượng hóa toàn bộ giao tiếp WooCommerce REST API. |
| `core` | App hạ tầng (không phải domain): expose `GET /api/health/` trả `{status, db, redis}` để kiểm tra stack đã kết nối. Endpoint **không auth** (health check không được chạm DB). |
| `accounts` | Auth JWT (SimpleJWT) + hồ sơ người dùng. Endpoints: `POST /api/auth/token/` (đăng nhập), `POST /api/auth/token/refresh/`, `GET/PATCH /api/auth/me/` (xem/cập nhật `full_name`+`email`, trả thêm `role` suy ra từ `is_superuser`/`is_staff`), `POST /api/auth/change-password/` (đổi mật khẩu, validate mật khẩu cũ + password validators). |

## 4. Mô hình dữ liệu

```
Hosting (1) ──< Site (N)                (1 hosting = 1 server/tài khoản, nhiều domain)
Site (1) ──< ProductMapping >── (1) MasterProduct
  │                                     (sku UNIQUE = khóa khớp xuyên site)
  ├──< ProductVariationMapping >── (1) MasterProduct   (biến thể: id riêng từng site)
  ├──< CategoryMapping >── (1) Category                (danh mục: tên UNIQUE, id riêng từng site)
  ├──< Order
  └──< SyncLog
```

> **`Hosting`** gom nhiều `Site` cùng một server/shared host. `Site.hosting` là FK nullable
> (`on_delete=SET_NULL`) — site chưa gán hosting được xử lý như nhóm riêng (`hosting_id=None`).
> Mục đích chính: **throttle healthcheck theo hosting** để không dội request lên host yếu.

Ràng buộc toàn vẹn cốt lõi:

- `MasterProduct.sku` **UNIQUE** — khóa khớp sản phẩm giữa các site.
- `ProductMapping` **UNIQUE (master, site)** — mỗi sản phẩm gốc map đúng một `woo_product_id` trên mỗi site.
- `ProductVariationMapping` **UNIQUE (master, site, variation_sku)** + **(site, woo_variation_id)** — biến thể idempotent per-site.
- `Category.name` **UNIQUE** (chuẩn hóa) + `CategoryMapping` **UNIQUE (category, site)** / **(site, woo_category_id)**.
- `Order` **UNIQUE (site, woo_order_id)** — chống trùng đơn khi webhook + poll cùng bắn.

> Bất biến quan trọng: **`woo_product_id`, category ID, attribute ID là RIÊNG theo từng site.** Hub không bao giờ giả định chúng giống nhau; mọi tham chiếu qua `ProductMapping`.

> **Đa nền tảng:** `Site.platform` ∈ `woocommerce` (mặc định) | `sapo`. Các cột `woo_*`
> trong mapping (`woo_product_id`, `woo_category_id`, `woo_variation_id`…) mang nghĩa
> **remote id trên site** bất kể nền tảng (với Sapo là product/collection/variant id);
> giữ nguyên tên cột để tương thích. Site Sapo tái dùng `consumer_key`/`consumer_secret_enc`
> cho API key/secret của Private App (cùng dạng cặp Basic auth, vẫn mã hóa Fernet).

## 5. Luồng dữ liệu

### 5.1. Gom đơn (quan trọng nhất)

**Chính — Webhook (real-time):** WooCommerce mỗi site cấu hình webhook topic *Order created*, delivery URL → `POST /api/webhooks/orders/?site=<id>`. Hub **verify HMAC** → chuẩn hóa payload → `update_or_create` vào `Order` → đẩy task forward marketing.

**Dự phòng — Poll (định kỳ):** Celery Beat chạy `poll_all_orders` mỗi ~8 phút: với mỗi site gọi `GET /orders?after=<mốc_lần_trước>&status=processing`, upsert đơn mới. Bù cho trường hợp shared host chặn outbound webhook hoặc webhook miss. **Áp dụng cho cả WooCommerce lẫn Sapo** — `SapoClient.list_orders` map đơn Sapo về cùng shape Woo nên `poll_site`/upsert/phân loại chạy không đổi; status Sapo (open/closed/cancelled) map 1:1 sang Woo status Hub lưu (processing/completed/cancelled), nên mỗi đơn Sapo rơi đúng một status, watermark per-(site, status) không double-count.

**Chọn site để poll — `apps.orders.services.sites_for_order_poll` (SSOT cho cả task định kỳ lẫn `poll_now`):** site Woo là độc lập → poll tất cả. Site **Sapo** đặc biệt: (1) **gate bằng `SAPO_ORDER_POLL_ENABLED`** (mặc định OFF — công tắc tạm dừng); (2) khi bật, **dedupe theo store**: nhiều Site Sapo có thể là các domain storefront của **cùng một store backend** — khác domain, **thậm chí khác API key**, vẫn redirect về cùng một host `*.mysapo.net`. Poll từng site sẽ kéo cùng bộ đơn nhiều lần, thổi phồng số đơn/doanh thu. Nên gom theo `Site.sapo_store_host` (host canonical, do health-check `test_connection` lưu lại từ `SapoClient.resolved_host` sau redirect) và chỉ poll site id nhỏ nhất mỗi store. Site chưa resolve host (blank) được coi là store riêng để không bị gộp nhầm. Phân trang Sapo dùng `page`+`limit` (Sapo có tôn trọng `page`; đơn trả về mới→cũ), chốt `_MAX_ORDER_PAGES` chống lặp vô hạn.

Cả hai đường cùng đổ vào một upsert idempotent → an toàn khi trùng. Đơn mới (`forwarded=False`) được gửi marketing (Telegram / Google Sheet / dashboard) rồi đánh dấu `forwarded=True`.

### 5.2. Đồng bộ sản phẩm

Thao tác CRUD diễn ra trên `MasterProduct` tại Hub (qua Admin/API). Khi "Sync all", `push_all_products` fan-out theo batch site → `push_products_batch_task` → `apps/catalog/services.push_products_to_site` chạy cho từng site. **Tập site đích đi qua `sites_for_product_push`** (mirror `sites_for_order_poll`, nhưng KHÔNG gate bởi `SAPO_ORDER_POLL_ENABLED`): site Woo lấy hết, các domain Sapo cùng `sapo_store_host` **gộp về 1** (8 storefront = 1 store dùng chung DB → push 1 lần) — `expected` của progress banner trong `sync_now` cũng đếm bằng hàm này:

1. Duyệt `MasterProduct`, tra `ProductMapping` của site đó.
2. **Nhận theo tên (adoption) cho master CHƯA có mapping** — `_adopt_by_name` chạy **sau `_ensure_site_categories`, trước `_plan_site_push`**: vì các site chưa thống nhất SKU/id, một sản phẩm import về Hub có thể đã tồn tại sẵn trên site dưới tên gõ tay. `_adopt_by_name` liệt kê sản phẩm site (`WooClient.list_products`), index theo tên chuẩn hóa (`normalize_match_name` — trim+collapse+lowercase+**bỏ dấu tiếng Việt**, tắt được bằng `PRODUCT_MATCH_FOLD_DIACRITICS`), khớp `match_name` (đóng băng lúc import; rỗng → fallback `name`): **khớp đúng 1** → tạo `ProductMapping` (master rơi vào nhánh `update`, không tạo trùng); **khớp >1** (ambiguous) → KHÔNG nhận & KHÔNG tạo (loại khỏi run, ghi `SyncLog.detail["ambiguous"]`, run đánh PARTIAL); **0** → để bước sau create. Khớp tên chỉ chạy **một lần/(master,site)** (run sau đã có mapping → bỏ qua, không gọi `list_products`), nên đổi tên trên Hub về sau không phá liên kết. Số nhận ghi `SyncLog.detail["adopted"]`/`["adopted_count"]`.
3. Chưa có mapping & chưa xóa → mảng `create`; đã có mapping & chưa xóa → `update` theo `woo_product_id`; đã có mapping & **soft-deleted** → `delete` (rồi gỡ mapping).
4. Gọi `WooClient.batch_products(create, update, delete)` — chia chunk **≤ `PRODUCT_BATCH_ITEM_LIMIT` (~100) item/request**, throttle `PRODUCT_PUSH_THROTTLE_SECONDS` giữa chunk.
5. Khớp response **theo SKU** → upsert `woo_product_id` + `last_synced_at` vào `ProductMapping`, ghi `SyncLog`. Lỗi mạng được **nuốt theo site** (trả `error`, ghi `SyncLog(error)`, không raise) để một site hỏng không kéo cả mẻ.
6. **Đếm thành công per-item = có `id` VÀ không có `error`** — batch của Woo trả HTTP 200 kể cả khi item bị từ chối, và reject của update/delete **vẫn echo `id`** (vd `woocommerce_rest_product_invalid_id`), nên "có id" không đủ. **Tự lành mapping mồ côi:** update bị reject `invalid_id` (sản phẩm đã bị xóa trên site ngoài Hub, vd wp-admin) → gỡ `ProductMapping` (+ var-mapping) và **re-push như create ngay trong cùng run**; số lượng ghi `SyncLog.detail["recreated_stale"]`.

**Loại sản phẩm (4 loại Woo):** `MasterProduct.type` ∈ `simple|grouped|external|variable`. `build_product_payload` nhánh theo type: `external` thêm `external_url`/`button_text`; `grouped` thêm `grouped_products` = ID các SKU con đã resolve (`_resolve_grouped_ids` tra `ProductMapping` của site; con chưa map ghi vào `SyncLog.detail["grouped_unresolved"]` và **tự lành** lần sync sau — `_plan_site_push` sắp xếp leaf-first/grouped-last); `variable` thêm `attributes` (định nghĩa, **không** kèm variations).

**Biến thể (variable):** push **2 bước** — đẩy sản phẩm cha qua `batch_products` để có `woo_product_id`, rồi `_push_variations` diff `MasterProduct.variations` vs `ProductVariationMapping` (theo `variation_sku`) → `WooClient.batch_variations(parent_id, create/update/delete)` (`/products/{id}/variations/batch`), chunk/throttle như cha; upsert var-mapping theo `woo_variation_id`. Xóa biến thể khỏi master → Woo delete + gỡ var-mapping; xóa cha → cascade gỡ var-mapping. Số liệu biến thể ghi `SyncLog.detail["variations"]`.

**Danh mục 2 chiều:** `MasterProduct.categories` vẫn là **list tên**. Hub có catalog danh mục riêng (`Category` + `CategoryMapping` per-site) được **kéo từ site về** (`pull_categories_for_site` ← `WooClient.list_categories`, fan-out `pull_all_categories`/`pull_categories_batch_task` mirror order-poll), upsert `Category` theo tên chuẩn hóa (`normalize_category_name` — trim+collapse, giữ hoa/thường) nên cùng tên ở nhiều site hội tụ về 1 `Category` nhiều mapping. **Cây danh mục (tree):** lúc pull, mỗi category resolve `parent` (woo parent id → tên → `Category`) rồi set self-FK `Category.parent` → Hub dựng lại đúng cây như WooCommerce (FE hiển thị `TreeSelect`); cây là **last-pull-wins** vì các site có thể nest khác nhau. Khi push, `build_product_payload` resolve tên → `{id}` của site qua `_category_id_map`. **Quan trọng: Woo REST API bỏ qua ref `{name}` (KHÔNG tự tạo category theo tên — chỉ CSV importer làm vậy)**, nên trước khi build payload, `_ensure_site_categories` **tạo trên site mọi category mà master sống tham chiếu nhưng chưa có mapping** (`WooClient.batch_categories` — `POST /products/categories/batch`, chunk + throttle như product): tạo **cha trước con theo wave** (kéo theo cả tổ tiên chưa map để giữ đúng cây; cha tạo fail → con tạo thành gốc, lần pull sau sửa lại); site đã có term trùng tên (chưa từng pull) → Woo reject `term_exists` kèm id sẵn có trong `error.data.resource_id` → **map id đó** thay vì tạo trùng; tên gõ tay chưa có trong Hub → `Category.objects.get_or_create` trước. Kết quả ghi `SyncLog.detail["categories"]` (`{created, linked, failed}`); category tạo fail → ref rơi về `{name}` (Woo bỏ qua) và run bị đánh **PARTIAL** để lộ thiếu sót thay vì success giả. Attribute/variation ID per-site để dành pha sau (attribute hiện gửi theo tên/option).

**Nhập sản phẩm từ website chính (`import_products_from_site`):** lấy data gốc một chiều site → Hub (mirror `pull_categories_for_site`, fan-out 1 site qua `import_products_task` + lock `lock:import_products:{id}`, endpoint `POST /products/import_from_site/`, operation `import_products`). Với mỗi sản phẩm **simple**: SKU trùng master sống → **link** (chỉ tạo mapping); chưa có → **create** master (đóng băng `match_name` = tên lúc nhập đã chuẩn hóa, `source_site`/`imported_at`); đã có mapping `(site, woo_id)` → skip (idempotent). **v1 chỉ nhập `simple`** — `variable/grouped/external` ghi vào `SyncLog.detail["skipped_types"]` (đẩy một master nửa-vời các loại này dễ làm hỏng sản phẩm trên site). SKU rỗng → placeholder `IMPORT-{site}-{woo_id}`.

**Báo cáo product-run (`apps/sync`):** mỗi run `push_products` (1 click "Đồng bộ ngay") gom theo `run_id`, mirror category-run — `product_runs_queryset`/`summarize_product_runs`/`product_run_stats`/`product_run_detail` + Excel (`build_product_run_workbook`), serve qua `GET /api/sync/product-runs/` (+ `stats/`, `{run_id}/`, `{run_id}/export/`). Mỗi `SyncLog` push mang snapshot `site_name`/`site_url`/`hosting` (`_site_snapshot`) để báo cáo sống sót khi site bị xóa + search theo tên. Per-site row phân loại created/updated/**adopted**/failed; `failed[].code` được `_classify_failure` gắn `kind` (`duplicate` vs `error`) cho FE tô màu. FE: tab "Lịch sử đồng bộ" trên trang Sản phẩm + modal tóm tắt cuối run (site nào thành công / thất bại + lý do).

### 5.3. Giám sát

`check_all_sites` chạy theo **nhịp beat = FAIL interval** (mặc định 5 phút, `SITE_HEALTHCHECK_FAIL_INTERVAL_SECONDS`) và **fan-out 1 sub-task `check_hosting_task` cho mỗi hosting** (cộng một nhóm `hosting_id=None` cho site chưa gán) → các hosting khác nhau chạy **song song** qua Celery, nhưng trong cùng một hosting `services.check_hosting` chỉ check **tối đa `Hosting.check_concurrency` domain đồng thời** (mặc định 5, dùng `ThreadPoolExecutor`; phần dư xếp hàng đợi). Nhờ vậy một shared host yếu không bị nhiều domain ping cùng lúc.

**Nhịp kiểm tra thích ứng (chỉ áp dụng cho lần chạy định kỳ `check_type="periodic"`):** `check_hosting` lọc qua `services._due_filter()` nên mỗi tick chỉ check **site đã đến hạn**:
- Site lần trước **thành công** (`status=up`) → kiểm tra lại mỗi **OK interval** (mặc định 10 phút, `SITE_HEALTHCHECK_OK_INTERVAL_SECONDS`) để tránh ping liên tục host khỏe mạnh.
- Site lần trước **thất bại / chưa từng kiểm tra** (`down`/`unknown`/`last_checked_at` null) → thử lại mỗi **FAIL interval** (5 phút) để phát hiện hồi phục sớm.
- Cutoff trừ một dung sai nhỏ (`_DUE_TOLERANCE_SECONDS`) để jitter của beat không đẩy lần check sang tick kế. FAIL interval phải ≤ OK interval (FAIL cũng chính là nhịp beat).
- **Ưu tiên trang chính:** trong mỗi hosting, danh sách site được sắp `-is_primary` trước khi đưa vào pool → các **trang chính** (`Site.is_primary`) luôn được kiểm tra trước các site còn lại của round đó (áp dụng cả periodic lẫn manual).

Action UI "Check ngay" (`check_type="manual"`) **bỏ qua bộ lọc đến hạn** — luôn kiểm tra mọi site. Mỗi site vẫn cập nhật `Site.status`/`last_checked_at` qua `services.test_connection`; timeout của call `system_status` cấu hình qua `SITE_HEALTHCHECK_TIMEOUT_SECONDS` (mặc định 15s, truyền vào `WooClient(status_timeout=...)`). Hosting yếu đặt `check_concurrency` thấp hơn. Production có thể thay/bổ sung bằng UptimeRobot cho nhẹ.

## 6. Lớp tích hợp (`WooClient`)

Mọi giao tiếp WooCommerce tập trung tại đây để cô lập đặc thù của shared host:

- Auth Basic (key/secret), **fallback query string trên HTTPS** nếu host strip header `Authorization`.
- Timeout theo loại call; `raise_for_status()`; `consumer_secret` chỉ giải mã trong bộ nhớ.
- **Throttle**: delay giữa request, giới hạn song song khi sync nhiều site.
- Dùng **batch** thay vì loop từng item.
- **Ghi**: `update_order(woo_order_id, status=)` (`PUT /orders/{id}`) — cùng pattern auth/timeout/fallback-401 như `list_orders`, trả payload đơn đã cập nhật để caller upsert lại Hub.
- **Batch sản phẩm**: `batch_products(create, update, delete)` (`POST /products/batch`) — đã hiện thực, cùng pattern auth/fallback-401, timeout 60s (ghi nặng hơn đọc). Trả `{create, update, delete}` mỗi item kèm `id`+`sku`. **Caller (`push_products_to_site`) chịu trách nhiệm chia chunk ≤100 item.**
- **Batch biến thể**: `batch_variations(parent_id, create, update, delete)` (`POST /products/{parent}/variations/batch`) — cùng pattern, timeout 60s; trả `{create, update, delete}` mỗi item kèm `id`+`sku` (map vào `ProductVariationMapping`).
- **Sản phẩm (đọc)**: `list_products(search=)` (`GET /products`, `status=any`, phân trang `X-WP-TotalPages`) — dùng cho name-match adoption (index theo tên) và import sản phẩm về Hub.
- **Danh mục (đọc)**: `list_categories()` (`GET /products/categories`, phân trang `X-WP-TotalPages` như `list_orders`) — kéo cây danh mục site về Hub.
- **Danh mục (ghi)**: `batch_categories(create)` (`POST /products/categories/batch`) — cùng pattern auth/fallback-401, timeout 60s; push dùng để tạo trước các category chưa map trên site (Woo bỏ qua ref `{name}` trong payload product). Item lỗi `term_exists` mang id sẵn có ở `error.data.resource_id`.

## 6b. Lớp tích hợp Sapo (`SapoClient`)

`apps/integrations/sapo.py` — adapter cho **Sapo Web** (API kiểu Shopify, per-store tại
`https://{store}/admin/*.json`, Basic auth bằng API key/secret của **Private App** — mỗi
store Sapo phải tự tạo Private App với quyền read-write Sản phẩm). `client_for_site(site)`
(apps/sites/services.py) dispatch theo `Site.platform`: `woocommerce` → `WooClient`,
`sapo` → `SapoClient`.

**Nguyên tắc thiết kế: adapter-inside-client.** `SapoClient` có **cùng bề mặt method với
`WooClient`** — nhận payload kiểu Woo (từ `build_product_payload`) và trả response kiểu Woo —
nên toàn bộ flow trong `apps/catalog/services.py` (push, mapping, stale recovery, SyncLog)
chạy nguyên vẹn, FakeClient trong test cũng dùng chung pattern.

Khác biệt nền tảng được hấp thụ bên trong client:

- **Không có batch endpoint** → một `batch_products` = nhiều request tuần tự, tự pacing
  `SAPO_THROTTLE_SECONDS` (mặc định 0.5s) giữa các request; HTTP 429 retry theo `Retry-After`
  (tối đa `SAPO_MAX_429_RETRIES`, fallback `SAPO_RETRY_AFTER_DEFAULT_SECONDS`). Lưu ý
  throughput: 1 chunk 100 sản phẩm ≈ vài phút (chạy trong Celery nên chấp nhận được).
- **SKU/giá/tồn kho nằm trên variant**: simple product = 1 default variant. Giá Woo
  (regular+sale) → Sapo `price` = giá bán thực, `compare_at_price` = giá gạch.
  `stock_status`: instock → không track tồn; outofstock → track, qty 0, policy deny;
  onbackorder → track, qty 0, policy continue. Update simple: GET trước để lấy variant id →
  PUT đè variant **tại chỗ** (không bao giờ thay mảng variants thiếu id).
- **Variable**: create gửi `options` (tối đa **3** thuộc tính biến thể) + **1 variant
  placeholder** (sku rỗng) để Sapo materialize options; `batch_variations` về sau PUT đè
  placeholder bằng biến thể thật đầu tiên (tránh 422 trùng tổ hợp), các biến thể sau POST
  per-variant. Attributes của variation map vị trí `option1..3` theo thứ tự options của cha.
- **Sản phẩm (đọc)**: `list_products()` (`GET /products.json`, phân trang 250) map về Woo-shape `{id, name, sku (variant đầu), type}` cho name-match adoption + import; vì 8 storefront Sapo chung 1 store/DB, push đã dedup theo `sapo_store_host` (`sites_for_product_push`) nên chỉ list/đẩy 1 lần.
- **Danh mục = custom collections (PHẲNG)**: `list_categories()` map collection →
  `{id, name: name, slug: alias, parent: 0}` (Sapo custom_collection mang tên ở field
  **`name`** và slug ở `alias` — **không** có field `title` kiểu Shopify; đọc nhầm `title`
  khiến name rỗng và `pull_categories_for_site` **skip sạch** mọi category Sapo; mọi
  collection thành category gốc trên Hub);
  `batch_categories` bỏ qua `parent`, tự giả lập `term_exists` (Sapo cho phép trùng title)
  để `_ensure_site_categories` link mapping thay vì tạo trùng. Gắn sản phẩm↔collection qua
  object **Collect** riêng: create POST collect cho mỗi ref `{id}`; update **diff** collects
  (POST thiếu / DELETE thừa) best-effort — lỗi collect không fail item, tự lành lần push sau.
- **Mã lỗi per-item**: `sapo_unsupported_type` (grouped/external — Sapo không có loại này),
  `sapo_max_options_exceeded` (>3 thuộc tính biến thể), `sapo_option_mismatch`,
  `sapo_http_<status>`. Tất cả chảy qua `_collect_batch_failures` → `SyncLog.detail.failed`
  → run PARTIAL, hiển thị trên report sẵn có. PUT/GET sản phẩm đã bị xóa trên site → 404
  được map thành **`woocommerce_rest_product_invalid_id`** để kích hoạt stale recovery sẵn có
  (gỡ mapping + re-create trong cùng run) mà không sửa service. DELETE 404 = thành công
  (idempotent).
- **Healthcheck**: `system_status()` → `GET /admin/custom_collections.json?limit=1` (test_connection
  dùng chung; endpoint nhẹ đã được luồng pull verify có scope cho private app).
- **Host canonical (smoke-tested store thật)**: REST API admin chỉ trả lời trên `*.mysapo.net`; base_url
  thường là tên miền cửa hàng (vd `https://shop.vn`). ⚠️ Tên miền cửa hàng **chỉ redirect đúng endpoint
  LIST** (`/admin/orders.json` → `*.mysapo.net`) sang host canonical; các path **theo từng resource**
  (`/orders/{id}.json`, `.../cancel.json`, `.../transactions.json`) lại bị **302 vào luồng logout**
  (`/admin/authorization/logout` → `accounts.sapo.vn/login`) → mất auth → 502. Vì vậy `client_for_site`
  **dựng base thẳng từ host canonical** (`https://{sapo_store_host}`) ngay khi đã health-check (host được
  lưu ở `Site.sapo_store_host`); site chưa health-check (host rỗng) mới fallback về base_url. `_request`/
  `_send` vẫn **tự đi theo redirect** + **áp lại Basic auth** (httpx xóa auth khi đổi host, biến POST 302
  thành GET), chỉ follow tới `*.mysapo.net`/cùng host — dùng cho lần health-check đầu để khám phá host.
- **Orders**: `list_orders` (`GET /admin/orders.json`, phân trang `page`+`limit` tới khi
  trang ngắn — Sapo không có header total-pages) map mỗi đơn Sapo → dict shape Woo qua
  `_sapo_order_to_woo`; status Woo yêu cầu → Sapo `status` (`processing→open`,
  `completed→closed`, `cancelled→cancelled`), status Woo không có tương ứng (pending/on-hold/
  refunded/failed) trả `[]`. `update_order(status=)` không có field status chung nên đẩy qua
  endpoint riêng: `completed→POST /orders/{id}/close.json`, `cancelled→.../cancel.json`.
  ⚠️ GET `/orders/{id}.json` + `/orders/{id}/transactions.json` đã verify 200 trên store thật (qua host
  canonical); POST close/cancel chưa chạy mutation thật (tránh đổi đơn khách) nhưng dùng **cùng routing**.
  ⚠️ **Lọc theo ngày (smoke-tested store thật):** Sapo dùng `created_on_min`/`created_on_max`/
  `modified_on_min` (KHÔNG phải `created_at_*` kiểu Shopify — tên đó bị bỏ qua) và **âm thầm bỏ
  qua datetime thiếu timezone** (`...T00:00:00` bị bỏ, `...T00:00:00Z` mới được áp). Bound naive
  của `_date_bounds` → `_with_tz` đóng dấu `Z` (coi như UTC) trước khi gửi; thiếu bước này poll
  kéo về **toàn bộ** đơn thay vì đúng khoảng đã chọn.
- **Thanh toán (Sapo)**: đơn Sapo mang **cả hai** trục trạng thái — lifecycle (open/closed/
  cancelled → processing/completed/cancelled) và **trạng thái thanh toán**. `_sapo_order_to_woo`
  mang `financial_status` về Hub (lưu ở `Order.payment_status`; Woo để trống). **`poll_site`
  KHÔNG còn ghim `financial_status`** — poll kéo *mọi* trạng thái thanh toán (đã + chưa) cho
  `status` đang poll, để màn Sapo liệt kê/lọc đủ; bộ lọc payment chạy ở query (`list_orders_qs`,
  nhóm `"unpaid"` = `pending`/`authorized`/`partially_paid`). `list_orders(financial_status=)`
  vẫn còn (Sapo-only, WooClient không có) cho caller nào cần lọc; ⚠️ Sapo **không có alias nhóm
  `unpaid`** (cả list ngăn cách dấu phẩy cũng bị bỏ qua — đều trả 0 đơn, smoke-tested), chỉ match
  một literal, nên khi được truyền `"unpaid"` thì `list_orders` **bung thành một query mỗi literal**
  trong `_UNPAID_FINANCIAL_STATUSES` rồi gộp/dedup theo id. `mark_order_paid(amount=)` ghi một
  transaction `sale` đầy đủ (`POST /orders/{id}/transactions.json`) rồi **GET lại đơn** (endpoint
  transactions trả về transaction, không phải order) → trả shape Woo để service upsert.
  ⚠️ **Backfill/staleness**: vì poll bám watermark `modified_on` theo `(site, status)`, đơn được
  thanh toán trực tiếp trên Sapo sẽ bump `modified_on` và được poll kéo về cập nhật ở lần sau.
  Riêng đơn *đã thanh toán từ trước* khi gỡ ghim `unpaid` có thể không tự xuất hiện cho tới khi bị
  sửa hoặc khi chạy đồng bộ theo **khoảng ngày** (bỏ qua watermark, kéo lại cả cửa sổ).
- **Giới hạn v1**: đổi tên thuộc tính biến thể không propagate khi update; ảnh riêng của
  variation bị bỏ qua (Sapo cần `image_id` đã upload, không nhận URL); Sapo không chặn trùng
  SKU nên mất mapping + re-create có thể tạo sản phẩm trùng (mapping table là lớp bảo vệ);
  một số tên field Sapo (`published_on`, `inventory_management: "sapo"`) cần smoke test trên
  store thật trước khi dùng production — đều cô lập trong các helper thuần ở `sapo.py`.

## 7. Xử lý nền

- **Celery worker** thực thi task; **Celery Beat** lên lịch (`poll_all_orders`, `check_all_sites`). Broker = **Redis**. Push sản phẩm (`push_all_products` → `push_products_batch_task`) chạy on-demand (UI/Admin), không lên lịch.
- **Hai queue, hai worker riêng** (routing qua `CELERY_TASK_ROUTES` trong settings, theo tên task — task con batch đi theo queue của task cha):
  - `interactive` — task do người dùng bấm: `push_all_products`/`push_products_batch_task`, `pull_all_categories`/`pull_categories_batch_task`. Worker riêng (`celery_worker_interactive` trong docker-compose) nên không bao giờ xếp sau job nền.
  - `periodic` (**default queue**) — task beat (`poll_all_orders`, `check_all_sites` + task con) và mọi task mới chưa route. Worker `celery_worker_periodic`.
  - Lưu ý: "Đồng bộ ngay" đơn hàng (on-demand `poll_all_orders`) hiện vẫn đi queue `periodic` — follow-up sau nếu cần ưu tiên.
- Task **idempotent**, có **retry + backoff** cho lỗi mạng, **timeout** mọi call ngoài.
- Sync N site = N task con (lỗi một site không kéo cả mẻ).

## 8. Quyết định thiết kế (tóm tắt)

| Quyết định | Lý do |
|---|---|
| Hub là SSOT, không sửa code WP | Tách biệt, không cần biết PHP; site chỉ là kho qua API. |
| SKU làm khóa khớp | ID sản phẩm khác nhau giữa các site; SKU ổn định, do người dùng kiểm soát. |
| Upsert idempotent theo unique key | Webhook + poll trùng nhau là chuyện bình thường; phải an toàn. |
| Webhook chính + poll dự phòng | Real-time khi tốt; vẫn không miss đơn khi host chặn/lỗi. |
| Batch products endpoint | Giảm số request, hợp với shared host yếu. |
| Mã hóa consumer_secret (Fernet) | Lộ DB không lộ key truy cập site. |
| Django (vs Spring Boot) | Admin dựng sẵn UI quản trị + Celery/Beat gọn cho job định kỳ. |
| Hai queue Celery (interactive/periodic) + worker riêng | Sync người dùng bấm không xếp sau job nền; default queue = periodic để task mới không chặn UI. |
| Sapo qua adapter cùng bề mặt WooClient | Service/task/test không đổi khi thêm nền tảng; đặc thù Sapo (không batch, variant-centric, collections phẳng) cô lập trong `sapo.py`. |

## 8b. Trạng thái hiện thực (Phase 1 — Site registry)

App `sites` đã hiện thực đầy đủ vertical slice (model → service → API/Admin → FE):

- **Model `Site`** (`apps/sites/models.py`): `name`, `base_url`, `consumer_key`, `consumer_secret_enc` (BinaryField — ciphertext Fernet), `status` (up/down/unknown, `db_index`), `is_primary` (boolean, `db_index` — **trang chính** của công ty: nổi lên đầu list mặc định và được healthcheck trước trong hosting, xem §5.3), `last_checked_at`, timestamps. Mã hóa/giải mã ở `apps/sites/crypto.py`; nghiệp vụ ở `apps/sites/services.py`.
- **API** (router DRF, prefix `/api/`):
  - `GET/POST /api/sites/`, `GET/PATCH/DELETE /api/sites/{id}/` — CRUD. `consumer_secret` **write-only**, không bao giờ trả ra response.
  - `POST /api/sites/{id}/test_connection/` — gọi `WooClient.system_status()`, cập nhật `Site.status`, trả `{ok, status, detail}`. **Chạy đồng bộ** (một call, timeout `SITE_HEALTHCHECK_TIMEOUT_SECONDS`, mặc định 15s) vì là thao tác tương tác cần kết quả ngay; healthcheck định kỳ vẫn để Celery (`check_all_sites`, Phase 4).
  - `POST /api/sites/test_connections/` — body `{ids: [...]}`, test nhiều site **tuần tự** (one-at-a-time = throttle tự nhiên), trả `{results: [{id, ok, status, detail}]}`.
  - `POST /api/sites/import_excel/` — upload `.xlsx` (multipart field `file`), parse bằng `openpyxl` ở service, bulk-create (mã hóa secret), bỏ qua dòng thiếu data / `base_url` trùng và báo lỗi từng dòng. Trả `{created, errors:[{row, error}]}`. Cột yêu cầu: `name, base_url, consumer_key, consumer_secret`. Có field multipart tùy chọn `hosting` (id) → gán mọi site import vào hosting đó (id không hợp lệ → 400).
  - `PATCH /api/sites/{id}/` — sửa site; `consumer_secret` optional (chỉ re-encrypt khi gửi).
  - `GET /api/sites/?hosting=<id>` / `?hosting=none` — lọc site theo hosting (hoặc site chưa gán hosting). Serializer trả thêm `hosting` (id) + `hosting_name`.
  - `GET /api/sites/?status=up|down|unknown` — lọc theo trạng thái; giá trị lạ bị bỏ qua (không lỗi).
  - `GET /api/sites/?is_primary=true|false` — lọc trang chính / trang thường. `is_primary` là field ghi được (POST/PATCH). Ordering mặc định của list: `-is_primary, -created_at` (trang chính lên đầu).
- **Hosting** (`apps/sites/models.Hosting`, router `/api/hostings/`):
  - Model: `name`, `provider`, `account_username`, `note`, `check_concurrency` (mặc định 5 = số domain check đồng thời), soft-delete (`is_deleted`/`deleted_at`).
  - `GET/POST /api/hostings/`, `GET/PATCH/DELETE /api/hostings/{id}/` — CRUD (xóa = soft-delete, **giữ FK của site**). List trả kèm `site_count` + `status_counts` ({up,down,unknown}) gom theo hosting.
  - `POST /api/hostings/{id}/check/` — healthcheck đồng bộ toàn bộ site của hosting (throttle theo `check_concurrency`), trả `{results:[{id, ok, status, detail}]}`.
  - `POST /api/hostings/import_excel/` — upload `.xlsx` (multipart field `file`), parse bằng `openpyxl` ở service, bulk-create hosting. Cột bắt buộc: `name`; tùy chọn `provider, account_username, note, check_concurrency` (mặc định 5 nếu trống/không hợp lệ, clamp 1–50). Dòng thiếu `name` hoặc trùng `(name, account_username)` (chưa xóa) bị bỏ qua + báo lỗi từng dòng. Trả `{created, errors:[{row, error}]}`.
  - Task định kỳ `apps/monitoring/tasks.check_all_sites` đã được hiện thực: fan-out `check_hosting_task` mỗi hosting (xem §5.3).
- **Admin**: `SiteAdmin` cho nhập key (password widget, mã hóa khi save) + action "Test connection".
- `WooClient.system_status()`, `list_orders()`, `update_order()`, `batch_products()` đã hiện thực đầy đủ.
- **Ghi chú website (`SiteNote` + `SiteNoteImage`)** — nhật ký ghi chú nhiều lần cho từng site (mới nhất lên đầu):
  - **Model `SiteNote`** (`apps/sites/models.py`): `site` (FK→Site, CASCADE, `db_index`), `content` (TextField — **HTML rich-text đã sanitize**), `created_by` (FK→User nullable, SET_NULL — `None` = "Hệ thống"), timestamps, **soft-delete** (`is_deleted`/`deleted_at`). `Meta.ordering = ["-created_at"]` + index `(site, created_at)`. `SiteNoteImage`: `note` (FK, CASCADE, `related_name="images"`), `image` (ImageField, `upload_to=site_notes/{note_id}/`), `original_name`, `uploaded_at`. Ảnh **chỉ là đính kèm**, không nhúng inline vào HTML.
  - **Service** (`apps/sites/services.py`): `sanitize_note_html` dùng **nh3** với allowlist tag rich-text (`p/strong/em/u/s/h1-3/ul/ol/li/a/blockquote/code/pre…`, `link_rel="noopener noreferrer nofollow"`); `create_site_note`/`update_site_note` (transaction, validate ảnh: type ∈ jpeg/png/gif/webp, ≤ 5MB) / `delete_site_note` (soft-delete). HTML được sanitize ở service trước khi lưu — **không tin** HTML từ client.
  - **API** `SiteNoteViewSet` (router `/api/site-notes/`, **multipart**): `GET /api/site-notes/?site=<id>` (list phân trang, mới nhất trước, scope theo site, ẩn soft-deleted), `POST` (fields `site`, `content`, nhiều file `images`), `PATCH /{id}/` (`content` + `images` mới + `remove_image_ids[]` để gỡ ảnh cũ), `DELETE /{id}/` (soft-delete). Serializer trả `images` (nested, `url` tuyệt đối qua `request.build_absolute_uri`) + `created_by_name`.
  - **Media**: `MEDIA_URL=/media/`, `MEDIA_ROOT=BASE_DIR/media` (settings); dev serve qua `static()` trong `config/urls.py` khi `DEBUG`. Cần **Pillow** (ImageField) + **nh3** (sanitize) — thêm vào `requirements.txt`. `backend/media/` đã gitignore.
  - **Admin**: `SiteNoteAdmin` + `SiteNoteImageInline` (đọc/debug).

## 8c. Trạng thái hiện thực (monitoring — Lịch sử kiểm tra sức khỏe)

App `monitoring` đã hiện thực lịch sử kiểm tra sức khỏe website (model → service → API/Admin → FE):

- **Model `HealthCheck`** (`apps/monitoring/models.py`): `site` (FK→Site, CASCADE), `status` (healthy/warning/critical, `db_index`), `check_type` (periodic/manual), `response_time_ms`, `ok` (reachability thô), `detail`, `performed_by` (FK→User nullable, SET_NULL — `None` = "Hệ thống"), `checked_at` (`db_index`). Là **log append-only** (giống `sync_logs`) → **không** soft-delete, **không** có endpoint create/update/delete. Index kép `(status, checked_at)` + `(site, checked_at)`.
- **Suy ra trạng thái** (`services.derive_status`): không reachable hoặc `response_time ≥ 5000ms` → `critical`; `1000–4999ms` → `warning`; `< 1000ms` → `healthy`.
- **Ghi lịch sử**: `apps/sites/services.test_connection` được mở rộng — đo round-trip `system_status()`, cập nhật `Site.status` (up/down) **và** gọi `monitoring.services.record_check(...)` (lazy import tránh vòng lặp). `check_type`/`performed_by` chảy xuyên qua `bulk_test_connections` và `check_hosting` (mặc định `periodic`/None cho Celery; `manual`+user cho action UI). View truyền user qua helper `_actor(request)`.
- **API** (router DRF, prefix `/api/`, read-only):
  - `GET /api/healthchecks/` — list phân trang server-side. Filter: `status`, `check_type`, `site`, `hosting` (`none` = chưa gán), `date_from`/`date_to` (theo `checked_at__date`). Search (`?search=`) trên tên/URL website + tên hosting. Sort (`?ordering=`) `checked_at`/`response_time_ms`/`status`. Serializer flatten `site_name`/`base_url`/`hosting_name`/`performed_by_name`/`status_display`/`check_type_display`.
  - `GET /api/healthchecks/{id}/` — chi tiết một lần kiểm tra.
  - `GET /api/healthchecks/stats/` — đếm theo trạng thái cho range đang lọc (`total/healthy/warning/critical`) + `trend_pct` (so với kỳ liền trước cùng độ dài, chỉ khi có đủ `date_from`+`date_to`). **Lưu ý:** dùng `.order_by().values().annotate()` để clear Meta ordering, tránh `checked_at` lọt vào GROUP BY.
  - `GET /api/healthchecks/export/` — `StreamingHttpResponse` CSV (UTF-8 BOM cho Excel) theo đúng filter hiện tại.
- **Admin**: `HealthCheckAdmin` read-only (list_filter status/check_type/checked_at, date_hierarchy, autocomplete site).
- **Seed dev**: `python manage.py seed_healthchecks --days 30 --per-day 8 [--reset]` sinh dữ liệu mẫu (≈84% healthy) cho các site hiện có.

## 8d. Trạng thái hiện thực (orders — Gom đơn theo polling)

App `orders` đã hiện thực vertical slice gom đơn bằng **polling** (webhook real-time + forward marketing để giai đoạn sau; model đã để sẵn cờ `forwarded`/`forwarded_at`):

- **Model `Order`** (`apps/orders/models.py`): `site` (FK→Site, CASCADE, `db_index`), `woo_order_id` (BigInteger — riêng từng site), `number`, `status` (`db_index`), `currency`, `total` (Decimal 12,2), thông tin KH `customer_name/phone/email/shipping_address/customer_note` (**PII — lưu DB nhưng KHÔNG log**), `line_items` (JSON: `{sku,name,quantity,total}`), `date_created_woo` (`db_index` — mốc tạo bên Woo), `date_modified_woo` (`db_index`, nullable — mốc sửa bên Woo, **dùng làm watermark poll**), `forwarded`/`forwarded_at`, **phân loại rủi ro** `classification` (genuine/suspicious/spam, `db_index`, default genuine) + `risk_score` (0–100) + `risk_reasons` (JSON list mã rule) + `classified_at`, `raw` (JSON payload gốc), timestamps. Ràng buộc `UniqueConstraint(site, woo_order_id)` (`order_unique_per_site`) → **upsert idempotent** an toàn khi poll/webhook trùng. Index kép `(site, date_created_woo)`, `(status, date_created_woo)`, `(forwarded, date_created_woo)`, `(site, status, date_modified_woo)` (watermark theo từng status), `(classification, date_created_woo)` (filter list), `(customer_phone, date_created_woo)` + `(customer_email, date_created_woo)` (velocity query).
- **`WooClient.list_orders(status, per_page, after, before, modified_after)`** (`apps/integrations/woocommerce.py`): `GET /orders` của **một status**, phân trang theo header `X-WP-TotalPages`, auth Basic + **fallback query-string khi gặp 401** (shared host strip header `Authorization`), timeout 30s, `raise_for_status()`. Poll định kỳ truyền `modified_after` + `dates_are_gmt=true` (mốc GMT, khớp `date_modified_gmt`); sync theo khoảng ngày dùng `after`/`before` (chặn theo `date_created`). Ghi: **`update_order(woo_order_id, status=)`** (`PUT /orders/{id}`) — cùng pattern auth/timeout/fallback, trả payload đơn đã cập nhật.
- **Service** (`apps/orders/services.py`): `POLL_STATUS="processing"` (default định kỳ) + `ALLOWED_POLL_STATUSES` (7 status chuẩn để API validate); `normalize_order` (map payload Woo → fields, ưu tiên `*_gmt`, lấy cả `date_modified_woo`), `upsert_order` (`update_or_create` theo `(site, woo_order_id)`), `poll_site(site, status, *, date_from=, date_to=)` — **hai chế độ loại trừ nhau**: (a) mặc định/định kỳ dùng watermark = `MAX(date_modified_woo)` của **`(site, status)`** → `list_orders(status=, modified_after=)` (key theo *modified* nên **bắt được cả đơn cũ đổi trạng thái**); (b) khi có `date_from`/`date_to` thì **bỏ watermark**, chặn theo `after`/`before` trên `date_created` (`_date_bounds` map `YYYY-MM-DD` → mốc GMT, bao trùm cả hai ngày — backfill theo yêu cầu). Bắt `httpx.HTTPError` trả `error`, **không** raise, log `site_id`+`status`+class lỗi, không log payload; `mark_order_completed(order)` (đẩy đơn `processing` → `completed` bằng `update_order` rồi upsert lại từ payload Woo, nên poll sau **không revert**; chỉ cho từ `processing`, nếu không raise `InvalidStatusTransition`); `mark_order_cancelled(order)` (đẩy đơn → `cancelled` cùng cách; chỉ cho từ `CANCELLABLE_STATUSES`=`pending`/`processing`/`on-hold`, các status terminal raise `InvalidStatusTransition`). **Forward marketing (một chiều)**: `_auto_forward_if_completed(order)` được `upsert_order` gọi sau mỗi upsert → đơn `status=="completed"` tự động `forwarded=True` (phủ cả poll, webhook, `complete`); `forward_order(order)` set `forwarded=True`/`forwarded_at` thủ công (idempotent, **không** gọi Woo, **không** có đường un-forward); `forward_orders(qs, ids)` bulk UPDATE các đơn `forwarded=False` trong selection (cap `MAX_FORWARD_ORDERS`=500). Vì `normalize_order` không đụng `forwarded`/`forwarded_at` nên re-sync chỉ có thể **thêm** cờ, không bao giờ xóa. `list_orders_qs` (lọc thêm `classification`) / `order_stats` (thêm `by_classification`) cho API.
- **Phân loại đơn (chống bot/spam — quy tắc heuristic cố định, v1):** `classify_order(order)` chấm điểm rủi ro 0–100 → nhãn (`SPAM_THRESHOLD=70`, `SUSPICIOUS_THRESHOLD=35`). Hai lớp rule: `classify_fields(data)` **thuần (không DB)** — SĐT Việt Nam (thiếu/sai định dạng `^0[35789]\d{8}$`/giả như `0000000000`, chuẩn hóa `+84`→`0`), email (sai định dạng / domain disposable trong `DISPOSABLE_EMAIL_DOMAINS`), tên (thiếu/vô nghĩa), địa chỉ (thiếu/quá ngắn); và `classify_velocity(order)` **query DB** — đếm đơn cùng `customer_phone`/`customer_email`/`raw.customer_ip_address` trong `VELOCITY_WINDOW` (24h), ≥`VELOCITY_MIN_ORDERS` (3) → cờ `velocity_*`. Trọng số ở `RULE_WEIGHTS`, nhãn tiếng Việt ở `REASON_LABELS`. `upsert_order` gọi `classify_and_save(obj)` **trước** `_auto_forward_if_completed` → đơn `completed` **chỉ tự forward khi `classification==genuine`** (đơn nghi ngờ/spam giữ lại cho admin duyệt; `forward_order`/`forward_orders` thủ công vẫn override được). Management command `python manage.py reclassify_orders [--site --status]` backfill + chạy lại khi tinh chỉnh trọng số.
- **Celery** (`apps/sync/tasks.py`): `poll_all_orders(status="processing", site_ids=None, date_from=None, date_to=None, platform=None)` (Beat mỗi ~3 phút chạy default `processing` toàn bộ site cả 2 platform, không date; UI có thể truyền status/sites/khoảng ngày khác; **`platform`** ∈ `woocommerce`|`sapo` giới hạn run về đúng một nền tảng — màn "Đơn hàng" có 2 sub-tab WooCommerce / Sapo, mỗi tab chỉ sync platform của nó qua `sites_for_order_poll(site_ids, platform=)`, gate Sapo `SAPO_ORDER_POLL_ENABLED` vẫn áp dụng) — chia site thành **mẻ `ORDER_POLL_BATCH_SIZE` (mặc định 8, env)** rồi dispatch `poll_sites_batch_task.delay(chunk, status, date_from, date_to)` mỗi mẻ; `poll_sites_batch_task` poll cả mẻ qua `ThreadPoolExecutor(max_workers=ORDER_POLL_BATCH_SIZE)` (cùng pattern `check_hosting`), lỗi một site không kéo cả mẻ. **Một lần sync = đúng một status** (hiệu năng). Poll định kỳ chỉ `processing`; các status khác / khoảng ngày sync theo yêu cầu từ UI.
- **API** (router DRF, prefix `/api/`, đơn được kéo về — không CRUD tay; write: `complete` đẩy lên Woo, `forward`/`forward_bulk` chỉ đổi cờ marketing nội bộ Hub):
  - `GET /api/orders/` — list phân trang. Filter: `site`, `hosting` (`none` = chưa gán), `status`, `forwarded` (`true`/`false`), `date_from`/`date_to` (theo `date_created_woo__date`). Search (`?search=`) trên số đơn / tên KH / SĐT / tên site. Filter thêm `classification` (genuine/suspicious/spam). Sort `date_created_woo`/`total`/`status`/`risk_score`. Serializer flatten `site_name`/`hosting_name`, expose `classification`/`classification_display`/`risk_score`/`risk_reasons`/`risk_reasons_display` (mã rule → nhãn tiếng Việt); **không** expose `raw` ở list.
  - `GET /api/orders/{id}/` — chi tiết (modal hiển thị `line_items` + thông tin KH).
  - `GET /api/orders/stats/` — `{total, revenue, not_forwarded, by_status, by_classification}` cho range đang lọc (**lưu ý** alias `Count` không được trùng tên field `total`, nếu không `Sum("total")` sẽ vỡ).
  - `POST /api/orders/poll_now/` — body tùy chọn `{status, sites, date_from, date_to, platform}` (`status` mặc định `processing`, phải ∈ `ALLOWED_POLL_STATUSES`; `sites` = list id, bỏ trống = toàn bộ; `date_from`/`date_to` = `YYYY-MM-DD`, khi có thì sync re-pull đơn **tạo** trong khoảng đó thay vì dùng watermark; **`platform`** ∈ `Site.Platform.values` (`woocommerce`|`sapo`) giới hạn run về một nền tảng — sub-tab WooCommerce gửi `woocommerce`, sub-tab Sapo gửi `sapo`). Validate sai (status/sites/date/platform) → 400. Sinh `run_id` (uuid4) + đếm `expected` (`sites_for_order_poll(sites, platform=)` — số site live trong scope sau khi áp `platform` + gate/dedup Sapo, cùng query `poll_all_orders` chạy), kích hoạt `poll_all_orders.delay(status=, site_ids=, date_from=, date_to=, run_id=, triggered_by_id=, platform=)`, trả `{task_id, status, run_id, expected}` (nút "Đồng bộ ngay" của UI gửi status/scope/khoảng ngày đang lọc; scope "hosting" được FE expand thành list site id). `run_id`/`expected` nuôi **banner tiến trình** "Đang đồng bộ đơn hàng… X/Y site" (FE poll `/api/sync/run-progress/`). Chỉ run thủ công (có `run_id`) mới ghi `SyncLog(operation="poll_orders")` per-site — poll định kỳ (Beat, `run_id=None`) **không ghi** để tránh phình bảng audit mỗi ~3 phút/site.
  - `POST /api/orders/{id}/complete/` — đánh dấu một đơn `completed`. **Chạy đồng bộ** (một `PUT` lên Woo, như `test_connection`) để UI nhận lại đơn đã cập nhật ngay; gọi `mark_order_completed`. Chỉ từ `processing` (nếu không → 409); lỗi WooCommerce → 502 (log `order_id`+`site_id`, không PII). Trả về đơn đã serialize.
  - `POST /api/orders/{id}/cancel/` — **hủy đơn** (đẩy `cancelled` lên Woo, đồng bộ như `complete`); gọi `mark_order_cancelled`. Chỉ từ `pending`/`processing`/`on-hold` (nếu không → 409); lỗi Woo → 502. Trả về đơn đã serialize. (FE bắt buộc confirm — `Popconfirm` — trước khi gọi.)
  - `POST /api/orders/{id}/forward/` — **chuyển đơn sang bộ phận marketing** (cờ nội bộ Hub, **một chiều**: idempotent, không có un-forward, **không** gọi Woo). Trả về đơn đã serialize.
  - `POST /api/orders/forward_bulk/` — body `{ids: [...]}` chuyển nhiều đơn đã chọn cùng lúc (giao với queryset đã lọc; chỉ đơn `forwarded=False` mới flip; cap `MAX_FORWARD_ORDERS`). `ids` không phải list số → 400. Trả `{forwarded: <count>}`.
  - `GET /api/orders/export_pdf/` — xuất **phiếu đơn hàng PDF** cho bộ phận kinh doanh (gom một file, **mỗi đơn một trang**). Query `?ids=1,2,3` giới hạn đúng các đơn đã chọn (giao với queryset đã lọc nên filter/quyền vẫn áp dụng); **bỏ `ids`** thì xuất toàn bộ selection đang lọc. `services.select_orders_for_pdf` sắp theo `date_created_woo` (thứ tự đọc) và **cap `MAX_PDF_ORDERS` (200)**. Trả `application/pdf` (`Content-Disposition: attachment`); một đơn → tên file `don-hang-<số_đơn>.pdf`, nhiều đơn → `don-hang.pdf`.
- **PDF** (`apps/orders/pdf.py`, lib **reportlab**): `build_orders_pdf(orders) -> bytes` dựng tài liệu Platypus (A4) — header Solar Hub, khối thông tin đơn + khách, bảng line items (STT/SKU/tên/SL/đơn giá/thành tiền) + tổng tiền, layout khớp modal chi tiết. Font **DejaVu Sans nhúng** (`apps/orders/fonts/DejaVuSans.ttf`, đăng ký một lần) vì font Type-1 mặc định của reportlab **không** có glyph tiếng Việt; tiền định dạng kiểu vi-VN (`1.850.000 ₫`). PII xuất hiện trong tài liệu theo chủ đích nhưng **không** log.
- **Admin**: `OrderAdmin` read-only (list_display kèm `classification`/`risk_score`, list_filter status/classification/forwarded/site, date_hierarchy `date_created_woo`, không cho add/change).

## 8e. Trạng thái hiện thực (catalog + sync — Đồng bộ sản phẩm)

App `catalog` + `sync` đã hiện thực **backend** vertical slice đồng bộ sản phẩm Hub → site, kèm **frontend** (form 4 loại sản phẩm + panel trạng thái đồng bộ — xem `docs/frontend/ARCHITECTURE.md`). Category xử lý **theo tên** + đồng bộ 2 chiều (xem §5.2):

- **Model `MasterProduct`** (`apps/catalog/models.py`): `sku` (CharField **UNIQUE**, `db_index` — khóa khớp xuyên site, chuẩn hóa trim/collapse/upper trước khi lưu), `name`, `type` (choices `simple|grouped|external|variable`, default `simple`), `description`/`short_description`, `regular_price`/`sale_price` (Decimal 12,2; `sale_price` nullable), `status`, `stock_status`, `weight` (Decimal 8,3 nullable), `images` (JSON list URL), `categories` (JSON list **tên** category); **type-specific (additive, default rỗng):** `external_url`/`button_text` (external), `grouped_skus` (JSON list SKU con), `attributes` (JSON `[{name,options,variation,visible}]`), `variations` (JSON `[{sku,regular_price,sale_price,stock_status,weight,attributes,image}]`); **soft-delete** (`is_deleted`/`deleted_at`) + timestamps. `Meta.ordering = ["-updated_at"]`.
- **Model `ProductMapping`** (`apps/catalog/models.py`): `master` (FK→MasterProduct, CASCADE, `related_name="mappings"`), `site` (FK→Site, CASCADE, `db_index`, `related_name="product_mappings"`), `woo_product_id` (BigInteger — **riêng từng site**), `last_synced_at`, timestamps. Ràng buộc `UniqueConstraint(master, site)` (`mapping_unique_master_site` — upsert idempotent) + `UniqueConstraint(site, woo_product_id)` (`mapping_unique_site_woo`).
- **Model `Category` + `CategoryMapping`** (`apps/catalog/models.py`): `Category.name` (CharField **UNIQUE** chuẩn hóa, giữ hoa/thường) + `slug` + **`parent`** (self-FK, `on_delete=SET_NULL`, `related_name="children"`, null=gốc) + soft-delete; `CategoryMapping` (mirror ProductMapping) `category`/`site`/`woo_category_id`/**`woo_name`** (tên RAW trên site, trước normalize — cho màn "Danh mục" đối chiếu tên site vs tên Hub; refresh mỗi lần pull vì mapping của site được rebuild wholesale; dòng cũ trước migration rỗng tới lần pull kế)/`last_synced_at`, UNIQUE `(category, site)` + `(site, woo_category_id)`. Catalog danh mục dùng cho picker (**TreeSelect** dựng cây từ `parent`) + resolve tên→id per-site khi push. **Cây danh mục:** `parent` dựng lại cây như WooCommerce (1 cây toàn cục cho Hub). Vì `Category` dedup theo *tên* mà cây cha–con có thể khác nhau giữa các site → quan hệ cha là **last-pull-wins** (mỗi lần pull một site ghi đè `parent` theo cây site đó, kể cả về null nếu site coi nó là gốc).
- **Model `ProductVariationMapping`** (`apps/catalog/models.py`): `master`/`site`/`variation_sku`/`woo_variation_id`/`woo_parent_id`/`last_synced_at`, UNIQUE `(master, site, variation_sku)` + `(site, woo_variation_id)` — id biến thể **riêng từng site** để upsert idempotent.
- **Model `SyncLog`** (`apps/sync/models.py`): `site` (FK→Site, **SET_NULL** nullable — log sống sót khi xóa site), `operation` (`db_index`, vd `push_products`), `status` (success/partial/error), `created_count`/`updated_count`/`deleted_count`, **`run_id`** (UUID nullable `db_index` — gom các dòng per-site của **một lần bấm** sync thành một *run*: "Đồng bộ danh mục" (`pull_categories`), "Đồng bộ ngay" sản phẩm (`push_products`) và đơn hàng (`poll_orders`); null với dòng cũ/operation không fan-out/poll định kỳ), **`triggered_by`** (FK→User, SET_NULL nullable — admin đã bấm sync, cho cột "Người chạy"; null với run định kỳ/beat/shell), **`started_at`** (nullable — lúc bắt đầu pull site đó; `created_at` là lúc kết thúc → duration per-site = `created_at - started_at`), `error` (chỉ tên class lỗi — **không** payload/PII), `detail` (JSON tóm tắt), **`is_deleted`** (soft-delete cho action "Xóa toàn bộ danh mục đồng bộ" — clear đánh dấu mọi dòng `pull_categories` đã xóa để báo cáo category-run bắt đầu lại từ đầu, dòng vẫn còn để khôi phục; mọi query của báo cáo lọc `is_deleted=False`, index `operation` đã cover hot path), `created_at`. Append-only (trừ cờ `is_deleted`), admin read-only.
- **`WooClient`** — `batch_products`, `batch_variations`, `list_categories`, `batch_categories` (xem §6).
- **Service** (`apps/catalog/services.py`): `normalize_sku`, `normalize_category_name`, `build_product_payload(master, *, category_id_by_name, grouped_ids)` (nhánh theo type, resolve category tên→id, tách riêng để unit-test không cần DB), `build_variation_payload`, `push_products_to_site(site, *, masters=None, run_id=None, triggered_by_id=None)` (lõi "Sync all" — xem §5.2: **`_ensure_site_categories` tạo + map category còn thiếu trên site trước** (Woo bỏ qua ref `{name}`; kết quả ở `detail["categories"]`, fail → PARTIAL), plan create/update/delete theo mapping + leaf-first cho grouped, chia chunk + throttle, khớp response theo SKU, đẩy biến thể 2 bước, gỡ mapping + var-mapping khi delete, **nuốt lỗi theo site** + ghi `SyncLog` kèm `run_id`/`triggered_by`/`started_at`; khi có `run_id` thì **cả nhánh no-op** (site đã đồng bộ, không có gì để đẩy) cũng ghi 1 dòng SUCCESS để banner tiến trình đếm đủ `expected`), `pull_categories_for_site(site, run_id=None, triggered_by_id=None)` (Woo→Hub, mirror `poll_site`; ghi `SyncLog` kèm `run_id`/`triggered_by`/`started_at` + **snapshot báo cáo** vào `detail`: `site_name`/`site_url`/`hosting` (sống sót khi xóa site) và `categories=[{woo_id, woo_name (tên gốc trước normalize), hub_id, hub_name}]` — cả dòng lỗi/rỗng cũng mang `run_id` để site hỏng vẫn hiện trong run), **`category_overview()`** (đếm cho thẻ thống kê dashboard: `hub_used`/`hub_total`/`linked`/`unlinked`/`linked_pct`/`site_count`/`root_count`/`child_count`/`deleted_count` — Exists subquery như `product_stats`), **`category_matrix_qs(params)`** (ma trận cross-site: 1 row/Hub category live, `prefetch_related('mappings__site')` + annotate `linked_site_count`, serializer pivot thành `cells` keyed theo site_id; search theo name/tên cha; ordering whitelist `name`/`linked_site_count`), **`category_site_links(category)`** (mọi site live + cờ `linked`/`woo_category_id`/`woo_name`/`last_synced_at` — panel chi tiết tab cây, mirror `product_sync_status`), `product_sync_status(master)` (mọi site active + cờ synced/last_synced_at + `site_status` up/down/unknown + `site_url`/`is_primary` để panel lọc theo trạng thái web / search domain / trang chính), `list_category_mappings_qs(site_id, params)` (queryset cho màn "Danh mục": mapping của một site + `select_related` category/parent, search theo `woo_name`/tên Hub/`woo_category_id` số, ordering whitelist + tie-break `id`), `list_products_qs`/`product_stats`.
- **Celery** (`apps/sync/tasks.py`): `push_all_products(site_ids, master_ids, run_id=None, triggered_by_id=None)`/`push_products_batch_task(..., run_id=, triggered_by_id=)` (mẻ `PRODUCT_PUSH_BATCH_SIZE`, ThreadPoolExecutor + `connection.close()`; `run_id`/`triggered_by_id` luồn từ view "Đồng bộ ngay" xuống từng `SyncLog` cho banner tiến trình, kwarg default nên admin-action/message cũ vẫn chạy), và `pull_all_categories(site_ids, run_id, triggered_by_id=None)`/`pull_categories_batch_task(site_ids, run_id, triggered_by_id=None)` (mirror order-poll, mẻ `ORDER_POLL_BATCH_SIZE`; `run_id` + `triggered_by_id` luồn từ view xuống từng `SyncLog`, `run_id` tự sinh khi gọi không có — kwarg default nên message cũ trong queue vẫn chạy). On-demand (không Beat). Settings: `PRODUCT_PUSH_BATCH_SIZE`, `PRODUCT_BATCH_ITEM_LIMIT` (≤100, dùng chung cho chunk biến thể), `PRODUCT_PUSH_THROTTLE_SECONDS`.
- **API** (`MasterProductViewSet`, router `/api/products/`): CRUD `GET/POST /api/products/`, `GET/PATCH/DELETE /api/products/{id}/` (DELETE = soft-delete; serializer normalize/check `sku`, validate theo type — external cần `external_url`, variable cần ≥1 attribute `variation=true`, normalize `grouped_skus`/`variations[].sku`; trả `mappings`+`mapping_count`+các field type). `GET /api/products/stats/`. `POST /api/products/sync_now/` (body `{sites, products}`) → sinh `run_id` + đếm `expected` (số site live trong scope) rồi `push_all_products.delay(site_ids=, master_ids=, run_id=, triggered_by_id=request.user.id)`, trả `{task_id, run_id, expected}` cho banner tiến trình "Đang đồng bộ sản phẩm… X/Y site" (FE poll `/api/sync/run-progress/`). `GET /api/products/{id}/sync_status/` → danh sách site đã/chưa đồng bộ (panel per-domain). `CategoryViewSet` (`/api/products/categories/`, đăng ký **trước** `products`): `GET` list (search theo name, cho picker; pagination riêng `CategoryPickerPagination` `page_size`/`max_page_size`=1000 — picker tải **toàn bộ** catalog, cap mặc định 100 từng cắt mất danh mục khiến không tìm thấy trong form sản phẩm) + `GET /mappings/?site=<id>` (**bắt buộc** `site`, thiếu/sai → 400; tùy chọn `search`/`ordering`/`page`/`page_size`, phân trang thủ công `StandardPagination` như category-runs) → mỗi row `{id, woo_category_id, woo_name, category_id, category_name, category_parent_id, category_parent_name, last_synced_at}` cho trang "Danh mục" của FE + `POST /pull_now/` (body `{sites}` tùy chọn) → sinh `run_id` (uuid4) rồi `pull_all_categories.delay(site_ids, run_id, triggered_by_id=request.user.id)`, trả `{task_id, run_id}` (run_id là "dự kiến" — nếu đụng lock đang chạy thì run không bao giờ xuất hiện; bảng runs là nguồn sự thật) + **`POST /clear_all/`** (reset catalog danh mục để pull lại từ đầu — **đồng bộ**, thuần DB nên không qua Celery): gọi `services.clear_category_sync_data()` → **soft-delete** mọi Hub `Category` + xóa `CategoryMapping` của chúng + soft-delete lịch sử `SyncLog(pull_categories)`, **NGOẠI TRỪ** danh mục đang được sản phẩm live tham chiếu theo tên (kèm **tổ tiên** để cây giữ được không gãy — danh mục được giữ vẫn nguyên mapping); trả `{categories_cleared, categories_kept, mappings_cleared, history_cleared}` cho toast. Workflow: clear → pull các site `is_primary` **trước** để cây của site chính thành gốc canonical. **Lưu ý revive:** `pull_categories_for_site` upsert Category với `update_fields=["slug", "is_deleted"]` nên pull lại một tên đã soft-delete sẽ **revive** nó (đặt lại `is_deleted=False`) thay vì để ẩn vĩnh viễn. **Dashboard 3-tab** (FE `pages/Categories.jsx`) thêm 3 action tổng hợp render động: `GET /overview/` (thẻ thống kê tab Tổng quan + Cây danh mục Hub), `GET /matrix/?search=&ordering=&page=&page_size=` (ma trận Hub × site — response bọc thêm `sites` làm header cột động, mỗi row có `cells` keyed theo site_id), `GET /{id}/sites/` (link site của một category cho panel chi tiết tab cây).
- **API báo cáo đồng bộ danh mục** (`apps/sync/{views,serializers,urls}.py`, router `/api/sync/category-runs/`, read-only — logic roll-up ở `apps/sync/services.py`): `GET /api/sync/category-runs/` (phân trang, mới nhất trước; group `run_id__isnull=False` theo `Min(created_at)`, roll-up Python: `site_count`, `total_pulled`/`total_mapped` từ `detail`, status all-success→success / all-error→error / trộn→partial; mỗi row thêm **`duration_seconds`** (max `created_at` − min `started_at`), **`triggered_by`** (tên người bấm, null nếu hệ thống), **`site_label`** (tên site khi run 1 site, null → FE hiện "N site"); **filter** `?status`/`?site`/`?date_from`/`?date_to`/`?search` — search khớp tên site/người chạy/UUID run, một row match là cả run hiện); `GET /stats/?site=&date_from=&date_to=&search=` (thẻ thống kê tab Lịch sử: `{total, success, partial, error, last_run}` trên cửa sổ — mặc định 30 ngày khi không truyền khoảng; cùng filter với list nên thẻ bám theo bộ lọc); `GET /{run_id}/` (per-site: site/url/hosting (FK sống ưu tiên, fallback snapshot trong `detail` khi site đã xóa), status/error/pulled/mapped + `categories` snapshot; 404 nếu không có); `GET /{run_id}/export/` → **Excel .xlsx** (openpyxl, in-memory BytesIO — vài nghìn dòng, cùng class với CSV/PDF export inline): sheet "Tổng quan" (timestamp localtime dd/mm/yyyy HH:MM:SS + mỗi site một dòng) + sheet "Chi tiết" phẳng (Site/Hosting/Woo ID/Tên Woo/Hub ID/Tên Hub — một sheet phẳng tránh giới hạn 31 ký tự tên sheet), `Content-Disposition: attachment; filename="bao-cao-danh-muc-<YYYYMMDD-HHMMSS>.xlsx"`. Run **không có marker kết thúc** — dòng per-site xuất hiện dần khi fan-out chạy xong từng site (FE có nút refresh). Dòng `SyncLog` cũ (trước khi có `run_id`) không bao giờ xuất hiện trong báo cáo.
- **API tiến trình run** (`RunProgressViewSet`, router `/api/sync/run-progress/`, read-only): `GET /api/sync/run-progress/{run_id}/?operation=` → `{run_id, operation, done, error_count}` — đếm số dòng `SyncLog` per-site đã đáp của một run (và bao nhiêu lỗi), **chung** cho cả 3 loại fan-out (`operation` ∈ `PROGRESS_OPERATIONS` = `pull_categories`/`push_products`/`poll_orders`; operation lạ → 404, `run_id` không phải UUID → 404 ở router). **Không bao giờ 404 khi UUID hợp lệ** mà trả `done=0` cho run vừa kích hoạt — banner tiến trình poll mỗi 3s tới khi `done ≥ expected` (số `expected` lấy từ response của endpoint trigger) hoặc quá hạn an toàn 3 phút. Nuôi banner "Đang đồng bộ… X/Y site hoàn tất" ở trang Đơn hàng / Sản phẩm (và modal đồng bộ theo sản phẩm), giống cơ chế trang Danh mục.
- **Thư viện media sản phẩm** (`ProductImage`, `apps/catalog/models.py` — kiểu WP Media Library): `image` (ImageField `upload_to="products/%Y/%m/"`), `original_name`, `uploaded_at`; **không gắn với product** — thư viện dùng chung, một ảnh tái sử dụng cho nhiều sản phẩm. API `ProductImageViewSet` (router `/api/products/media/`, đăng ký **trước** `products`, multipart): `GET` (mới nhất trước, `?search=` theo tên file), `POST` (field `image`, validate content-type ∈ jpeg/png/gif/webp + ≤5MB như site-note; **webp được re-encode thành PNG khi lưu** — nhiều site WP/shared-host từ chối sideload webp và lỗi đó giết cả product item trong batch), `DELETE /{id}/` (hard delete, xóa cả file khỏi MEDIA_ROOT). Serializer trả **`url` tuyệt đối** (`request.build_absolute_uri`) — FE lưu URL đó vào `MasterProduct.images` / nhúng `<img>` vào `description`, nên model catalog vẫn URL-based và payload push Woo (`[{"src": url}]`) **không đổi**; site Woo tự tải file về khi nhận product. **Lưu ý deploy:** URL media phải reachable từ các site Woo — set **`MEDIA_PUBLIC_BASE_URL`** (.env, vd `https://hub.example.com`) để serializer build URL theo domain public của Hub thay vì host của request (fallback `request.build_absolute_uri` chỉ đúng khi Woo sandbox cùng máy); để trống ở dev thuần local. Ảnh trỏ `localhost` khiến site thật reject cả product (`woocommerce_product_image_upload_error`, thấy được trong `SyncLog.detail["failed"]`). Đổi host (tunnel mới/deploy) → URL đã lưu trong product mang host cũ; chạy `python manage.py set_media_public_url <base-url>` để viết lại mọi URL `/media/` trong `images`/description/`variations` (link ngoài không bị đụng). Dev dùng `scripts/dev-tunnel.ps1` (root repo): tự chạy cloudflared quick tunnel → ghi `.env` → restart backend+celery → chạy command trên.
- **Admin**: `MasterProductAdmin` (editable, normalize sku khi save, `ProductMappingInline` read-only, action "Đồng bộ sản phẩm đã chọn" → `push_all_products.delay`); `SyncLogAdmin` read-only.

## 9. Local vs Production

- **Local:** Postgres + Redis chạy Docker; Django/Celery chạy host. WooCommerce **sandbox** chạy local (WordPress + WooCommerce qua Docker) để test full luồng mà không chạm web thật. `DEBUG=True`.
- **Production:** đổi `.env` (DB, Redis, domain Hub có HTTPS), `DEBUG=False`, `ALLOWED_HOSTS` rõ; site trỏ webhook về domain Hub thật. Kiến trúc không đổi.

## 10. Ngoài phạm vi (giai đoạn này)

- Frontend React — dự án tách trong `frontend/`; xem `docs/frontend/ARCHITECTURE.md`.
- Đồng bộ giá theo khu vực / multi-currency, phân quyền người dùng nhiều cấp — chưa làm.
- Đồng bộ hai chiều sản phẩm (site → Hub) — hiện chỉ một chiều Hub → site (trừ đơn hàng).
