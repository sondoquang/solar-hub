import { Button, Modal, Popconfirm } from "antd";
import { CheckCircle2, XCircle } from "lucide-react";
import toast from "react-hot-toast";

import { useCancelOrder, useMarkOrderPaid } from "../api/orders.js";
import OrderDetailContent from "./OrderDetailContent.jsx";

// Detail view for a SINGLE Sapo order. The Sapo screen has no multi-select, so
// (unlike the WooCommerce OrderDetailModal carousel) this shows exactly one
// order: the body is the shared OrderDetailContent and the footer carries the
// same two Sapo actions as the table row — Đánh dấu đã thanh toán / Hủy đơn —
// so an admin can act right after reviewing. Each is shown only when it applies
// (mirrors the row actions and the backend rules), pushes the change to Sapo,
// and on success closes the modal; useMarkOrderPaid/useCancelOrder invalidate
// ["orders"] so the just-paid/cancelled order leaves the list.

// Non-terminal statuses can be cancelled (mirrors backend CANCELLABLE_STATUSES).
const CANCELLABLE = new Set(["pending", "processing", "on-hold"]);
const canCancel = (o) => !!o && CANCELLABLE.has(o.status);
const canMarkPaid = (o) => !!o && o.payment_status !== "paid" && o.status !== "cancelled";

export default function SapoOrderDetailModal({ order, open, onClose }) {
  const markPaid = useMarkOrderPaid();
  const cancelOrder = useCancelOrder();

  const handlePaid = () =>
    markPaid.mutate(order.id, {
      onSuccess: () => {
        toast.success(`Đã đánh dấu thanh toán đơn #${order.number}.`);
        onClose();
      },
      onError: (err) =>
        toast.error(err?.response?.data?.detail || "Đánh dấu thanh toán thất bại."),
    });

  const handleCancel = () =>
    cancelOrder.mutate(order.id, {
      onSuccess: () => {
        toast.success(`Đã hủy đơn #${order.number}.`);
        onClose();
      },
      onError: (err) => toast.error(err?.response?.data?.detail || "Hủy đơn thất bại."),
    });

  const paid = canMarkPaid(order);
  const cancel = canCancel(order);

  const footer = (
    // Gap 6px giữa các nút — đồng nhất khoảng cách button toàn hệ thống.
    <div className="flex justify-end gap-1.5">
      <Button key="close" onClick={onClose}>
        Đóng
      </Button>
      {paid && (
        <Popconfirm
          key="paid"
          title="Đánh dấu đã thanh toán?"
          description="Ghi nhận thanh toán đủ cho đơn này trên Sapo."
          okText="Xác nhận"
          cancelText="Đóng"
          okButtonProps={{ loading: markPaid.isPending }}
          onConfirm={handlePaid}
        >
          <Button
            type="primary"
            icon={<CheckCircle2 size={15} />}
            loading={markPaid.isPending}
          >
            Đánh dấu đã thanh toán
          </Button>
        </Popconfirm>
      )}
      {cancel && (
        <Popconfirm
          key="cancel"
          title="Hủy đơn này?"
          description="Đơn sẽ được hủy trên Sapo và không thể hoàn tác."
          okText="Xác nhận hủy"
          cancelText="Đóng"
          okButtonProps={{ danger: true, loading: cancelOrder.isPending }}
          onConfirm={handleCancel}
        >
          <Button danger icon={<XCircle size={15} />} loading={cancelOrder.isPending}>
            Hủy đơn
          </Button>
        </Popconfirm>
      )}
    </div>
  );

  return (
    <Modal open={open} onCancel={onClose} footer={footer} title="Chi tiết đơn Sapo" width={640}>
      {order && (
        <div className="mt-2">
          <OrderDetailContent order={order} />
        </div>
      )}
    </Modal>
  );
}
