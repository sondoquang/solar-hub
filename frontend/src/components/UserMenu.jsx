import { Button, Dropdown, Form, Input, Modal } from "antd";
import { ChevronDown, KeyRound, LogOut, UserCog } from "lucide-react";
import { useState } from "react";
import toast from "react-hot-toast";

import { changePassword, updateProfile } from "../api/auth.js";
import { useAuth } from "../lib/AuthContext.jsx";

function initialsOf(user) {
  if (user?.full_name) {
    return user.full_name
      .split(" ")
      .map((w) => w[0])
      .slice(0, 2)
      .join("")
      .toUpperCase();
  }
  return (user?.username?.[0] ?? "?").toUpperCase();
}

// Modal: edit full name + email of the current user.
function ProfileModal({ open, onClose }) {
  const { user, updateUser } = useAuth();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  async function handleSubmit(values) {
    setSaving(true);
    try {
      const updated = await updateProfile(values);
      updateUser(updated);
      toast.success("Đã cập nhật thông tin.");
      onClose();
    } catch (err) {
      const data = err?.response?.data;
      toast.error(data?.email?.[0] || data?.detail || "Cập nhật thất bại.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Cập nhật thông tin"
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
      afterOpenChange={(o) =>
        o &&
        form.setFieldsValue({
          full_name: user?.full_name ?? "",
          email: user?.email ?? "",
        })
      }
    >
      <Form form={form} layout="vertical" onFinish={handleSubmit} requiredMark={false} className="mt-2">
        <Form.Item label="Tên đăng nhập">
          <Input value={user?.username ?? ""} disabled />
        </Form.Item>
        <Form.Item
          label="Họ và tên"
          name="full_name"
          rules={[{ required: true, message: "Vui lòng nhập họ và tên" }]}
        >
          <Input placeholder="Nhập họ và tên" />
        </Form.Item>
        <Form.Item
          label="Email"
          name="email"
          rules={[{ type: "email", message: "Email không hợp lệ" }]}
        >
          <Input placeholder="Nhập email" />
        </Form.Item>
        <div className="mt-4 flex justify-end gap-2">
          <Button onClick={onClose}>Hủy</Button>
          <Button type="primary" htmlType="submit" loading={saving}>
            Lưu thay đổi
          </Button>
        </div>
      </Form>
    </Modal>
  );
}

// Modal: change password (old + new + confirm).
function PasswordModal({ open, onClose }) {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  async function handleSubmit(values) {
    setSaving(true);
    try {
      await changePassword({
        old_password: values.old_password,
        new_password: values.new_password,
      });
      toast.success("Đã đổi mật khẩu.");
      form.resetFields();
      onClose();
    } catch (err) {
      const data = err?.response?.data;
      toast.error(
        data?.old_password?.[0] ||
          data?.new_password?.[0] ||
          data?.detail ||
          "Đổi mật khẩu thất bại.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title="Đổi mật khẩu"
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnHidden
      afterOpenChange={(o) => o && form.resetFields()}
    >
      <Form form={form} layout="vertical" onFinish={handleSubmit} requiredMark={false} className="mt-2">
        <Form.Item
          label="Mật khẩu hiện tại"
          name="old_password"
          rules={[{ required: true, message: "Vui lòng nhập mật khẩu hiện tại" }]}
        >
          <Input.Password placeholder="Nhập mật khẩu hiện tại" />
        </Form.Item>
        <Form.Item
          label="Mật khẩu mới"
          name="new_password"
          rules={[{ required: true, message: "Vui lòng nhập mật khẩu mới" }]}
        >
          <Input.Password placeholder="Nhập mật khẩu mới" />
        </Form.Item>
        <Form.Item
          label="Xác nhận mật khẩu mới"
          name="confirm"
          dependencies={["new_password"]}
          rules={[
            { required: true, message: "Vui lòng xác nhận mật khẩu mới" },
            ({ getFieldValue }) => ({
              validator(_, value) {
                if (!value || getFieldValue("new_password") === value) {
                  return Promise.resolve();
                }
                return Promise.reject(new Error("Mật khẩu xác nhận không khớp"));
              },
            }),
          ]}
        >
          <Input.Password placeholder="Nhập lại mật khẩu mới" />
        </Form.Item>
        <div className="mt-4 flex justify-end gap-2">
          <Button onClick={onClose}>Hủy</Button>
          <Button type="primary" htmlType="submit" loading={saving}>
            Đổi mật khẩu
          </Button>
        </div>
      </Form>
    </Modal>
  );
}

export default function UserMenu() {
  const { user, logout } = useAuth();
  const [profileOpen, setProfileOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);

  const items = [
    { key: "profile", icon: <UserCog size={16} />, label: "Cập nhật" },
    { key: "password", icon: <KeyRound size={16} />, label: "Đổi mật khẩu" },
    { type: "divider" },
    { key: "logout", icon: <LogOut size={16} />, label: "Đăng xuất", danger: true },
  ];

  function onClick({ key }) {
    if (key === "profile") setProfileOpen(true);
    else if (key === "password") setPasswordOpen(true);
    else if (key === "logout") logout();
  }

  return (
    <>
      <Dropdown
        menu={{ items, onClick }}
        trigger={["click"]}
        placement="bottomRight"
        arrow
      >
        <button
          type="button"
          className="flex cursor-pointer items-center gap-1.5 rounded-lg border-0 bg-transparent px-1.5 py-1 hover:bg-slate-100"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-200 text-sm font-semibold text-slate-600">
            {initialsOf(user)}
          </span>
          <div className="text-right text-sm leading-tight">
            <p className="mb-1.5 font-semibold">{user?.full_name ?? user?.username ?? "—"}</p>
            <p className="text-xs text-muted">{user?.role ?? "—"}</p>
          </div>
          <ChevronDown size={16} className="text-slate-400" />
        </button>
      </Dropdown>

      <ProfileModal open={profileOpen} onClose={() => setProfileOpen(false)} />
      <PasswordModal open={passwordOpen} onClose={() => setPasswordOpen(false)} />
    </>
  );
}
