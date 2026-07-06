// Shared copy for the product-push confirm step. A push fans out to many sites
// and runs far longer than a request can wait, so both entry points (the
// per-product sync panel and the "push to ALL sites" action) gate it behind a
// type-to-confirm keyword and tell the user the result arrives by email — the
// frontend no longer polls the run to completion.

export const PUSH_CONFIRM_WORD = "PUSH";

export const PUSH_EMAIL_NOTICE =
  "Hệ thống cần nhiều thời gian để đồng bộ sản phẩm lên các trang web. " +
  "Kết quả đồng bộ sẽ được gửi qua email tới địa chỉ bạn đã cấu hình nhận " +
  "thông báo đồng bộ dữ liệu.";
