# PROJECT_RULE.md — Backend

> Vị trí: `docs/backend/PROJECT_RULE.md`. Context gốc: `/CLAUDE.md`. Thiết kế: `docs/backend/ARCHITECTURE.md`.

Quy tắc code cho **backend** Solar Hub. Mục tiêu: nhất quán, an toàn, dễ test, idempotent.

---

## 1. Ngôn ngữ & công cụ

- Python **3.12+**, Django **5.x**, DRF.
- Format & lint bằng **ruff** (thay cho black + isort + flake8). Chạy `ruff format` + `ruff check` trước khi commit.
- **Type hints** cho mọi hàm public (service, client, task). Model fields không cần annotate thêm.
- Quản lý dependency qua `requirements.txt` (pin version). Không cài lung tung ngoài file.

## 2. Cấu trúc & phân lớp

- Mỗi domain là một Django app trong `apps/`: `sites`, `catalog`, `orders`, `sync`, `monitoring`, `integrations`.
- Phân lớp rõ: **view (mỏng) → service (business logic) → model/ORM**. View chỉ nhận request, validate, gọi service, trả response.
- Logic tích hợp ngoài (gọi WooCommerce) **chỉ** ở `apps/integrations/`. Các app khác import `WooClient`, không tự gọi HTTP.
- Hàm dài quá ~40 dòng hoặc lồng quá 3 cấp → tách nhỏ.

## 3. Django

- **Settings đọc từ `.env`** (django-environ). Không hard-code DB URL, key, secret trong settings.
- Một thay đổi model = một **migration** đi kèm trong cùng commit. Migration phải chạy được cả `migrate` lẫn `migrate --plan` không lỗi.
- Model chỉ chứa field + ràng buộc + method đơn giản (`__str__`, computed property nhẹ). Logic nghiệp vụ → service.
- Mọi ràng buộc toàn vẹn để ở DB: `unique`, `unique_together`, `db_index` cho cột hay query (vd `Order.created_at`, `MasterProduct.sku`).
- Tận dụng **Django Admin** cho quản trị catalog/site/log — đăng ký model vào admin, đừng dựng UI thủ công ở giai đoạn đầu.

## 4. DRF (API)

- API đặt dưới prefix `/api/`. Webhook đặt dưới `/api/webhooks/`.
- Dùng `ModelSerializer` + `ViewSet` cho CRUD chuẩn; `APIView` cho endpoint đặc thù (webhook).
- Bật **pagination** mặc định cho list (đơn hàng có thể rất nhiều). FE sẽ dựa vào pagination này.
- Validate input ở serializer, không ở view.
- Không trả raw exception/traceback ra response. Lỗi nghiệp vụ → mã lỗi + message gọn.

## 5. Celery & job nền

- **Task phải idempotent.** Chạy lại 2 lần cho kết quả như 1 lần (dùng upsert theo unique key).
- Đặt tên task đầy đủ path: `apps.sync.tasks.poll_all_orders`. Khai báo trong `beat_schedule` ở `config/celery.py`.
- Call mạng trong task phải có **timeout** và **retry** với backoff: `autoretry_for=(httpx.HTTPError,)`, `retry_backoff=True`, `max_retries` hợp lý.
- Không chạy đồng bộ nặng (poll/push) trong request cycle DRF — luôn `.delay()` sang Celery.
- Task lớn (sync N site) chia theo site, mỗi site một task con để lỗi một site không kéo cả mẻ.

## 6. Tích hợp WooCommerce

- Mọi call qua `WooClient`. Mỗi method có **timeout** (orders ~30s, batch ~60s) và `raise_for_status()`.
- **Throttle:** khi sync nhiều site, thêm delay nhẹ giữa các request, giới hạn số site chạy song song. Shared host (TenTen) dễ nghẽn.
- **Batch trước, đừng loop từng item.** Dùng `products/batch` với `create/update/delete`, tối đa ~100 item/request.
- Auth: Basic Auth (consumer_key/secret). Nếu host strip header `Authorization` → fallback query string, **chỉ trên HTTPS**. Local sandbox dùng Basic Auth bình thường.
- **Phân quyền key tối thiểu:** key đọc đơn = Read; key sync sản phẩm = Read/Write.

## 7. Bảo mật

- **Secret không bao giờ vào git/log.** `.env` trong `.gitignore`.
- `consumer_secret` lưu DB ở dạng **mã hóa Fernet**; chỉ giải mã trong bộ nhớ khi gọi API. Không có endpoint nào trả secret ra ngoài.
- **Không log PII** (tên, phone, address khách) ở mức INFO. Cần debug thì mask.
- Webhook: **verify HMAC** bằng secret của webhook trước khi tin payload.
- Production: HTTPS bắt buộc, `DEBUG=False`, `ALLOWED_HOSTS` cấu hình rõ. (Local thì DEBUG=True được.)

## 8. Toàn vẹn dữ liệu

- Ghi đơn: `Order.objects.update_or_create(site=.., woo_order_id=.., defaults={...})`.
- Mapping sản phẩm: `update_or_create(master=.., site=.., defaults={"woo_product_id": ..})`.
- **Chuẩn hóa SKU** (trim, upper, bỏ khoảng trắng thừa) trước khi lưu/khớp.
- Không xóa cứng dữ liệu nghiệp vụ tùy tiện — ưu tiên đổi `status`. Xóa sản phẩm trên site qua mảng `delete` của batch, nhưng giữ lịch sử mapping nếu cần truy vết.

## 9. Lỗi & logging

- Ghi mọi thao tác sync vào bảng `sync_logs` (site, operation, status, error, timestamp) để truy vết.
- Không **nuốt** exception (`except: pass`). Bắt đúng loại, log, và xử lý/đẩy retry.
- Log có cấu trúc, kèm `site_id`/`operation` để lọc. Mức: lỗi tích hợp = ERROR, retry = WARNING, luồng bình thường = INFO (không kèm PII).

## 10. Testing

- Dùng **pytest** + `pytest-django`. Đặt test cạnh app: `apps/<app>/tests/`.
- **Mock toàn bộ call WooCommerce** (respx/responses hoặc monkeypatch `WooClient`). Test không chạm mạng thật.
- Bắt buộc test các luồng: parse đơn từ payload Woo, build payload sản phẩm cho batch, và **tính idempotent** (gọi 2 lần → 1 bản ghi).
- Dùng factory (factory_boy) cho dữ liệu test thay vì fixture tay.

## 11. Git & commit

- Branch: `feat/<mô-tả>`, `fix/<mô-tả>`, `chore/<...>`.
- Commit theo **Conventional Commits**: `feat(orders): ingest webhook`, `fix(sync): handle 100-item batch limit`.
- PR nhỏ, một mục đích. Mô tả thay đổi + cách test.
- Không commit: `.env`, secret, file build, `.venv/`, `__pycache__/`.

## 12. Tài liệu

- Đổi cấu trúc app / luồng dữ liệu / quyết định thiết kế → cập nhật `docs/backend/ARCHITECTURE.md`.
- Đổi lệnh chạy / quy tắc cốt lõi cấp hệ thống → cập nhật `/CLAUDE.md` (root).
- Endpoint mới → ghi chú ngắn (path, method, mục đích) trong docstring view hoặc README app.
