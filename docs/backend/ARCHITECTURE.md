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
| `catalog` | `MasterProduct` (catalog gốc) + `ProductMapping` (master ↔ woo_product_id từng site). |
| `orders` | `Order` (đơn đã chuẩn hóa) + endpoint webhook + logic forward marketing. |
| `sync` | Celery tasks: push sản phẩm xuống site (batch), poll đơn định kỳ. |
| `monitoring` | Healthcheck site **theo nhóm hosting** (fan-out 1 task/hosting, throttle song song trong mỗi hosting), cập nhật `Site.status`. Lưu **lịch sử kiểm tra** (`HealthCheck`) mỗi lần test kết nối + API đọc lịch sử cho dashboard. |
| `integrations` | `WooClient` — lớp trừu tượng hóa toàn bộ giao tiếp WooCommerce REST API. |
| `core` | App hạ tầng (không phải domain): expose `GET /api/health/` trả `{status, db, redis}` để kiểm tra stack đã kết nối. Endpoint **không auth** (health check không được chạm DB). |
| `accounts` | Auth JWT (SimpleJWT) + hồ sơ người dùng. Endpoints: `POST /api/auth/token/` (đăng nhập), `POST /api/auth/token/refresh/`, `GET/PATCH /api/auth/me/` (xem/cập nhật `full_name`+`email`, trả thêm `role` suy ra từ `is_superuser`/`is_staff`), `POST /api/auth/change-password/` (đổi mật khẩu, validate mật khẩu cũ + password validators). |

## 4. Mô hình dữ liệu

```
Hosting (1) ──< Site (N)                (1 hosting = 1 server/tài khoản, nhiều domain)
Site (1) ──< ProductMapping >── (1) MasterProduct
  │                                     (sku UNIQUE = khóa khớp xuyên site)
  ├──< Order
  └──< SyncLog
```

> **`Hosting`** gom nhiều `Site` cùng một server/shared host. `Site.hosting` là FK nullable
> (`on_delete=SET_NULL`) — site chưa gán hosting được xử lý như nhóm riêng (`hosting_id=None`).
> Mục đích chính: **throttle healthcheck theo hosting** để không dội request lên host yếu.

Ràng buộc toàn vẹn cốt lõi:

- `MasterProduct.sku` **UNIQUE** — khóa khớp sản phẩm giữa các site.
- `ProductMapping` **UNIQUE (master, site)** — mỗi sản phẩm gốc map đúng một `woo_product_id` trên mỗi site.
- `Order` **UNIQUE (site, woo_order_id)** — chống trùng đơn khi webhook + poll cùng bắn.

> Bất biến quan trọng: **`woo_product_id`, category ID, attribute ID là RIÊNG theo từng site.** Hub không bao giờ giả định chúng giống nhau; mọi tham chiếu qua `ProductMapping`.

## 5. Luồng dữ liệu

### 5.1. Gom đơn (quan trọng nhất)

**Chính — Webhook (real-time):** WooCommerce mỗi site cấu hình webhook topic *Order created*, delivery URL → `POST /api/webhooks/orders/?site=<id>`. Hub **verify HMAC** → chuẩn hóa payload → `update_or_create` vào `Order` → đẩy task forward marketing.

**Dự phòng — Poll (định kỳ):** Celery Beat chạy `poll_all_orders` mỗi ~3 phút: với mỗi site gọi `GET /orders?after=<mốc_lần_trước>&status=processing`, upsert đơn mới. Bù cho trường hợp shared host chặn outbound webhook hoặc webhook miss.

Cả hai đường cùng đổ vào một upsert idempotent → an toàn khi trùng. Đơn mới (`forwarded=False`) được gửi marketing (Telegram / Google Sheet / dashboard) rồi đánh dấu `forwarded=True`.

### 5.2. Đồng bộ sản phẩm

Thao tác CRUD diễn ra trên `MasterProduct` tại Hub (qua Admin/API). Khi "Sync all", `push_all_products` fan-out theo batch site → `push_products_batch_task` → `apps/catalog/services.push_products_to_site` chạy cho từng site:

1. Duyệt `MasterProduct`, tra `ProductMapping` của site đó.
2. Chưa có mapping & chưa xóa → mảng `create`; đã có mapping & chưa xóa → `update` theo `woo_product_id`; đã có mapping & **soft-deleted** → `delete` (rồi gỡ mapping).
3. Gọi `WooClient.batch_products(create, update, delete)` — chia chunk **≤ `PRODUCT_BATCH_ITEM_LIMIT` (~100) item/request**, throttle `PRODUCT_PUSH_THROTTLE_SECONDS` giữa chunk.
4. Khớp response **theo SKU** → upsert `woo_product_id` + `last_synced_at` vào `ProductMapping`, ghi `SyncLog`. Lỗi mạng được **nuốt theo site** (trả `error`, ghi `SyncLog(error)`, không raise) để một site hỏng không kéo cả mẻ.

