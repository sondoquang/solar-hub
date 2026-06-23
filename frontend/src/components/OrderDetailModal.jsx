import { Button, Modal, Popconfirm } from "antd";
import { ChevronLeft, ChevronRight, FileDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import toast from "react-hot-toast";

import { exportOrdersPdf, useCancelOrder, useCompleteOrder } from "../api/orders.js";
import OrderDetailContent from "./OrderDetailContent.jsx";

// The modal shows orders one at a time; with more than one selected it becomes a
// carousel navigated by Prev/Next buttons, dot indicators, the ←/→ keys, or the
// mouse wheel. A single order hides all navigation (the per-row "Xem chi tiết").

const WHEEL_THROTTLE_MS = 350;

export default function OrderDetailModal({ orders, open, onClose }) {
  const list = orders ?? [];
  const [index, setIndex] = useState(0);
  // Slide direction of the last move (1 = forward, -1 = backward) so the content
  // animates in from the matching side.
  const [direction, setDirection] = useState(1);
  const completeOrder = useCompleteOrder();
  const cancelOrder = useCancelOrder();
  const [exporting, setExporting] = useState(false);
  const lastWheelRef = useRef(0);

  // Reset to the first order whenever the modal (re)opens.
  useEffect(() => {
    if (open) {
      setIndex(0);
      setDirection(1);
    }
  }, [open]);

  const count = list.length;
  // Clamp in case the order list shrinks underneath us.
  const safeIndex = Math.min(index, Math.max(count - 1, 0));
  const current = list[safeIndex];
  const isCarousel = count > 1;

  const goTo = (next) => {
    const clamped = Math.min(Math.max(next, 0), count - 1);
    setDirection(clamped >= safeIndex ? 1 : -1);
    setIndex(clamped);
  };
  const goPrev = () => goTo(safeIndex - 1);
  const goNext = () => goTo(safeIndex + 1);

  // Arrow-key navigation while the carousel is open.
  useEffect(() => {
    if (!open || !isCarousel) return undefined;
    const onKey = (e) => {
      if (e.key === "ArrowLeft") goPrev();
      else if (e.key === "ArrowRight") goNext();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // safeIndex/count drive the clamp inside goPrev/goNext.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, isCarousel, safeIndex, count]);

  // Mouse-wheel navigation, throttled so one flick moves one order (and so it
  // doesn't fight scrolling a long order's content).
  const handleWheel = (e) => {
    if (!isCarousel) return;
    const now = e.timeStamp;
    if (now - lastWheelRef.current < WHEEL_THROTTLE_MS) return;
    if (Math.abs(e.deltaY) < 8) return;
    lastWheelRef.current = now;
    if (e.deltaY > 0) goNext();
    else goPrev();
  };

  // Only a processing order can be completed (matches the backend rule).
  const canComplete = current?.status === "processing";
  // Non-terminal orders can be cancelled (matches CANCELLABLE_STATUSES backend).
  const canCancel = ["pending", "processing", "on-hold"].includes(current?.status);

  // Export the order being viewed to a PDF ("view xong xuất file").
  const handleExport = async () => {
    if (!current) return;
    setExporting(true);
    try {
      await exportOrdersPdf({ ids: [current.id] });
      toast.success("Đã xuất PDF đơn hàng.");
    } catch {
      toast.error("Xuất PDF thất bại.");
    } finally {
      setExporting(false);
    }
  };

  const handleComplete = async () => {
    try {
      await completeOrder.mutateAsync(current.id);
      toast.success("Đã đánh dấu hoàn thành.");
      // Move to the next order if there is one, otherwise close.
      if (safeIndex < count - 1) goNext();
      else onClose();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Cập nhật thất bại.");
    }
  };

  const handleCancel = async () => {
    try {
      await cancelOrder.mutateAsync(current.id);
      toast.success("Đã hủy đơn hàng.");
      // Move to the next order if there is one, otherwise close.
      if (safeIndex < count - 1) goNext();
      else onClose();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Hủy đơn thất bại.");
    }
  };

  const title = (
    <div className="flex items-center gap-2">
      <span>Chi tiết đơn hàng</span>
      {isCarousel && (
        <span
          key={safeIndex}
          className="animate-order-next rounded-full bg-blue-500/15 px-2.5 py-0.5 text-xs font-semibold text-blue-300"
        >
          Đơn {safeIndex + 1}/{count}
        </span>
      )}
    </div>
  );

  const footer = (
    // Gap 6px giữa các nút (mặc định antd là 8px) — đồng nhất khoảng cách button toàn hệ thống.
    <div className="flex justify-end gap-1.5">
      <Button key="close" onClick={onClose}>
        Đóng
      </Button>
      <Button
        key="export"
        icon={<FileDown size={15} />}
        loading={exporting}
        onClick={handleExport}
      >
        Xuất PDF
      </Button>
      {canCancel && (
        <Popconfirm
          key="cancel"
          title="Hủy đơn hàng này?"
          description="Đơn sẽ được hủy trên WooCommerce và không thể hoàn tác."
          okText="Hủy đơn"
          cancelText="Không"
          okButtonProps={{ danger: true, loading: cancelOrder.isPending }}
          onConfirm={handleCancel}
        >
          <Button danger loading={cancelOrder.isPending}>
            Hủy đơn
          </Button>
        </Popconfirm>
      )}
      {canComplete && (
        <Button
          key="complete"
          type="primary"
          loading={completeOrder.isPending}
          onClick={handleComplete}
        >
          Đánh dấu hoàn thành
        </Button>
      )}
    </div>
  );

  return (
    <Modal open={open} onCancel={onClose} footer={footer} title={title} width={640}>
      {current && (
        <div className="mt-2 space-y-3" onWheel={handleWheel}>
          {isCarousel && (
            <div className="flex items-center justify-between gap-2 rounded-lg bg-surface-muted px-2 py-1.5">
              <Button
                type="text"
                icon={<ChevronLeft size={16} />}
                onClick={goPrev}
                disabled={safeIndex === 0}
              >
                Trước
              </Button>
              <div className="flex items-center gap-1.5">
                {list.map((o, i) => (
                  <button
                    key={o.id}
                    type="button"
                    aria-label={`Đơn ${i + 1}`}
                    aria-current={i === safeIndex}
                    onClick={() => goTo(i)}
                    className={`rounded-full transition-all duration-200 ${
                      i === safeIndex
                        ? "h-2 w-5 bg-blue-500"
                        : "h-2 w-2 bg-white/25 hover:scale-125 hover:bg-white/50"
                    }`}
                  />
                ))}
              </div>
              <Button type="text" onClick={goNext} disabled={safeIndex === count - 1}>
                Sau
                <ChevronRight size={16} />
              </Button>
            </div>
          )}

          <div key={safeIndex} className={direction >= 0 ? "animate-order-next" : "animate-order-prev"}>
            <OrderDetailContent order={current} />
          </div>
        </div>
      )}
    </Modal>
  );
}
