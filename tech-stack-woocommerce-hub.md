# Tech Stack — Hệ thống quản trị tập trung WooCommerce (Docker single-image)

> Tài liệu công nghệ để build hệ thống **Hub** quản lý nhiều website WooCommerce: CRUD sản phẩm đồng loạt + đồng bộ, gom/giám sát đơn hàng. Bản này build bằng **Docker, đóng gói thành MỘT image duy nhất chứa cả frontend + backend**, dùng **nginx làm reverse proxy**, và **DB local** (không bắt buộc pull image PostgreSQL). Chạy local trước; lên host chỉ đổi `.env`.

---

## 1. Mục tiêu & nguyên tắc

Hub là "single source of truth": bạn thao tác sản phẩm/đơn hàng tại Hub, Hub nói chuyện với từng WooCommerce site qua **REST API** (`/wp-json/wc/v3/...`). Không cần biết PHP/WordPress.

Bốn nguyên tắc cho bản Docker này:
/pp
1. **Một image duy nhất** chứa frontend (đã build tĩnh) + backend + nginx + gunicorn + Celery. Build một lần, chạy ở đâu cũng vậy.
2. **Frontend build trước thành file tĩnh**, **nginx phục vụ trực tiếp** và **reverse proxy `/api` về backend**. Frontend và backend **cùng một origin** → không còn vấn đề CORS, cookie cross-site, cấu hình gọn nhất.
3. **DB local**: mặc định dùng **SQLite** (file trong volume, không pull image gì); khi cần mạnh hơn thì trỏ sang **PostgreSQL cài sẵn trên host** — vẫn không phải pull image Postgres từ registry.
4. **Mọi cấu hình qua `.env`** — local và production chỉ khác nhau ở file env.

> **Lưu ý về cách bạn mô tả ("reverse proxy về port của frontend"):** trong image, frontend **không chạy dev server** (Vite cổng 5173 chỉ dùng khi dev trên host). Frontend được **build ra file tĩnh** và nginx phục vụ thẳng các file đó — không cần proxy tới "port frontend". nginx chỉ reverse proxy phần động (`/api`, `/admin`) về gunicorn. Đây là cách chuẩn và **chạy nhanh nhất** cho một image gộp.

---

## 2. Tổng quan công nghệ

| Lớp | Công nghệ | Phiên bản đề xuất | Vai trò |
| --- | --- | --- | --- |
| Reverse proxy / web | **nginx** | mới nhất | Phục vụ FE tĩnh + proxy `/api`,`/admin` về gunicorn |
| WSGI server | **gunicorn** | mới nhất | Chạy Django trong image |
| Process manager | **supervisor** | mới nhất | Chạy nhiều process trong 1 container (nginx, gunicorn, celery) |
| Ngôn ngữ backend | Python | 3.12+ | Nền tảng Hub |
| Web framework | Django | 5.x | Core app + Django Admin |
| REST API | Django REST Framework | mới nhất | API cho dashboard + nhận webhook |
| Job nền | Celery + Beat | 5.x | Sync sản phẩm, poll đơn, healthcheck |
| Message broker | Redis | 7.x (alpine) | Broker cho Celery |
| Database (local) | **SQLite** _hoặc_ Postgres trên host | — | Mặc định SQLite; khỏi pull image |
| Database (prod) | PostgreSQL | 16.x | Khi lên host |
| HTTP client | httpx | mới nhất | Gọi WooCommerce REST API |
| Frontend | React + Vite | React 18/19, Vite 5/6 | Dashboard (build tĩnh) |
| Build FE (stage 1) | Node.js | 20 LTS / 22 LTS | Chỉ dùng lúc build image |
| WooCommerce test | WordPress + WooCommerce + MariaDB | image official | Sandbox test (compose riêng) |

