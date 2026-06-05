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
| `src/components/` | UI tái dùng, presentational (Table, Badge, StatusDot, EmptyState, Skeleton...). |
| `src/hooks/` | Custom hook UI (filter, debounce). Không fetch data ở đây. |
| `src/lib/` | Helper thuần: format tiền VND, ngày, transform dữ liệu. |
| `src/routes.jsx` | Khai báo router + guard auth. |

## 4. Các màn hình

- **Dashboard (`/`)** — tổng quan: số đơn mới/đã forward, trạng thái sync gần nhất, đèn up/down từng site.
- **Orders (`/orders`)** — *quan trọng nhất*: bảng đơn gom từ mọi site, lọc theo site/trạng thái/thời gian, cờ "đã forward marketing", phân trang. Refetch định kỳ để gần real-time.
- **Products (`/products`)** — danh sách + form CRUD master catalog (SKU, giá, tồn, ảnh), nút **Sync all** (gọi API kích hoạt task đồng bộ ở backend), hiển thị trạng thái mapping theo site.
- **Sites (`/sites`)** — danh sách website, trạng thái up/down, form đăng ký site (nhập base_url + key — key chỉ gửi đi, không hiển thị lại).
- **Login (`/login`)** — đăng nhập lấy token.

## 5. Luồng dữ liệu

### 5.1. Đọc (queries)

Component gọi React Query hook trong `src/api/` → axios gọi DRF → dữ liệu được cache theo **query key** (`["orders", filters]`, `["products"]`, `["sites"]`). UI render theo 3 trạng thái loading/error/empty. Đơn hàng bật `refetchInterval`/`refetchOnWindowFocus` để cập nhật gần real-time.

### 5.2. Ghi (mutations)

Form (tạo/sửa sản phẩm, đăng ký site, bấm Sync all) gọi mutation hook → POST/PATCH lên DRF → thành công thì **invalidate** query liên quan để UI tự refresh, kèm **toast** báo kết quả. Thất bại thì giữ form và hiển thị lỗi từ server.

### 5.3. Đồng bộ sản phẩm (từ phía FE)

FE **không** tự đẩy sản phẩm xuống site. Bấm "Sync all" chỉ gọi một endpoint backend để **kích hoạt Celery task**; FE sau đó poll/hiển thị trạng thái sync (`SyncLog`/mapping) trả về từ Hub.

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
| Tắt Tailwind `preflight`, dùng `antd/dist/reset.css` | Tránh hai reset CSS đá nhau; antd là chủ đạo nên để reset của antd làm nền. |

## 9b. Trạng thái hiện thực (Phase 1 — Sites)

Trang **Sites (`/sites`)** đã hiện thực: `src/api/sites.js` (hooks `useSites/useCreateSite/useUpdateSite/useDeleteSite/useTestConnection/useTestConnections/useImportSites`, query key `["sites"]`, invalidate sau mutation). Components: `StatusDot` (chấm màu + nhãn up/down/tạm dừng), `SiteRegisterForm` (react-hook-form + zod, dùng chung cho **tạo và sửa** — edit thì secret optional), `SitesTable` (bảng + checkbox chọn + select-all theo trang + sort theo tên + per-row Test/Sửa/Xóa kèm icon), `SiteImport` (upload `.xlsx`), `SiteStats` (4 thẻ tổng hợp: tổng / hoạt động / tạm dừng / không hoạt động — count tính ở page), `TablePagination` (pager client-side: chọn page-size + chuyển trang). Tính năng:
- **Import Excel** hàng loạt (file parse ở backend) → toast tóm tắt created/errors.
- **Thêm/Sửa** site qua antd `Modal` (form nằm trong modal; PATCH với secret để trống = giữ nguyên).
- Nút **Test** mỗi site có loading ("Đang kiểm tra…") + disable chống spam (dựa `mutation.isPending`/`variables`).
- **Tick chọn nhiều site** + "Kiểm tra đã chọn" gọi bulk `test_connections`.
- **Sort theo tên** và **phân trang client-side** (asc/desc/none, page-size 10/20/50) — state ở page, components chỉ render + báo intent qua callback.
- Đủ loading/error/empty; toast cho mọi mutation; `consumer_secret` chỉ gửi đi, không hiển thị lại.

**Khung app (`AppLayout`)**: layout dạng **sidebar trái** (logo Solar Hub, nav có icon, mục **Website** mở rộng được với các mục con, thẻ hỗ trợ ở đáy) + **topbar** (chuông thông báo + hồ sơ người dùng). Các route đã có (`/`, `/orders`, `/products`, `/sites`, `/login`) dùng `NavLink`; mục chưa có route (Khách hàng, Báo cáo, Cài đặt hệ thống, các mục con Import Excel/Lịch sử/Cài đặt) là placeholder tĩnh, sẽ nối route khi dựng.

## 9c. UI stack — Ant Design chủ đạo + Tailwind tinh chỉnh

Từ phase này, **Ant Design (antd v5) là design system chủ đạo** cho dashboard; **Tailwind** giữ lại để tinh chỉnh spacing/màu lặt vặt và layout nhanh; **lucide-react** là bộ icon.

Cấu hình (xem `src/main.jsx`):

- `<StyleProvider layer>` (`@ant-design/cssinjs`) đưa style antd vào một CSS `@layer` → utility của Tailwind (không layer) luôn thắng khi cần ghi đè antd.
- `<ConfigProvider theme={...} locale={viVN}>` — theme antd nằm ở `src/lib/antdTheme.js`, **ánh xạ đúng design token** trong `src/index.css` (brand amber, success/warning/danger, radius). Đổi token thì sửa cả hai nơi.
- `<App>` của antd bọc app để dùng `message`/`modal`/`notification` tĩnh có context (`react-hot-toast` vẫn dùng cho toast mutation như cũ).
- `import "antd/dist/reset.css"` làm reset nền; Tailwind **tắt `preflight`** (`tailwind.config.js`) để không xung đột.

Quy ước dùng: ưu tiên component antd cho UI mới (Button, Table, Form, Modal, Select, DatePicker…); icon lấy từ `lucide-react` và truyền vào prop `icon`. Component cũ tự viết (`StatusDot`, `SitesTable`, `SiteRegisterForm`…) vẫn chạy, sẽ chuyển dần sang antd khi đụng tới. Mẫu đầu tiên: nút header trang Sites (`src/pages/Sites.jsx`) đã dùng `Button` + icon lucide.

## 10. Local vs Production

- **Local:** `VITE_API_BASE_URL=http://localhost:8000/api`, `npm run dev` ở cổng 5173 (backend đã whitelist CORS cổng này).
- **Production:** đổi `VITE_API_BASE_URL` sang domain Hub thật (HTTPS), `npm run build` ra `dist/` để serve tĩnh. Kiến trúc không đổi.

## 11. Ngoài phạm vi (giai đoạn này)

- Gọi WooCommerce trực tiếp — không bao giờ (thuộc backend).
- Phân quyền nhiều vai trò chi tiết, đa ngôn ngữ, dark/light theme switch — chưa làm.
- Realtime bằng WebSocket — hiện dùng polling của React Query là đủ.
