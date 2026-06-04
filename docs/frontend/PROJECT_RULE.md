# PROJECT_RULE.md — Frontend

> Vị trí: `docs/frontend/PROJECT_RULE.md`. Context gốc: `/CLAUDE.md`. Thiết kế: `docs/frontend/ARCHITECTURE.md`.

Quy tắc code cho **frontend** Solar Hub. Mục tiêu: nhất quán, dữ liệu luôn đúng trạng thái, dashboard nhanh và dễ đọc cho đội vận hành.

---

## 1. Ngôn ngữ & công cụ

- React 18, **Vite**, **JSX** (JavaScript). Giai đoạn đầu không dùng TypeScript để đi nhanh.
  - Muốn an toàn kiểu dữ liệu mà chưa chuyển TS: dùng **JSDoc** cho hàm/hook quan trọng, hoặc **zod** để validate dữ liệu API ở ranh giới `src/api/`.
  - Khi quyết định chuyển TS sau này: `npm i -D typescript`, đổi dần `.jsx`→`.tsx`, thêm `tsconfig`. Cập nhật rule này khi chuyển.
- **ESLint + Prettier** bắt buộc. Chạy `npm run lint` trước khi commit.
- Quản lý dependency qua `package.json` + lockfile. Không thêm thư viện nặng nếu chưa cần (xem mục State).

## 2. Cấu trúc & phân lớp

- `src/api/` — tầng giao tiếp backend: một axios instance, các hàm gọi endpoint, và **React Query hooks** bọc chúng. Không component nào gọi axios trực tiếp.
- `src/pages/` — màn theo route, lắp ráp components + hooks. Mỏng.
- `src/components/` — UI tái dùng, **presentational** (nhận props, không tự fetch).
- `src/hooks/` — custom hook không phải data-fetching (vd `useDebounce`, `useFilters`).
- `src/lib/` — helper thuần (format tiền VND, format ngày, transform).
- Component > ~150 dòng hoặc làm quá nhiều việc → tách nhỏ.

## 3. Component

- Chỉ dùng **function component + hooks**. Không class component.
- **Logic không nằm trong JSX:** tính toán/format đưa vào hook hoặc `lib`. JSX chỉ lo render.
- Tách **container** (lấy data qua hook) và **presentational** (nhận props) khi component lớn lên.
- Props rõ ràng; nếu không dùng TS thì cân nhắc `prop-types` cho component dùng nhiều.
- Tránh prop-drilling sâu: nâng state lên hợp lý hoặc dùng context cho state UI dùng chung (không cho server state).

## 4. State & dữ liệu

- **Server state → React Query.** Đơn, sản phẩm, site, dashboard đều fetch qua hook React Query. Không `useEffect + fetch`.
- **UI state → `useState`/`useReducer`** (filter đang chọn, modal mở/đóng, form...).
- **Không thêm Redux.** Nếu thực sự cần global UI state phức tạp, dùng **Zustand** (nhẹ) và ghi lý do vào `docs/frontend/ARCHITECTURE.md`.
- Query key có cấu trúc: `["orders", filters]`, `["products"]`, `["sites"]`. Mutation xong **invalidate** đúng key.
- Đơn hàng nên bật **refetch định kỳ / refetchOnWindowFocus** để dashboard gần real-time (đây là tính năng quan trọng nhất).

## 5. Tầng API

- **Một axios instance** trong `src/api/client.js`, `baseURL = import.meta.env.VITE_API_BASE_URL`. Không hard-code URL.
- Interceptor:
  - request: đính token Authorization.
  - response: bắt lỗi tập trung (401 → điều hướng login; 5xx → toast lỗi chung).
- Validate/parse dữ liệu API ở ranh giới này (zod hoặc hàm map) để component nhận shape ổn định.
- Mọi endpoint là một hàm + một hook React Query tương ứng. Component import hook, không import axios.
- **Chỉ gọi backend Hub** (`/api/...`). Tuyệt đối không gọi WooCommerce.

## 6. Routing

