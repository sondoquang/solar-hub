export default function ErrorState({ message = "Đã xảy ra lỗi", onRetry }) {
  return (
    <div className="flex flex-col items-center gap-3 py-10 text-center">
      <p className="text-danger">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded bg-brand px-4 py-2 font-medium text-ink"
        >
          Thử lại
        </button>
      )}
    </div>
  );
}