> **Một image build, tối thiểu image pull.** Bạn chỉ _build_ duy nhất image `solar-hub`. Redis chỉ là image alpine ~30MB (cần làm broker cho Celery) — nếu muốn thật sự "một container", có thể nhúng luôn `redis-server` vào image qua supervisor (xem mục 7.4). DB SQLite thì không pull gì cả.

---

## 3. Cấu trúc thư mục dự án

```
solar-hub/
├── Dockerfile                  # multi-stage: build FE -> gộp BE + nginx + supervisor
├── .dockerignore
├── docker-compose.yml          # app (1 image) + redis (+ db tùy chọn)
├── docker-compose.woo.yml      # WordPress + WooCommerce + MariaDB (sandbox test)
├── .env.example
├── deploy/
│   ├── nginx.conf              # serve FE tĩnh + proxy /api,/admin
│   ├── supervisord.conf        # nginx + gunicorn + celery worker + beat
│   └── entrypoint.sh           # migrate + collectstatic rồi chạy supervisor
├── backend/
│   ├── manage.py
│   ├── requirements.txt
│   ├── config/                 # settings, celery, urls, wsgi
│   └── apps/
│       ├── sites/              # đăng ký site + key (model: Site)
│       ├── catalog/            # master_products + product_mappings
│       ├── orders/             # orders + webhook endpoint + forward
│       ├── sync/               # Celery tasks: push sản phẩm, poll đơn
│       ├── monitoring/         # healthcheck task + trạng thái site
│       └── integrations/
│           └── woocommerce.py  # WooClient — wrapper gọi REST API
└── frontend/
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── api/                # axios client gọi /api (cùng origin)
        ├── pages/              # Orders, Products, Sites, Dashboard
        └── components/
```

---

## 4. Backend — Django + DRF + Celery

### 4.1. `backend/requirements.txt`

```txt
Django>=5.0
djangorestframework
django-environ            # đọc .env
django-cors-headers       # chỉ cần cho dev (Vite 5173); cùng image thì không cần
psycopg[binary]           # driver PostgreSQL (khi dùng Postgres)
celery>=5.3
redis                     # client redis cho Celery
httpx                     # gọi WooCommerce API
cryptography              # mã hóa consumer_secret trong DB
gunicorn                  # WSGI server trong image
```

> SQLite không cần driver. `psycopg` chỉ dùng khi `DATABASE_URL` trỏ Postgres.

### 4.2. `config/settings.py` (phần quan trọng)

```python
import environ
env = environ.Env()
environ.Env.read_env()

DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])  # local để *; prod khai báo rõ

# DB local: SQLite (mặc định) hoặc Postgres-trên-host qua DATABASE_URL
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="sqlite:////app/data/db.sqlite3",  # file trong volume
    )
}
# Giảm "database is locked" khi nhiều process cùng ghi SQLite (local)
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    DATABASES["default"].setdefault("OPTIONS", {})["timeout"] = 20

CELERY_BROKER_URL = env("REDIS_URL", default="redis://redis:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

# Static cho Django Admin/DRF — nginx phục vụ từ thư mục này
STATIC_URL = "/static/"
STATIC_ROOT = "/app/staticfiles"

# Đứng sau nginx (reverse proxy)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=["http://localhost"])

# CORS: chỉ bật khi dev trên host (Vite 5173). Cùng image -> cùng origin -> bỏ qua.
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:5173"])
```

### 4.3. Celery — `config/celery.py`

```python
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
app = Celery("solar_hub")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "poll-orders-every-3-min": {"task": "apps.sync.tasks.poll_all_orders", "schedule": 180.0},
    "healthcheck-every-5-min": {"task": "apps.monitoring.tasks.check_all_sites", "schedule": 300.0},
}
```

### 4.4. WooCommerce client — `apps/integrations/woocommerce.py`