- `react-router-dom`. Route chính: `/` (Dashboard), `/orders`, `/products`, `/sites`, `/login`.
- Route cần đăng nhập bọc trong guard kiểm tra auth; chưa auth → `/login`.
- **Lazy-load** trang nặng bằng `React.lazy` + `Suspense`.

## 7. Styling & thiết kế

- **Tailwind CSS.** Định nghĩa **design token** (màu, spacing, radius, shadow) trong `tailwind.config` / CSS variables — không rải giá trị magic.
- Chọn **một hướng thẩm mỹ rõ ràng và nhất quán** cho dashboard: ưu tiên rõ ràng, mật độ dữ liệu hợp lý, dễ quét bằng mắt (đây là công cụ vận hành, không phải landing page).
- Một cặp font có chủ đích (1 display + 1 body dễ đọc cho bảng số liệu). **Tránh aesthetic "AI slop"**: không mặc định Inter/Arial/system font, không gradient tím trên nền trắng, không layout rập khuôn.
- **Accessibility:** màu đủ tương phản, focus state rõ, `aria-*` cho control, dùng đúng thẻ ngữ nghĩa. Bảng dữ liệu phải có header đúng.
- **Responsive** ở mức hợp lý (dùng chính trên desktop, nhưng không vỡ trên tablet).
- Trạng thái rõ ràng: hàng/đơn theo màu trạng thái (badge), site up/down bằng chấm xanh/đỏ nhất quán.

## 8. Form & validate

- Form phức tạp (tạo/sửa sản phẩm, đăng ký site): dùng **react-hook-form**; validate bằng **zod** (resolver).
- Validate phía client trước khi gửi; vẫn tin lỗi từ server và hiển thị lại.
- Disable nút submit khi đang gửi; tránh double-submit.

## 9. Loading / Error / Empty (bắt buộc)

- Mọi view có dữ liệu phải có **3 trạng thái**: loading (skeleton/spinner), error (thông báo + nút thử lại), empty (gợi ý hành động).
- Mutation: dùng **toast** báo thành công/thất bại. Lỗi không được nuốt im lặng.
- Không để màn trắng hoặc hiển thị `undefined`.

## 10. Hiệu năng

- **Pagination** cho danh sách đơn (đừng tải hết). Khớp với pagination của DRF.
- `React.lazy` cho route; `useMemo`/`useCallback` chỉ khi có lý do đo được, không tối ưu sớm.
- Tránh re-render thừa do tạo object/array mới trong render (đưa ra ngoài hoặc memo).

## 11. Bảo mật

- **Không secret trong frontend.** Mọi bí mật ở backend. `.env` frontend chỉ chứa `VITE_API_BASE_URL` (giá trị công khai được).
- Token: không lưu thông tin nhạy cảm ở `localStorage` thường; ưu tiên cookie httpOnly do backend set, hoặc giữ token trong bộ nhớ + refresh. Quyết định cuối ghi vào `docs/frontend/ARCHITECTURE.md`.
- **Không log PII** (tên/sđt/địa chỉ) ở production. Mask khi debug.
- Hiển thị dữ liệu người dùng đúng cách (React tự escape; tránh `dangerouslySetInnerHTML`).

## 12. Testing

- **Vitest** + **React Testing Library**. Test hành vi, không test chi tiết triển khai.
- **MSW** để mock API — không gọi backend thật trong test.
- Bắt buộc test: hàm format (tiền/ngày), hook lấy đơn (loading→data→error), và form validate.

## 13. Git & commit

- Branch: `feat/<...>`, `fix/<...>`, `chore/<...>`.
- **Conventional Commits**: `feat(orders): add status filter`, `fix(api): handle 401 redirect`.
- PR nhỏ, một mục đích, mô tả cách test. Không commit `.env`, `node_modules/`, `dist/`.

## 14. Tài liệu

- Đổi route/cấu trúc/luồng dữ liệu/quyết định state → cập nhật `docs/frontend/ARCHITECTURE.md`.
- Đổi lệnh chạy / quy tắc cốt lõi cấp hệ thống → cập nhật `/CLAUDE.md` (root).
- Endpoint mới dùng ở FE → ghi chú ngắn trong `src/api/` (hàm + hook + mục đích).
