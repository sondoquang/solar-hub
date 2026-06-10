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

// Response time: sub-second as "256 ms", ≥1s as "1.25 s".
export function formatResponseTime(ms) {
  const n = Number(ms);
  if (ms == null || Number.isNaN(n)) return "—";
  if (n < 1000) return `${n} ms`;
  return `${(n / 1000).toFixed(2)} s`;
}
