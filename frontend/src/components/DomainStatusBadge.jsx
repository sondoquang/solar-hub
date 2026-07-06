// Shared presentational badges for the domain-info screens. Colours reuse the
// StatusDot / HealthStatusBadge conventions so every status screen reads the same.

// Per-check lifecycle status (whois/dns/ssl/blacklist/gindex_status).
const CHECK_MAP = {
  ok: { bg: "bg-green-500/15", text: "text-success", label: "Thành công" },
  partial: { bg: "bg-amber-500/15", text: "text-warning", label: "Thiếu một phần" },
  pending: { bg: "bg-blue-500/15", text: "text-info", label: "Đang kiểm tra…" },
  error: { bg: "bg-red-500/15", text: "text-danger", label: "Lỗi" },
  unsupported: { bg: "bg-overlay/5", text: "text-muted", label: "Chưa hỗ trợ" },
  skipped: { bg: "bg-overlay/5", text: "text-muted", label: "Bỏ qua" },
};

// Blacklist roll-up verdict (blacklist_verdict).
const VERDICT_MAP = {
  clean: { bg: "bg-green-500/15", text: "text-success", label: "Sạch" },
  listed: { bg: "bg-red-500/15", text: "text-danger", label: "Bị liệt kê" },
  unknown: { bg: "bg-amber-500/15", text: "text-warning", label: "Không xác định" },
};

function Pill({ bg, text, label }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 ${bg}`}
      aria-label={`Trạng thái: ${label}`}
    >
      <span className={`text-xs font-medium ${text}`}>{label}</span>
    </span>
  );
}

export function CheckStatusBadge({ status, label }) {
  const cfg = CHECK_MAP[status] || CHECK_MAP.skipped;
  return <Pill {...cfg} label={label || cfg.label} />;
}

export function BlacklistBadge({ verdict, label }) {
  const cfg = VERDICT_MAP[verdict] || VERDICT_MAP.unknown;
  return <Pill {...cfg} label={label || cfg.label} />;
}

// Expiry countdown for WHOIS/SSL. Thresholds: >30d green, 8–30d amber, ≤7d red,
// past = red "Đã hết hạn". null → a muted dash (never checked / unsupported).
export function ExpiryBadge({ days }) {
  if (days == null) return <span className="text-muted">—</span>;
  let cfg;
  let label;
  if (days < 0) {
    cfg = { bg: "bg-red-500/15", text: "text-danger" };
    label = `Đã hết hạn ${Math.abs(days)} ngày`;
  } else if (days <= 7) {
    cfg = { bg: "bg-red-500/15", text: "text-danger" };
    label = `Còn ${days} ngày`;
  } else if (days <= 30) {
    cfg = { bg: "bg-amber-500/15", text: "text-warning" };
    label = `Còn ${days} ngày`;
  } else {
    cfg = { bg: "bg-green-500/15", text: "text-success" };
    label = `Còn ${days} ngày`;
  }
  return <Pill {...cfg} label={label} />;
}