**v1 (hiện tại):** category/attribute xử lý **theo tên** — `MasterProduct.categories` là list tên, push gửi `categories=[{name}]` để Woo tự khớp/tạo (không có bảng mapping category/attribute per-site). Mapping category/attribute theo ID riêng từng site (đồng bộ **trước** sản phẩm) để dành pha sau.

### 5.3. Giám sát

`check_all_sites` chạy mỗi ~5 phút và **fan-out 1 sub-task `check_hosting_task` cho mỗi hosting** (cộng một nhóm `hosting_id=None` cho site chưa gán) → các hosting khác nhau chạy **song song** qua Celery, nhưng trong cùng một hosting `services.check_hosting` chỉ check **tối đa `Hosting.check_concurrency` domain đồng thời** (mặc định 5, dùng `ThreadPoolExecutor`; phần dư xếp hàng đợi). Nhờ vậy một shared host yếu không bị nhiều domain ping cùng lúc. Mỗi site vẫn cập nhật `Site.status`/`last_checked_at` qua `services.test_connection` như cũ. Hosting yếu đặt `check_concurrency` thấp hơn. Production có thể thay/bổ sung bằng UptimeRobot cho nhẹ.

## 6. Lớp tích hợp (`WooClient`)

Mọi giao tiếp WooCommerce tập trung tại đây để cô lập đặc thù của shared host:

- Auth Basic (key/secret), **fallback query string trên HTTPS** nếu host strip header `Authorization`.
- Timeout theo loại call; `raise_for_status()`; `consumer_secret` chỉ giải mã trong bộ nhớ.
- **Throttle**: delay giữa request, giới hạn song song khi sync nhiều site.
- Dùng **batch** thay vì loop từng item.
- **Ghi**: `update_order(woo_order_id, status=)` (`PUT /orders/{id}`) — cùng pattern auth/timeout/fallback-401 như `list_orders`, trả payload đơn đã cập nhật để caller upsert lại Hub.
- **Batch sản phẩm**: `batch_products(create, update, delete)` (`POST /products/batch`) — đã hiện thực, cùng pattern auth/fallback-401, timeout 60s (ghi nặng hơn đọc). Trả `{create, update, delete}` mỗi item kèm `id`+`sku`. **Caller (`push_products_to_site`) chịu trách nhiệm chia chunk ≤100 item.**

## 7. Xử lý nền

- **Celery worker** thực thi task; **Celery Beat** lên lịch (`poll_all_orders`, `check_all_sites`). Broker = **Redis**. Push sản phẩm (`push_all_products` → `push_products_batch_task`) chạy on-demand (UI/Admin), không lên lịch.
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

## 8b. Trạng thái hiện thực (Phase 1 — Site registry)

App `sites` đã hiện thực đầy đủ vertical slice (model → service → API/Admin → FE):

- **Model `Site`** (`apps/sites/models.py`): `name`, `base_url`, `consumer_key`, `consumer_secret_enc` (BinaryField — ciphertext Fernet), `status` (up/down/unknown, `db_index`), `last_checked_at`, timestamps. Mã hóa/giải mã ở `apps/sites/crypto.py`; nghiệp vụ ở `apps/sites/services.py`.
- **API** (router DRF, prefix `/api/`):
  - `GET/POST /api/sites/`, `GET/PATCH/DELETE /api/sites/{id}/` — CRUD. `consumer_secret` **write-only**, không bao giờ trả ra response.
  - `POST /api/sites/{id}/test_connection/` — gọi `WooClient.system_status()`, cập nhật `Site.status`, trả `{ok, status, detail}`. **Chạy đồng bộ** (một call, timeout 15s) vì là thao tác tương tác cần kết quả ngay; healthcheck định kỳ vẫn để Celery (`check_all_sites`, Phase 4).
  - `POST /api/sites/test_connections/` — body `{ids: [...]}`, test nhiều site **tuần tự** (one-at-a-time = throttle tự nhiên), trả `{results: [{id, ok, status, detail}]}`.
  - `POST /api/sites/import_excel/` — upload `.xlsx` (multipart field `file`), parse bằng `openpyxl` ở service, bulk-create (mã hóa secret), bỏ qua dòng thiếu data / `base_url` trùng và báo lỗi từng dòng. Trả `{created, errors:[{row, error}]}`. Cột yêu cầu: `name, base_url, consumer_key, consumer_secret`. Có field multipart tùy chọn `hosting` (id) → gán mọi site import vào hosting đó (id không hợp lệ → 400).
  - `PATCH /api/sites/{id}/` — sửa site; `consumer_secret` optional (chỉ re-encrypt khi gửi).
  - `GET /api/sites/?hosting=<id>` / `?hosting=none` — lọc site theo hosting (hoặc site chưa gán hosting). Serializer trả thêm `hosting` (id) + `hosting_name`.
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

