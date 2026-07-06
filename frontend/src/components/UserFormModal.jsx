import { Form, Input, Modal, Select } from "antd";
import { useEffect } from "react";
import toast from "react-hot-toast";

import { useCreateUser, useUpdateUser } from "../api/users.js";
import { useGroups } from "../api/groups.js";

// Shared create/edit modal for a user. Create shows username + password; edit
// hides both (username is immutable, password is reset via SetPasswordModal).
// Groups come from the groups list; the backend validates password strength
// and username uniqueness, surfaced here as per-field errors.
export default function UserFormModal({ open, onClose, mode = "create", user = null }) {
  const isEdit = mode === "edit";
  const [form] = Form.useForm();
  const createUser = useCreateUser();
  const updateUser = useUpdateUser();
  const { data: groupsData } = useGroups();

  const groupOptions = (groupsData?.results ?? []).map((g) => ({
    value: g.id,
    label: g.name,
  }));

  useEffect(() => {
    if (!open) return;
    form.resetFields();
    if (isEdit && user) {
      form.setFieldsValue({
        email: user.email ?? "",
        full_name: user.full_name === user.username ? "" : user.full_name ?? "",
        group_ids: (user.groups ?? []).map((g) => g.id),
      });
    }
  }, [open, isEdit, user, form]);

  const pending = createUser.isPending || updateUser.isPending;

  const applyServerErrors = (e) => {
    const data = e?.response?.data;
    if (data && typeof data === "object") {
      const fields = Object.entries(data)
        .filter(([name]) => ["username", "password", "email", "full_name"].includes(name))
        .map(([name, errs]) => ({
          name,
          errors: Array.isArray(errs) ? errs : [String(errs)],
        }));
      if (fields.length) {
        form.setFields(fields);
        return true;
      }
    }
    return false;
  };

  const submit = async () => {
    let values;
    try {
      values = await form.validateFields();
    } catch {
      return; // client-side validation errors already shown
    }
    const mutation = isEdit ? updateUser : createUser;
    const payload = isEdit ? { id: user.id, ...values } : values;
    mutation.mutate(payload, {
      onSuccess: () => {
        toast.success(isEdit ? "Đã cập nhật người dùng." : "Đã tạo người dùng.");
        onClose();
      },
      onError: (e) => {
        if (!applyServerErrors(e)) toast.error("Lưu người dùng thất bại.");
      },
    });
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      onOk={submit}
      okText={isEdit ? "Lưu" : "Tạo người dùng"}
      cancelText="Hủy"
      okButtonProps={{ loading: pending }}
      title={isEdit ? "Sửa người dùng" : "Thêm người dùng"}
      destroyOnClose
    >
      <Form form={form} layout="vertical" className="pt-2" requiredMark={false}>
        {!isEdit && (
          <Form.Item
            name="username"
            label="Tên đăng nhập"
            rules={[{ required: true, message: "Bắt buộc" }]}
          >
            <Input autoFocus placeholder="vd: nhanvien01" autoComplete="off" />
          </Form.Item>
        )}
        {!isEdit && (
          <Form.Item
            name="password"
            label="Mật khẩu"
            rules={[{ required: true, message: "Bắt buộc" }]}
          >
            <Input.Password placeholder="Mật khẩu đăng nhập" autoComplete="new-password" />
          </Form.Item>
        )}
        <Form.Item name="full_name" label="Họ tên">
          <Input placeholder="vd: Nguyễn Văn A" />
        </Form.Item>
        <Form.Item
          name="email"
          label="Email"
          rules={[{ type: "email", message: "Email không hợp lệ" }]}
        >
          <Input placeholder="vd: a@example.com" />
        </Form.Item>
        <Form.Item name="group_ids" label="Nhóm quyền">
          <Select
            mode="multiple"
            allowClear
            placeholder="Chọn nhóm quyền"
            options={groupOptions}
            optionFilterProp="label"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