```python
import httpx

class WooClient:
    def __init__(self, site):
        self.base = site.base_url.rstrip("/") + "/wp-json/wc/v3"
        self.auth = (site.consumer_key, site.decrypt_secret())

    def list_orders(self, after=None, status="processing", per_page=100):
        params = {"per_page": per_page, "status": status}
        if after:
            params["after"] = after  # ISO timestamp, chỉ lấy đơn mới
        r = httpx.get(f"{self.base}/orders", params=params, auth=self.auth, timeout=30)
        r.raise_for_status()
        return r.json()

    def batch_products(self, create=None, update=None, delete=None):
        payload = {"create": create or [], "update": update or [], "delete": delete or []}
        r = httpx.post(f"{self.base}/products/batch", json=payload, auth=self.auth, timeout=60)
        r.raise_for_status()
        return r.json()

    def system_status(self):
        return httpx.get(f"{self.base}/system_status", auth=self.auth, timeout=15)
```

> **Bẫy shared host (TenTen):** một số host strip header `Authorization`. Nếu Basic Auth lỗi, fallback truyền key qua query string (`?consumer_key=...&consumer_secret=...`) **bắt buộc HTTPS**. Local sandbox thì Basic Auth bình thường.

### 4.5. Models cốt lõi (rút gọn)

```python
# apps/sites/models.py
class Site(models.Model):
    name = models.CharField(max_length=120)
    base_url = models.URLField()
    consumer_key = models.CharField(max_length=120)
    consumer_secret_enc = models.BinaryField()   # mã hóa, không lưu plaintext
    status = models.CharField(max_length=20, default="unknown")  # up/down/unknown

# apps/catalog/models.py
class MasterProduct(models.Model):
    sku = models.CharField(max_length=80, unique=True)  # KHÓA khớp xuyên site
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    regular_price = models.DecimalField(max_digits=12, decimal_places=0)
    stock = models.IntegerField(default=0)
    images = models.JSONField(default=list)
    status = models.CharField(max_length=20, default="draft")

class ProductMapping(models.Model):
    master = models.ForeignKey(MasterProduct, on_delete=models.CASCADE)
    site = models.ForeignKey(Site, on_delete=models.CASCADE)
    woo_product_id = models.IntegerField()      # ID riêng trên từng site
    last_synced = models.DateTimeField(null=True)
    class Meta:
        unique_together = ("master", "site")

# apps/orders/models.py
class Order(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE)
    woo_order_id = models.IntegerField()
    customer_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=40)
    address = models.TextField(blank=True)
    line_items = models.JSONField(default=list)
    total = models.DecimalField(max_digits=12, decimal_places=0)
    status = models.CharField(max_length=40)
    forwarded = models.BooleanField(default=False)  # đã gửi marketing chưa
    created_at = models.DateTimeField()
    class Meta:
        unique_together = ("site", "woo_order_id")  # tránh trùng đơn
```

> **Điểm dữ liệu quan trọng nhất:** mỗi site có `woo_product_id` riêng cho cùng một sản phẩm → bắt buộc có `ProductMapping`. **SKU** là chìa khóa khớp sản phẩm. **Category/attribute cũng có ID riêng từng site** → map trước khi sync.

---

## 5. Background jobs — luồng nghiệp vụ

Hai task chính trong `apps/sync/tasks.py`:

**Gom đơn (poll dự phòng cho webhook):** lặp từng site → `list_orders(after=mốc_lần_trước)` → `update_or_create` vào `Order` theo `(site, woo_order_id)` → đơn mới chưa `forwarded` thì đẩy marketing (Telegram / Google Sheet / dashboard).

**Đồng bộ sản phẩm:** với mỗi site, duyệt `MasterProduct` → tra `ProductMapping`: chưa có thì gom `create`, đã có thì gom `update` theo `woo_product_id` → gọi `batch_products(...)` một lần → lưu `woo_product_id` trả về vào mapping. Nút "Sync all" ở dashboard kích hoạt task này cho mọi site.

**Webhook (real-time, ưu tiên hơn poll):** endpoint DRF `POST /api/webhooks/orders/?site=<id>`. Trong WooCommerce: `Settings > Advanced > Webhooks`, topic _Order created_, delivery URL trỏ về endpoint này. Hub verify HMAC rồi lưu đơn.

