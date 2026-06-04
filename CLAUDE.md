# CLAUDE.md

> File context gốc cho AI coding agent (Claude Code) của **toàn bộ monorepo Solar Hub**. Đọc kỹ trước khi sửa bất kỳ thứ gì.
> Đây là repo gồm **`backend/`** (Django) và **`frontend/`** (React). Quy tắc & thiết kế chi tiết nằm trong **`docs/`** (xem bảng bên dưới).

## Dự án là gì

**Solar Hub** — hệ thống quản trị tập trung cho công ty bán SolarPower, gom nhiều website WooCommerce về một nơi.

- **`backend/`** (Hub, Django + DRF + Celery + PostgreSQL): là **single source of truth (SSOT)**. Nói chuyện với từng WooCommerce site qua REST API. Gom đơn hàng, CRUD + đồng bộ sản phẩm, giám sát site.
- **`frontend/`** (React + Vite): dashboard cho admin & marketing. **Chỉ là client của backend**, không bao giờ gọi WooCommerce trực tiếp.

Việc quan trọng nhất của hệ thống: **gom đơn hàng** từ mọi site rồi forward marketing. Việc thứ hai: **đăng/đồng bộ sản phẩm đồng loạt** xuống các site.

## Cấu trúc monorepo

```
project-root/
├── CLAUDE.md                  # file này — context gốc
├── docs/
│   ├── backend/
│   │   ├── PROJECT_RULE.md     # luật code backend
│   │   └── ARCHITECTURE.md     # thiết kế backend
│   └── frontend/
│       ├── PROJECT_RULE.md     # luật code frontend
│       └── ARCHITECTURE.md     # thiết kế frontend
├── backend/                   # Django app (config/, apps/, requirements.txt)
└── frontend/                  # React app (src/, package.json, vite.config.js)
```

## Đọc tài liệu nào trước khi làm gì

| Khi làm việc với... | Đọc bắt buộc |
|---|---|
| Code backend (Django/DRF/Celery/WooCommerce) | `docs/backend/PROJECT_RULE.md` + `docs/backend/ARCHITECTURE.md` |
| Code frontend (React/Vite/React Query) | `docs/frontend/PROJECT_RULE.md` + `docs/frontend/ARCHITECTURE.md` |
| Hiểu tổng thể hệ thống | File này + cả hai `ARCHITECTURE.md` |

## Tech stack tóm tắt

- **Backend:** Python 3.12+, Django 5.x, DRF, Celery 5.x + Beat (broker Redis 7), PostgreSQL 16, httpx, Fernet (mã hóa key).
- **Frontend:** React 18 + Vite (JSX), @tanstack/react-query, axios, react-router-dom, Tailwind CSS.
- **Hạ tầng local:** Docker Compose (Postgres + Redis); WooCommerce sandbox (WordPress + WooCommerce + MariaDB) để test.

## Lệnh thường dùng

```bash
# Hạ tầng (chạy trước, từ root hoặc backend/)
docker compose up -d                 # postgres + redis

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver           # http://localhost:8000  (+ /admin)
celery -A config worker -l info      # terminal riêng
celery -A config beat -l info        # terminal riêng

# Frontend
cd frontend
npm install
npm run dev                          # http://localhost:5173
```

## Quy tắc TỐI QUAN TRỌNG (xuyên suốt, agent phải tuân thủ)

**Toàn hệ thống**
1. **Backend là SSOT.** Mọi nghiệp vụ tích hợp (gọi WooCommerce, gom đơn, build payload sản phẩm) ở backend. Frontend chỉ hiển thị + gửi lệnh.
2. **Frontend KHÔNG gọi WooCommerce trực tiếp** — chỉ gọi backend Hub.
3. **Bí mật không vào git/log/frontend.** `.env` trong `.gitignore`; `consumer_secret` mã hóa Fernet ở backend; FE chỉ chứa `VITE_API_BASE_URL`.
4. **Không log PII** (tên/sđt/địa chỉ khách) ở production, cả hai bên.

**Backend** (chi tiết: `docs/backend/PROJECT_RULE.md`)
5. **Idempotent:** upsert đơn theo `(site, woo_order_id)`, mapping theo `(master, site)`.
6. **SKU là khóa khớp sản phẩm** xuyên site; `woo_product_id`/category/attribute là **riêng từng site**.
7. **Mọi call WooCommerce qua `WooClient`**; dùng **batch** + **throttle**; webhook phải **verify HMAC**.

**Frontend** (chi tiết: `docs/frontend/PROJECT_RULE.md`)
8. **Server state = React Query**; một axios instance, `baseURL` từ env.
9. **Mọi view dữ liệu có đủ loading / error / empty**; mutation xong **invalidate** query liên quan.

## Định nghĩa "xong"

Tuân theo phần "Định nghĩa xong" trong `PROJECT_RULE.md` của bên tương ứng. Tối thiểu: lint sạch, có test (mock API/WooCommerce, không gọi mạng thật), và **cập nhật `docs/<bên>/ARCHITECTURE.md`** nếu đổi cấu trúc/luồng.

## Đừng làm

- Đừng để frontend gọi WooCommerce hay tự build payload Woo.
- Đừng commit `.env`/secret; đừng lưu token nhạy cảm ở `localStorage`.
- Đừng "đoán" ID sản phẩm/category giữa các site (backend).
- Đừng đặt nghiệp vụ nặng trong request cycle DRF — đẩy sang Celery.
- Đừng trộn file backend/frontend lẫn thư mục của nhau.
