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
| `monitoring` | Healthcheck site **theo nhóm hosting** (fan-out 1 task/hosting, throttle song song trong mỗi hosting), cập nhật `Site.status`. |
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

Thao tác CRUD diễn ra trên `MasterProduct` tại Hub (qua Admin/API). Khi "Sync all", task `push_products` chạy cho từng site:

1. Duyệt `MasterProduct`, tra `ProductMapping` của site đó.
2. Chưa có mapping → đưa vào mảng `create`; đã có → `update` theo `woo_product_id`.
3. Gọi `WooClient.batch_products(create, update, delete)` — **một request, tối đa ~100 item**.
4. Lưu `woo_product_id` trả về vào `ProductMapping`, ghi `SyncLog`.

Category/attribute được đồng bộ và map **trước** sản phẩm (vì sản phẩm tham chiếu chúng qua ID riêng từng site).

### 5.3. Giám sát

`check_all_sites` chạy mỗi ~5 phút và **fan-out 1 sub-task `check_hosting_task` cho mỗi hosting** (cộng một nhóm `hosting_id=None` cho site chưa gán) → các hosting khác nhau chạy **song song** qua Celery, nhưng trong cùng một hosting `services.check_hosting` chỉ check **tối đa `Hosting.check_concurrency` domain đồng thời** (mặc định 5, dùng `ThreadPoolExecutor`; phần dư xếp hàng đợi). Nhờ vậy một shared host yếu không bị nhiều domain ping cùng lúc. Mỗi site vẫn cập nhật `Site.status`/`last_checked_at` qua `services.test_connection` như cũ. Hosting yếu đặt `check_concurrency` thấp hơn. Production có thể thay/bổ sung bằng UptimeRobot cho nhẹ.

## 6. Lớp tích hợp (`WooClient`)

Mọi giao tiếp WooCommerce tập trung tại đây để cô lập đặc thù của shared host:

- Auth Basic (key/secret), **fallback query string trên HTTPS** nếu host strip header `Authorization`.
- Timeout theo loại call; `raise_for_status()`; `consumer_secret` chỉ giải mã trong bộ nhớ.
- **Throttle**: delay giữa request, giới hạn song song khi sync nhiều site.
- Dùng **batch** thay vì loop từng item.

## 7. Xử lý nền

- **Celery worker** thực thi task; **Celery Beat** lên lịch (`poll_all_orders`, `check_all_sites`). Broker = **Redis**.
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
  - Task định kỳ `apps/monitoring/tasks.check_all_sites` đã được hiện thực: fan-out `check_hosting_task` mỗi hosting (xem §5.3).
- **Admin**: `SiteAdmin` cho nhập key (password widget, mã hóa khi save) + action "Test connection".
- `WooClient.system_status()` đã hiện thực; `list_orders`/`batch_products` còn `NotImplementedError`.

## 9. Local vs Production

- **Local:** Postgres + Redis chạy Docker; Django/Celery chạy host. WooCommerce **sandbox** chạy local (WordPress + WooCommerce qua Docker) để test full luồng mà không chạm web thật. `DEBUG=True`.
- **Production:** đổi `.env` (DB, Redis, domain Hub có HTTPS), `DEBUG=False`, `ALLOWED_HOSTS` rõ; site trỏ webhook về domain Hub thật. Kiến trúc không đổi.

## 10. Ngoài phạm vi (giai đoạn này)

- Frontend React — dự án tách trong `frontend/`; xem `docs/frontend/ARCHITECTURE.md`.
- Đồng bộ giá theo khu vực / multi-currency, phân quyền người dùng nhiều cấp — chưa làm.
- Đồng bộ hai chiều sản phẩm (site → Hub) — hiện chỉ một chiều Hub → site (trừ đơn hàng).