---

## 6. Frontend — React + Vite

### 6.1. `frontend/package.json` (dependencies chính)

```json
{
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^6",
    "axios": "^1",
    "@tanstack/react-query": "^5"
  },
  "devDependencies": {
    "vite": "^5",
    "@vitejs/plugin-react": "^4"
  }
}
```

### 6.2. Gọi API theo đường dẫn tương đối (cùng origin)

Vì nginx phục vụ FE và proxy `/api` cùng một origin, axios chỉ cần `baseURL = "/api"` — không hard-code `http://localhost:8000`. Lúc build image, đặt biến `VITE_API_BASE_URL=/api`. Khi **dev trên host** (Vite 5173 gọi Django 8000) thì đặt `VITE_API_BASE_URL=http://localhost:8000/api` và bật CORS.

```js
// src/api/client.js
import axios from "axios";
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api",
});
```

---

## 7. Đóng gói Docker — một image duy nhất

### 7.1. `Dockerfile` (multi-stage: FE build trước → gộp vào BE)

```dockerfile
# ---------- Stage 1: build frontend thành file tĩnh ----------
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ENV VITE_API_BASE_URL=/api          # cùng origin với nginx
RUN npm run build                    # -> /fe/dist

# ---------- Stage 2: backend + nginx + supervisor ----------
FROM python:3.12-slim AS app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        nginx supervisor \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./

# FE build (stage 1) -> nơi nginx phục vụ
COPY --from=frontend /fe/dist /app/frontend_dist

# Cấu hình
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/supervisord.conf /etc/supervisor/conf.d/solarhub.conf
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /app/data /app/staticfiles

EXPOSE 80
ENTRYPOINT ["/entrypoint.sh"]
```

### 7.2. `deploy/nginx.conf` — serve FE tĩnh + proxy phần động

```nginx
server {
    listen 80;
    server_name _;
    client_max_body_size 25m;

    root /app/frontend_dist;
    index index.html;

    # API + admin -> gunicorn (Django)
    location /api/   { proxy_pass http://127.0.0.1:8000; include /etc/nginx/proxy_params; }
    location /admin/ { proxy_pass http://127.0.0.1:8000; include /etc/nginx/proxy_params; }

    # Static của Django (admin/DRF)
    location /static/ { alias /app/staticfiles/; }

    # SPA fallback cho React Router
    location / { try_files $uri $uri/ /index.html; }
}
```

> `proxy_params` (có sẵn trong gói nginx Debian) đã set `Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`. Nếu image không có file này, thêm thủ công các header đó vào mỗi block proxy.

### 7.3. `deploy/supervisord.conf` — chạy nhiều process trong 1 container

```ini
[supervisord]
nodaemon=true

[program:gunicorn]
command=gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3
directory=/app
autorestart=true
stdout_logfile=/dev/stdout
stderr_logfile=/dev/stderr
stdout_logfile_maxbytes=0
stderr_logfile_maxbytes=0

[program:nginx]
command=nginx -g 'daemon off;'
autorestart=true
stdout_logfile=/dev/stdout
stderr_logfile=/dev/stderr
stdout_logfile_maxbytes=0
stderr_logfile_maxbytes=0

[program:celery_worker]
command=celery -A config worker -l info
directory=/app
autorestart=true
stdout_logfile=/dev/stdout
stderr_logfile=/dev/stderr
stdout_logfile_maxbytes=0
stderr_logfile_maxbytes=0

[program:celery_beat]
command=celery -A config beat -l info
directory=/app
autorestart=true
stdout_logfile=/dev/stdout
stderr_logfile=/dev/stderr
stdout_logfile_maxbytes=0
stderr_logfile_maxbytes=0
```

### 7.4. (Tùy chọn) Nhúng luôn Redis vào image để thành "một container"

