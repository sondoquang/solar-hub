export default function EmptyState({ title = "Chưa có dữ liệu", hint, action }) {
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-center">
      <p className="font-display text-lg">{title}</p>
      {hint && <p className="text-sm text-muted">{hint}</p>}
      {action}
    </div>
  );
}
