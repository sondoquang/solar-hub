# Solar Hub

Hệ thống quản trị tập trung cho công ty bán SolarPower — gom nhiều website **WooCommerce** về một nơi.

- **Backend (Hub)** — Django + DRF + Celery: là **single source of truth (SSOT)**. Nói chuyện với từng WooCommerce site qua REST API, gom đơn hàng, CRUD + đồng bộ sản phẩm, giám sát site.
- **Frontend** — React + Vite: dashboard cho admin & marketing. **Chỉ là client của backend**, không bao giờ gọi WooCommerce trực tiếp.

> Việc quan trọng nhất: **gom đơn hàng** từ mọi site rồi forward marketing. Việc thứ hai: **đăng/đồng bộ sản phẩm đồng loạt** xuống các site.

---

## Tech stack

| Lớp | Công nghệ |
|---|---|
| Backend | Python 3.12, Django 5.x, Django REST Framework |
| Job nền | Celery 5.x + Beat, broker Redis 7 |
| Database | PostgreSQL (chạy trên host OS) |
| HTTP client | httpx (gọi WooCommerce), cryptography/Fernet (mã hóa key) |
| Frontend | React 18 + Vite, @tanstack/react-query, axios, react-router-dom, Tailwind CSS |
| Hạ tầng dev | Docker Compose (backend + celery worker + beat + frontend + redis) |

---

## Cấu trúc dự án

```
solar-hub/
├── README.md                  # file này
├── CLAUDE.md                  # context cho AI coding agent
├── docker-compose.yml         # 5 service: backend, celery_worker, celery_beat, frontend, redis
├── docs/
│   ├── backend/               # PROJECT_RULE.md + ARCHITECTURE.md (backend)
│   └── frontend/              # PROJECT_RULE.md + ARCHITECTURE.md (frontend)
├── backend/                   # Django app
│   ├── config/                # settings, celery, urls, wsgi/asgi
│   ├── apps/
│   │   ├── core/              # endpoint /api/health/
│   │   ├── sites/             # đăng ký site + key (mã hóa)            [stub]
│   │   ├── catalog/           # MasterProduct + ProductMapping        [stub]
│   │   ├── orders/            # gom đơn + webhook + forward            [stub]
│   │   ├── sync/              # Celery tasks: push sản phẩm, poll đơn  [stub]
│   │   ├── monitoring/        # healthcheck site                      [stub]
│   │   └── integrations/      # WooClient — wrapper REST API           [skeleton]
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
└── frontend/                  # React app
    ├── src/
    │   ├── api/               # axios client + React Query hooks
    │   ├── pages/             # Dashboard, Orders, Products, Sites, Login
    │   ├── components/        # Loading, ErrorState, EmptyState, AppLayout
    │   └── lib/               # helper (format VND, date)
    ├── package.json
    ├── Dockerfile
    └── .env.example
```

> **Trạng thái hiện tại:** đây là bản **scaffold** — toàn bộ stack đã chạy và kết nối end-to-end, nhưng các app domain (`sites`, `catalog`, `orders`, `sync`, `monitoring`) mới là **stub**, chưa có nghiệp vụ. Xem lộ trình ở cuối file.

---

## Yêu cầu

- **Docker Desktop** (Windows/Mac/Linux) — đã bật.
- **PostgreSQL chạy sẵn trên máy host** (không chạy trong Docker). App trong container kết nối ra Postgres của host qua `host.docker.internal`.

---

## Setup & chạy (Docker)

### 1. Chuẩn bị database trên host

Tạo database và một role có quyền login + password:

```sql
CREATE DATABASE solar_hub;
CREATE ROLE "solar-hub" LOGIN PASSWORD 'matkhau-cua-ban';
GRANT ALL PRIVILEGES ON DATABASE solar_hub TO "solar-hub";
```

> Có thể tạo bằng pgAdmin hoặc `psql`. Đảm bảo role **LOGIN** được (group role NOLOGIN sẽ không đăng nhập được).

### 2. Tạo file `.env`

```powershell
Copy-Item backend\.env.example backend\.env
Copy-Item frontend\.env.example frontend\.env
```

Mở `backend\.env` và sửa:

- **`DATABASE_URL`** — trỏ tới Postgres của host. Định dạng:
  ```
  DATABASE_URL=postgres://<user>:<password>@host.docker.internal:5432/solar_hub
  ```
  ⚠️ **Ký tự đặc biệt trong password phải URL-encode.** Ví dụ password `Dfghjklo@1` → `@` thành `%40`:
  ```
  DATABASE_URL=postgres://solar-hub:Dfghjklo%401@host.docker.internal:5432/solar_hub
  ```
  (Các ký tự khác cần encode: `:` → `%3A`, `/` → `%2F`, `#` → `%23`, `?` → `%3F`, `%` → `%25`.)