Nếu muốn không pull cả image Redis: `apt-get install redis-server` trong Dockerfile và thêm program vào supervisor. Khi đó `REDIS_URL=redis://127.0.0.1:6379/0`.

```ini
[program:redis]
command=redis-server --save "" --appendonly no
autorestart=true
stdout_logfile=/dev/stdout
stderr_logfile=/dev/stderr
stdout_logfile_maxbytes=0
stderr_logfile_maxbytes=0
```

> Khuyến nghị: với local, để Redis **container riêng** (`redis:7-alpine`) vẫn sạch và dễ quản lý hơn. Nhúng vào chỉ khi bạn thực sự cần đúng một container.

### 7.5. `deploy/entrypoint.sh`

```bash
#!/usr/bin/env bash
set -e
python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec supervisord -c /etc/supervisor/conf.d/solarhub.conf
```

---

## 8. `docker-compose.yml` — app (1 image) + DB local

```yaml
services:
  app:
    build: . # build DUY NHẤT image này
    image: solar-hub:local
    env_file: .env
    ports: ["80:80"] # truy cập http://localhost
    depends_on: [redis]
    volumes:
      - appdata:/app/data # SQLite + media (DB local, không pull image)
      - staticfiles:/app/staticfiles
    extra_hosts:
      - "host.docker.internal:host-gateway" # để gọi Postgres cài trên host (Linux)

  redis:
    image: redis:7-alpine

volumes:
  appdata:
  staticfiles:
```

**Chọn DB local trong `.env`:**

- **SQLite (mặc định, khỏi pull gì):** `DATABASE_URL=sqlite:////app/data/db.sqlite3`
- **Postgres cài sẵn trên máy bạn (không pull image):** `DATABASE_URL=postgres://hub:hub@host.docker.internal:5432/solarhub`
- (Nếu sau này muốn Postgres trong Docker: thêm service `db: image: postgres:16` rồi trỏ `@db:5432`.)

> SQLite hợp cho local nhẹ. Khi chạy đủ tải (gunicorn + 2 process Celery cùng ghi) mà gặp `database is locked`, chuyển sang Postgres-trên-host là hết.

---

## 9. Biến môi trường — `.env.example`

```env
# Django
DJANGO_SECRET_KEY=dev-only-change-me
DEBUG=True
ALLOWED_HOSTS=*
CSRF_TRUSTED_ORIGINS=http://localhost

# DB local: chọn 1 trong 2
DATABASE_URL=sqlite:////app/data/db.sqlite3
# DATABASE_URL=postgres://hub:hub@host.docker.internal:5432/solarhub

# Redis (broker Celery)
REDIS_URL=redis://redis:6379/0
# Nếu nhúng Redis vào image: redis://127.0.0.1:6379/0

# Khóa mã hóa consumer_secret (Fernet)
FERNET_KEY=thay-bang-key-sinh-tu-cryptography

# Forward đơn cho marketing (điền khi cần)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
GOOGLE_SHEET_ID=
```

---

## 10. Quy trình chạy local

### 10.1. Chạy bằng Docker (đường chính)

```bash
cp .env.example .env            # điền giá trị, chọn DATABASE_URL
docker compose build            # build 1 image solar-hub:local
docker compose up -d            # app + redis

# Tạo superuser (chạy trong container app đang chạy)
docker compose exec app python manage.py createsuperuser

# -> Mở http://localhost         (frontend)
# -> http://localhost/admin      (Django Admin)
# -> http://localhost/api        (REST API)
```

`entrypoint.sh` tự `migrate` + `collectstatic` mỗi lần container khởi động; supervisor chạy nginx + gunicorn + celery worker + beat trong cùng container.

### 10.2. (Tùy chọn) Dev nhanh trên host — hot reload

Khi code và cần reload tức thì, chạy ngoài Docker sẽ nhanh hơn build image:

```bash
cd backend && python manage.py runserver        # 8000
cd frontend && npm run dev                       # 5173 (đặt VITE_API_BASE_URL=http://localhost:8000/api)
```

