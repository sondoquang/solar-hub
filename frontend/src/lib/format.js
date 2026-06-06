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

// Response time: sub-second as "256 ms", ≥1s as "1.25 s".
export function formatResponseTime(ms) {
  const n = Number(ms);
  if (ms == null || Number.isNaN(n)) return "—";
  if (n < 1000) return `${n} ms`;
  return `${(n / 1000).toFixed(2)} s`;
}
