// Pure formatting helpers (no React, no I/O).

const vnd = new Intl.NumberFormat("vi-VN", {
  style: "currency",
  currency: "VND",
  maximumFractionDigits: 0,
});

export function formatVND(value) {
  const n = Number(value);
  if (Number.isNaN(n)) return "—";
  return vnd.format(n);
}

export function formatDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(d);
}

// "30/06/2024 09:30:15" — full timestamp with seconds (health-check log rows).
export function formatDateTime(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(d);
}

// Relative time in Vietnamese for recent events ("Vừa xong", "5 phút trước",
// "2 giờ trước", "3 ngày trước"); falls back to a short date past ~30 days.
export function timeAgo(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  const sec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return "Vừa xong";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} phút trước`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} giờ trước`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day} ngày trước`;
  return formatDate(value);
}

// Wall-clock duration in seconds → "mm:ss" (under an hour) or "hh:mm:ss".
// Used by the category sync-history "Thời gian" column.
export function formatDuration(seconds) {
  const n = Number(seconds);
  if (seconds == null || Number.isNaN(n) || n < 0) return "—";
  const total = Math.round(n);
  const s = total % 60;
  const m = Math.floor(total / 60) % 60;
  const h = Math.floor(total / 3600);
  const pad = (x) => String(x).padStart(2, "0");
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

// Title-case a person/customer name for display & export: first letter of each
// word uppercased, the rest lowercased ("nguyễn VĂN an" → "Nguyễn Văn An"). The
// synced/stored value is left untouched — this only formats output. Returns ""
// for blank input so callers keep their own fallback ("—", "Khách lẻ").
export function titleCaseName(value) {
  if (!value) return "";
  return String(value)
    .toLocaleLowerCase("vi")
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toLocaleUpperCase("vi") + w.slice(1))
    .join(" ");
}

// Response time: sub-second as "256 ms", ≥1s as "1.25 s".
export function formatResponseTime(ms) {
  const n = Number(ms);
  if (ms == null || Number.isNaN(n)) return "—";
  if (n < 1000) return `${n} ms`;
  return `${(n / 1000).toFixed(2)} s`;
}

// Sync errors reach the UI as the backend's raw exception class name (httpx etc.)
// — "ReadTimeout", "ConnectError", "HTTPStatusError" — which mean nothing to an
// end user. Map them to one short Vietnamese sentence each; the raw token is kept
// elsewhere (a tooltip) for support staff. Order matters: more specific patterns
// first (e.g. ConnectTimeout before the generic timeout/connect rules).
const SYNC_ERROR_RULES = [
  [/connect\s*timeout/i, "Không kết nối được tới website — quá thời gian chờ kết nối"],
  [/timed?\s*out|timeout/i, "Website phản hồi quá chậm, đã hết thời gian chờ"],
  [/connect|connection|getaddr|dns|resolve|nodename|unreachable|refused/i,
    "Không kết nối được tới website"],
  [/ssl|cert/i, "Lỗi chứng chỉ bảo mật (SSL) của website"],
  [/redirect/i, "Website chuyển hướng sai, không truy cập được"],
  [/401|403|forbidden|unauthor|authenticat/i,
    "Sai thông tin đăng nhập (key/secret) tới website"],
  [/404|not\s*found/i, "Không tìm thấy địa chỉ API trên website"],
  [/protocol|decod|json|parse|malformed/i, "Website trả về dữ liệu không hợp lệ"],
  [/5\d\d|internal\s*server|server\s*error/i, "Website đang gặp sự cố máy chủ"],
];

export function friendlySyncError(raw) {
  if (!raw) return "";
  const text = String(raw).trim();
  if (!text) return "";
  for (const [pattern, message] of SYNC_ERROR_RULES) {
    if (pattern.test(text)) return message;
  }
  return "Không đồng bộ được — website không phản hồi đúng";
}
