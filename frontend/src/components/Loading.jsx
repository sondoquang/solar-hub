export default function Loading({ label = "Đang tải…" }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center justify-center gap-3 py-10 text-muted"
    >
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-muted border-t-brand" />
      <span>{label}</span>
    </div>
  );
}