- **Model `Order`** (`apps/orders/models.py`): `site` (FK→Site, CASCADE, `db_index`), `woo_order_id` (BigInteger — riêng từng site), `number`, `status` (`db_index`), `currency`, `total` (Decimal 12,2), thông tin KH `customer_name/phone/email/shipping_address/customer_note` (**PII — lưu DB nhưng KHÔNG log**), `line_items` (JSON: `{sku,name,quantity,total}`), `date_created_woo` (`db_index` — mốc tạo bên Woo), `date_modified_woo` (`db_index`, nullable — mốc sửa bên Woo, **dùng làm watermark poll**), `forwarded`/`forwarded_at`, `raw` (JSON payload gốc), timestamps. Ràng buộc `UniqueConstraint(site, woo_order_id)` (`order_unique_per_site`) → **upsert idempotent** an toàn khi poll/webhook trùng. Index kép `(site, date_created_woo)`, `(status, date_created_woo)`, `(forwarded, date_created_woo)`, `(site, status, date_modified_woo)` (watermark theo từng status).
- **`WooClient.list_orders(status, per_page, after, before, modified_after)`** (`apps/integrations/woocommerce.py`): `GET /orders` của **một status**, phân trang theo header `X-WP-TotalPages`, auth Basic + **fallback query-string khi gặp 401** (shared host strip header `Authorization`), timeout 30s, `raise_for_status()`. Poll định kỳ truyền `modified_after` + `dates_are_gmt=true` (mốc GMT, khớp `date_modified_gmt`); sync theo khoảng ngày dùng `after`/`before` (chặn theo `date_created`). Ghi: **`update_order(woo_order_id, status=)`** (`PUT /orders/{id}`) — cùng pattern auth/timeout/fallback, trả payload đơn đã cập nhật.
- **Service** (`apps/orders/services.py`): `POLL_STATUS="processing"` (default định kỳ) + `ALLOWED_POLL_STATUSES` (7 status chuẩn để API validate); `normalize_order` (map payload Woo → fields, ưu tiên `*_gmt`, lấy cả `date_modified_woo`), `upsert_order` (`update_or_create` theo `(site, woo_order_id)`), `poll_site(site, status, *, date_from=, date_to=)` — **hai chế độ loại trừ nhau**: (a) mặc định/định kỳ dùng watermark = `MAX(date_modified_woo)` của **`(site, status)`** → `list_orders(status=, modified_after=)` (key theo *modified* nên **bắt được cả đơn cũ đổi trạng thái**); (b) khi có `date_from`/`date_to` thì **bỏ watermark**, chặn theo `after`/`before` trên `date_created` (`_date_bounds` map `YYYY-MM-DD` → mốc GMT, bao trùm cả hai ngày — backfill theo yêu cầu). Bắt `httpx.HTTPError` trả `error`, **không** raise, log `site_id`+`status`+class lỗi, không log payload; `mark_order_completed(order)` (đẩy đơn `processing` → `completed` bằng `update_order` rồi upsert lại từ payload Woo, nên poll sau **không revert**; chỉ cho từ `processing`, nếu không raise `InvalidStatusTransition`), `list_orders_qs`/`order_stats` cho API.
- **Celery** (`apps/sync/tasks.py`): `poll_all_orders(status="processing", site_ids=None, date_from=None, date_to=None)` (Beat mỗi ~3 phút chạy default `processing` toàn bộ site, không date; UI có thể truyền status/sites/khoảng ngày khác) — chia site thành **mẻ `ORDER_POLL_BATCH_SIZE` (mặc định 8, env)** rồi dispatch `poll_sites_batch_task.delay(chunk, status, date_from, date_to)` mỗi mẻ; `poll_sites_batch_task` poll cả mẻ qua `ThreadPoolExecutor(max_workers=ORDER_POLL_BATCH_SIZE)` (cùng pattern `check_hosting`), lỗi một site không kéo cả mẻ. **Một lần sync = đúng một status** (hiệu năng). Poll định kỳ chỉ `processing`; các status khác / khoảng ngày sync theo yêu cầu từ UI.
- **API** (router DRF, prefix `/api/`, đơn được kéo về — không CRUD tay; write duy nhất là `complete`):
  - `GET /api/orders/` — list phân trang. Filter: `site`, `hosting` (`none` = chưa gán), `status`, `forwarded` (`true`/`false`), `date_from`/`date_to` (theo `date_created_woo__date`). Search (`?search=`) trên số đơn / tên KH / SĐT / tên site. Sort `date_created_woo`/`total`/`status`. Serializer flatten `site_name`/`hosting_name`; **không** expose `raw` ở list.
  - `GET /api/orders/{id}/` — chi tiết (modal hiển thị `line_items` + thông tin KH).
  - `GET /api/orders/stats/` — `{total, revenue, not_forwarded, by_status}` cho range đang lọc (**lưu ý** alias `Count` không được trùng tên field `total`, nếu không `Sum("total")` sẽ vỡ).
  - `POST /api/orders/poll_now/` — body tùy chọn `{status, sites, date_from, date_to}` (`status` mặc định `processing`, phải ∈ `ALLOWED_POLL_STATUSES`; `sites` = list id, bỏ trống = toàn bộ; `date_from`/`date_to` = `YYYY-MM-DD`, khi có thì sync re-pull đơn **tạo** trong khoảng đó thay vì dùng watermark). Validate sai (status/sites/date) → 400. Kích hoạt `poll_all_orders.delay(status=, site_ids=, date_from=, date_to=)`, trả `{task_id, status}` (nút "Đồng bộ ngay" của UI gửi status/scope/khoảng ngày đang lọc; scope "hosting" được FE expand thành list site id).
  - `POST /api/orders/{id}/complete/` — đánh dấu một đơn `completed`. **Chạy đồng bộ** (một `PUT` lên Woo, như `test_connection`) để UI nhận lại đơn đã cập nhật ngay; gọi `mark_order_completed`. Chỉ từ `processing` (nếu không → 409); lỗi WooCommerce → 502 (log `order_id`+`site_id`, không PII). Trả về đơn đã serialize.
  - `GET /api/orders/export_pdf/` — xuất **phiếu đơn hàng PDF** cho bộ phận kinh doanh (gom một file, **mỗi đơn một trang**). Query `?ids=1,2,3` giới hạn đúng các đơn đã chọn (giao với queryset đã lọc nên filter/quyền vẫn áp dụng); **bỏ `ids`** thì xuất toàn bộ selection đang lọc. `services.select_orders_for_pdf` sắp theo `date_created_woo` (thứ tự đọc) và **cap `MAX_PDF_ORDERS` (200)**. Trả `application/pdf` (`Content-Disposition: attachment`); một đơn → tên file `don-hang-<số_đơn>.pdf`, nhiều đơn → `don-hang.pdf`.