Lúc này bật CORS cho `http://localhost:5173`. Khi xong thì build lại image để chạy thống nhất.

### 10.3. WooCommerce sandbox để test — `docker-compose.woo.yml`

```yaml
services:
  woo_db:
    image: mariadb:11
    environment:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: wordpress
      MYSQL_USER: wp
      MYSQL_PASSWORD: wp
    volumes: ["woodb:/var/lib/mysql"]

  wordpress:
    image: wordpress:latest
    depends_on: [woo_db]
    ports: ["8080:80"] # http://localhost:8080
    environment:
      WORDPRESS_DB_HOST: woo_db
      WORDPRESS_DB_USER: wp
      WORDPRESS_DB_PASSWORD: wp
      WORDPRESS_DB_NAME: wordpress
    volumes: ["wpdata:/var/www/html"]

volumes:
  woodb:
  wpdata:
```

```bash
docker compose -f docker-compose.woo.yml up -d
```

Sau khi up: vào `http://localhost:8080` cài WordPress → cài plugin **WooCommerce** → `WooCommerce > Settings > Advanced > REST API` tạo Consumer Key/Secret → đăng ký site vào Hub với `base_url = http://localhost:8080`. Test full: tạo sản phẩm ở Hub đẩy xuống, đặt thử đơn trên sandbox xem nó chảy về Hub. Giả lập nhiều site thì copy compose đổi cổng (8081, 8082...).

> Webhook từ sandbox → Hub: vì cả hai chạy Docker trên cùng máy, delivery URL dùng `http://host.docker.internal/api/webhooks/orders/?site=<id>` (hoặc IP máy host).

---

## 11. Lộ trình build (ưu tiên giải phóng việc đau nhất trước)

1. **Site registry + test kết nối** — model `Site`, lưu key (mã hóa), gọi `system_status` xác nhận key chạy. Quản trị qua Django Admin.
2. **Gom đơn hàng** — webhook + poll dự phòng → lưu `Order` → auto-forward marketing. _Làm trước, lấy lại nhiều thời gian nhất._
3. **Master catalog + bulk sync** — `MasterProduct` + `ProductMapping`, dùng `products/batch`, đồng bộ category/attribute trước.
4. **Monitoring** — healthcheck task cập nhật `Site.status`.
5. **Dashboard React** — màn đơn/sản phẩm cho marketing (đã gộp sẵn vào image).

---

## 12. Vài lưu ý kỹ thuật để khỏi vấp

- **Cùng origin → không cần CORS** ở bản image (FE và API đều qua nginx). CORS chỉ cho dev trên host.
- **`collectstatic` cho admin/DRF**: nginx phục vụ `/static/` từ `STATIC_ROOT=/app/staticfiles`; entrypoint đã chạy sẵn.
- **Đứng sau proxy**: đã set `SECURE_PROXY_SSL_HEADER` và `CSRF_TRUSTED_ORIGINS`; khi lên domain HTTPS nhớ cập nhật `ALLOWED_HOSTS` + `CSRF_TRUSTED_ORIGINS`.
- **SQLite + nhiều process**: nếu gặp `database is locked`, tăng `timeout` hoặc chuyển Postgres-trên-host.
- **SKU chuẩn hóa thống nhất** trước khi sync — khóa khớp duy nhất giữa các site.
- **Throttle khi sync nhiều site** (shared host yếu): delay nhẹ, không bắn song song ồ ạt, batch ~100 item/lần.
- **Phân quyền API key:** key đọc đơn = _Read_; key sync sản phẩm = _Read/Write_.
- **Ảnh sản phẩm:** truyền URL (`images[].src`), WooCommerce tự tải; host ảnh tập trung để khỏi upload lại.
- **Idempotent:** luôn `update_or_create` theo `(site, woo_order_id)` và `(master, site)` để webhook + poll trùng nhau không tạo bản ghi đôi.