- **`DJANGO_SECRET_KEY`** — đổi sang chuỗi ngẫu nhiên.
- **`FERNET_KEY`** — `.env.example` để placeholder; sinh key thật bằng:
  ```powershell
  python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
  ```

### 3. Build & khởi động

```powershell
docker compose build
docker compose up -d
```

### 4. Migrate + tạo superuser

```powershell
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser
```

### 5. Truy cập

| | URL |
|---|---|
| Frontend (dashboard) | http://localhost:5173 |
| Django Admin | http://localhost:8000/admin/ |
| API health check | http://localhost:8000/api/health/ |

`GET /api/health/` trả `{"status":"ok","db":true,"redis":true}` khi mọi thứ kết nối ổn.

---

## Lệnh thường dùng

```powershell
# Xem trạng thái / log
docker compose ps
docker compose logs -f backend
docker compose logs -f celery_worker

# Dừng / khởi động lại
docker compose down
docker compose restart backend

# Backend: test, lint, format (chạy trong container)
docker compose exec backend pytest
docker compose exec backend ruff check .
docker compose exec backend ruff format .

# Backend: tạo migration sau khi đổi model
docker compose exec backend python manage.py makemigrations
docker compose exec backend python manage.py migrate

# Frontend: test, lint, build (chạy trong container)
docker compose exec frontend npm test
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
```

> Source được **bind-mount** vào container nên sửa code là backend (runserver) và frontend (Vite HMR) tự reload — không cần build lại image cho thay đổi code thường ngày.

---

## (Tùy chọn) Dev trên host — hot reload nhanh hơn

Chạy ngoài Docker khi cần reload tức thì:

```powershell
# Backend
cd backend
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Khi chạy trên host: dùng localhost thay cho host.docker.internal trong DATABASE_URL & REDIS_URL
python manage.py runserver        # http://localhost:8000

# Frontend
cd frontend
npm install
npm run dev                        # http://localhost:5173
```

Lúc này backend và frontend khác origin nên cần CORS — đã cấu hình sẵn cho `http://localhost:5173`.

---

## Troubleshooting

- **`password authentication failed for user "..."`** — sai user/password trong `DATABASE_URL`, hoặc chưa URL-encode ký tự đặc biệt (xem bước 2).
- **Backend container tắt ngay sau khi `up`** — Django `runserver` kiểm tra migration lúc khởi động và **thoát nếu không kết nối được DB**. Phải có DB đúng credential + database `solar_hub` tồn tại *trước khi* `up`. Xem log: `docker compose logs backend`.
- **`connection refused` tới Postgres** — Postgres host phải cho phép kết nối từ Docker bridge: `listen_addresses='*'` và một dòng trong `pg_hba.conf` cho phép subnet container (dev: `host all all 0.0.0.0/0 scram-sha-256` rồi reload). Trên Docker Desktop, `host.docker.internal` đã tự trỏ về host.
- **Sai port Postgres** — chỉ cần đổi port trong `DATABASE_URL` (`backend/.env`), không hard-code ở nơi khác.

---

## Tài liệu chi tiết

| Cần làm việc với... | Đọc |
|---|---|
| Tổng thể hệ thống | [CLAUDE.md](CLAUDE.md) |
| Code backend | [docs/backend/PROJECT_RULE.md](docs/backend/PROJECT_RULE.md), [docs/backend/ARCHITECTURE.md](docs/backend/ARCHITECTURE.md) |
| Code frontend | [docs/frontend/PROJECT_RULE.md](docs/frontend/PROJECT_RULE.md), [docs/frontend/ARCHITECTURE.md](docs/frontend/ARCHITECTURE.md) |

---

## Lộ trình build

1. **Site registry + test kết nối** — model `Site`, lưu key (mã hóa Fernet), gọi `system_status` xác nhận key chạy.
2. **Gom đơn hàng** — webhook + poll dự phòng → lưu `Order` → auto-forward marketing.
3. **Master catalog + bulk sync** — `MasterProduct` + `ProductMapping`, dùng `products/batch`.
4. **Monitoring** — healthcheck task cập nhật `Site.status`.
5. **Dashboard React** — màn đơn/sản phẩm cho marketing.

> Đóng gói production thành **một image duy nhất** (nginx + supervisor + gunicorn) là bước triển khai về sau — xem `tech-stack-woocommerce-hub.md`.