- **PDF** (`apps/orders/pdf.py`, lib **reportlab**): `build_orders_pdf(orders) -> bytes` dựng tài liệu Platypus (A4) — header Solar Hub, khối thông tin đơn + khách, bảng line items (STT/SKU/tên/SL/đơn giá/thành tiền) + tổng tiền, layout khớp modal chi tiết. Font **DejaVu Sans nhúng** (`apps/orders/fonts/DejaVuSans.ttf`, đăng ký một lần) vì font Type-1 mặc định của reportlab **không** có glyph tiếng Việt; tiền định dạng kiểu vi-VN (`1.850.000 ₫`). PII xuất hiện trong tài liệu theo chủ đích nhưng **không** log.
- **Admin**: `OrderAdmin` read-only (list_filter status/forwarded/site, date_hierarchy `date_created_woo`, không cho add/change).

## 8e. Trạng thái hiện thực (catalog + sync — Đồng bộ sản phẩm)

App `catalog` + `sync` đã hiện thực **backend** vertical slice đồng bộ sản phẩm Hub → site (frontend để pha sau). v1 xử lý category **theo tên** (xem §5.2):

- **Model `MasterProduct`** (`apps/catalog/models.py`): `sku` (CharField **UNIQUE**, `db_index` — khóa khớp xuyên site, chuẩn hóa trim/collapse/upper trước khi lưu), `name`, `type` (default `simple`), `description`/`short_description`, `regular_price`/`sale_price` (Decimal 12,2; `sale_price` nullable), `status` (draft/publish/pending/private), `stock_status` (instock/outofstock/onbackorder), `weight` (Decimal 8,3 nullable), `images` (JSON list URL), `categories` (JSON list **tên** category), **soft-delete** (`is_deleted`/`deleted_at`) + timestamps. `Meta.ordering = ["-updated_at"]`.
- **Model `ProductMapping`** (`apps/catalog/models.py`): `master` (FK→MasterProduct, CASCADE, `related_name="mappings"`), `site` (FK→Site, CASCADE, `db_index`, `related_name="product_mappings"`), `woo_product_id` (BigInteger — **riêng từng site**), `last_synced_at`, timestamps. Ràng buộc `UniqueConstraint(master, site)` (`mapping_unique_master_site` — upsert idempotent) + `UniqueConstraint(site, woo_product_id)` (`mapping_unique_site_woo`).
- **Model `SyncLog`** (`apps/sync/models.py`): `site` (FK→Site, **SET_NULL** nullable — log sống sót khi xóa site), `operation` (`db_index`, vd `push_products`), `status` (success/partial/error), `created_count`/`updated_count`/`deleted_count`, `error` (chỉ tên class lỗi — **không** payload/PII), `detail` (JSON tóm tắt), `created_at`. Append-only, admin read-only.
- **`WooClient.batch_products(create, update, delete)`** — xem §6.
- **Service** (`apps/catalog/services.py`): `normalize_sku` (trim/collapse/upper), `build_product_payload(master)` (map → fields Woo, giá/weight dạng string, `categories=[{name}]`, `images=[{src}]`, tách riêng để unit-test không cần DB), `push_products_to_site(site, *, masters=None)` (lõi "Sync all" — xem §5.2: plan create/update/delete theo mapping, chia chunk `PRODUCT_BATCH_ITEM_LIMIT` + throttle `PRODUCT_PUSH_THROTTLE_SECONDS`, khớp response theo SKU lưu `woo_product_id`, gỡ mapping khi delete, **nuốt lỗi theo site** + ghi `SyncLog`), `list_products_qs`/`product_stats` (mapped/unmapped/by_status) cho API.
- **Celery** (`apps/sync/tasks.py`): `push_all_products(site_ids=None, master_ids=None)` chia site thành **mẻ `PRODUCT_PUSH_BATCH_SIZE` (mặc định 8, env)** → dispatch `push_products_batch_task.delay(chunk, master_ids)`; batch task chạy qua `ThreadPoolExecutor` (mỗi worker `connection.close()`), gọi `push_products_to_site` mỗi site. On-demand (không Beat). Settings mới: `PRODUCT_PUSH_BATCH_SIZE`, `PRODUCT_BATCH_ITEM_LIMIT` (≤100), `PRODUCT_PUSH_THROTTLE_SECONDS`.
- **API** (`MasterProductViewSet`, router `/api/products/`): `GET/POST /api/products/`, `GET/PATCH/DELETE /api/products/{id}/` — CRUD (queryset ẩn soft-deleted, prefetch `mappings__site`). `DELETE` = **soft-delete** (để push sau gỡ sản phẩm khỏi site). Serializer normalize + check trùng `sku` (400 nếu trùng), trả `mappings` (nested per-site) + `mapping_count` (read-only). Search `sku`/`name`, sort `name`/`sku`/`updated_at`. `GET /api/products/stats/` (total/mapped/unmapped/by_status). `POST /api/products/sync_now/` — body tùy chọn `{sites, products}` (list id, validate → 400), kích hoạt `push_all_products.delay`, trả `{task_id}`.
- **Admin**: `MasterProductAdmin` (editable, normalize sku khi save, `ProductMappingInline` read-only, action "Đồng bộ sản phẩm đã chọn" → `push_all_products.delay`); `SyncLogAdmin` read-only.

## 9. Local vs Production

- **Local:** Postgres + Redis chạy Docker; Django/Celery chạy host. WooCommerce **sandbox** chạy local (WordPress + WooCommerce qua Docker) để test full luồng mà không chạm web thật. `DEBUG=True`.
- **Production:** đổi `.env` (DB, Redis, domain Hub có HTTPS), `DEBUG=False`, `ALLOWED_HOSTS` rõ; site trỏ webhook về domain Hub thật. Kiến trúc không đổi.

## 10. Ngoài phạm vi (giai đoạn này)

- Frontend React — dự án tách trong `frontend/`; xem `docs/frontend/ARCHITECTURE.md`.
- Đồng bộ giá theo khu vực / multi-currency, phân quyền người dùng nhiều cấp — chưa làm.
- Đồng bộ hai chiều sản phẩm (site → Hub) — hiện chỉ một chiều Hub → site (trừ đơn hàng).
