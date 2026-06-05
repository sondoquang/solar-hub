import { Button } from "antd";

export default function ErrorState({ message = "Đã xảy ra lỗi", onRetry }) {
  return (
    <div className="flex flex-col items-center gap-3 py-10 text-center">
      <p className="text-danger">{message}</p>
      {onRetry && (
        <Button type="primary" onClick={onRetry}>
          Thử lại
        </Button>
      )}
    </div>
  );
}
