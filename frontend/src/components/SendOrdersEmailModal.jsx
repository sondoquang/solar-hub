import { Input, Modal } from "antd";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";

import { useSendOrdersEmail } from "../api/orders.js";

// Light client-side check so the "Gửi" button only enables for a plausible
// address; the backend re-validates and is the source of truth.
const isEmail = (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim());

// Manual send: email the selected orders (HTML body + PDF attachment, built
// server-side from the saved SMTP config) to one address the user types.
export default function SendOrdersEmailModal({ open, orderIds = [], onClose, onSent }) {
  const [email, setEmail] = useState("");
  const send = useSendOrdersEmail();

  // Clear the field each time the modal opens.
  useEffect(() => {
    if (open) setEmail("");
  }, [open]);

  const submit = () => {
    const recipient = email.trim();
    if (!isEmail(recipient)) {
      toast.error("Email người nhận không hợp lệ.");
      return;
    }
    send.mutate(
      { recipient, ids: orderIds },
      {
        onSuccess: (res) => {
          toast.success(`Đã gửi ${res?.sent ?? orderIds.length} đơn tới ${res?.recipient}.`);
          onSent?.();
          onClose();
        },
        onError: (e) =>
          toast.error(e?.response?.data?.detail || "Gửi email thất bại."),
      },
    );
  };

  return (
    <Modal
      open={open}
      title={`Gửi ${orderIds.length} đơn hàng qua email`}
      okText="Gửi"
      cancelText="Hủy"
      confirmLoading={send.isPending}
      okButtonProps={{ disabled: !isEmail(email) }}
      onOk={submit}
      onCancel={onClose}
      destroyOnClose
    >
      <p className="mb-2 text-sm text-muted">
        Email gồm thông tin chi tiết các đơn (dạng HTML) và file PDF đính kèm —
        mỗi trang là một đơn của khách. Dùng tài khoản SMTP đã cấu hình trong
        Cài đặt hệ thống.
      </p>
      <label className="mb-1 block text-sm font-medium">Email người nhận</label>
      <Input
        type="email"
        autoFocus
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        onPressEnter={submit}
        placeholder="nguoinhan@example.com"
      />
    </Modal>
  );
}
