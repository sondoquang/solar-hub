import { Form, Input, Modal } from "antd";
import { useEffect } from "react";
import toast from "react-hot-toast";

import { useSetUserPassword } from "../api/users.js";

// Admin resets a user's password (no old password needed). Strength is
// validated server-side and surfaced on the password field.
export default function SetPasswordModal({ open, onClose, user = null }) {
  const [form] = Form.useForm();
  const setPassword = useSetUserPassword();

  useEffect(() => {
    if (open) form.resetFields();
  }, [open, form]);

  const submit = async () => {
    let values;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setPassword.mutate(
      { id: user.id, password: values.password },
      {
        onSuccess: () => {
          toast.success("Đã đặt lại mật khẩu.");
          onClose();
        },
        onError: (e) => {
          const errs = e?.response?.data?.password;
          if (errs) {
            form.setFields([
              { name: "password", errors: Array.isArray(errs) ? errs : [String(errs)] },
            ]);
          } else {
            toast.error("Đặt lại mật khẩu thất bại.");
          }
        },
      },
    );
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      onOk={submit}
      okText="Đặt lại mật khẩu"
      cancelText="Hủy"
      okButtonProps={{ loading: setPassword.isPending }}
      title={user ? `Đặt lại mật khẩu — ${user.username}` : "Đặt lại mật khẩu"}
      destroyOnClose
    >
      <Form form={form} layout="vertical" className="pt-2" requiredMark={false}>
        <Form.Item
          name="password"
          label="Mật khẩu mới"
          rules={[{ required: true, message: "Bắt buộc" }]}
        >
          <Input.Password autoFocus placeholder="Mật khẩu mới" autoComplete="new-password" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
