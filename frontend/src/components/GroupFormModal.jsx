import { Checkbox, Form, Input, Modal, Skeleton } from "antd";
import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import { useCreateGroup, usePermissionCatalog, useUpdateGroup } from "../api/groups.js";

// Create/edit a permission group. The permission matrix is grouped by module →
// model → action (Vietnamese labels from the backend catalog). Selection state
// is a Set of permission ids; module/model headers offer check-all with an
// indeterminate state. Submit sends { name, permission_ids }.
export default function GroupFormModal({ open, onClose, mode = "create", group = null }) {
  const isEdit = mode === "edit";
  const [form] = Form.useForm();
  const createGroup = useCreateGroup();
  const updateGroup = useUpdateGroup();
  const { data: catalog, isLoading: catalogLoading } = usePermissionCatalog({
    enabled: open,
  });

  const [selected, setSelected] = useState(() => new Set());

  useEffect(() => {
    if (!open) return;
    form.resetFields();
    if (isEdit && group) {
      form.setFieldsValue({ name: group.name });
      setSelected(new Set(group.permission_ids ?? []));
    } else {
      setSelected(new Set());
    }
  }, [open, isEdit, group, form]);

  const pending = createGroup.isPending || updateGroup.isPending;

  // Flat id lists per model / per module for the check-all headers.
  const modelIds = useMemo(() => {
    const map = new Map();
    for (const mod of catalog ?? []) {
      for (const m of mod.models) {
        map.set(`${mod.module}:${m.model}`, m.permissions.map((p) => p.id));
      }
    }
    return map;
  }, [catalog]);

  const moduleIds = useMemo(() => {
    const map = new Map();
    for (const mod of catalog ?? []) {
      map.set(
        mod.module,
        mod.models.flatMap((m) => m.permissions.map((p) => p.id)),
      );
    }
    return map;
  }, [catalog]);

  const toggle = (id) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleMany = (ids, checked) =>
    setSelected((prev) => {
      const next = new Set(prev);
      for (const id of ids) {
        if (checked) next.add(id);
        else next.delete(id);
      }
      return next;
    });

  const groupState = (ids) => {
    const on = ids.filter((id) => selected.has(id)).length;
    return { all: on > 0 && on === ids.length, some: on > 0 && on < ids.length };
  };

  const submit = async () => {
    let values;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const mutation = isEdit ? updateGroup : createGroup;
    const payload = {
      name: values.name,
      permission_ids: [...selected],
      ...(isEdit ? { id: group.id } : {}),
    };
    mutation.mutate(payload, {
      onSuccess: () => {
        toast.success(isEdit ? "Đã cập nhật nhóm." : "Đã tạo nhóm.");
        onClose();
      },
      onError: (e) => {
        const nameErr = e?.response?.data?.name;
        if (nameErr) {
          form.setFields([
            { name: "name", errors: Array.isArray(nameErr) ? nameErr : [String(nameErr)] },
          ]);
        } else {
          toast.error("Lưu nhóm thất bại.");
        }
      },
    });
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      onOk={submit}
      okText={isEdit ? "Lưu" : "Tạo nhóm"}
      cancelText="Hủy"
      okButtonProps={{ loading: pending }}
      title={isEdit ? "Sửa nhóm quyền" : "Thêm nhóm quyền"}
      width={820}
      destroyOnClose
    >
      <Form form={form} layout="vertical" className="pt-2" requiredMark={false}>
        <Form.Item
          name="name"
          label="Tên nhóm"
          rules={[{ required: true, message: "Bắt buộc" }]}
        >
          <Input autoFocus placeholder="vd: Nhân viên kho" />
        </Form.Item>
      </Form>

      <p className="mb-2 text-sm font-medium text-muted">Phân quyền</p>
      {catalogLoading ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : (
        <div className="flex max-h-[52vh] flex-col gap-2 overflow-auto pr-1">
          {(catalog ?? []).map((mod) => {
            const modState = groupState(moduleIds.get(mod.module) ?? []);
            return (
              <div
                key={mod.module}
                className="rounded-lg border border-border bg-surface p-3"
              >
                <Checkbox
                  checked={modState.all}
                  indeterminate={modState.some}
                  onChange={(e) =>
                    toggleMany(moduleIds.get(mod.module) ?? [], e.target.checked)
                  }
                >
                  <span className="font-medium">{mod.label}</span>
                </Checkbox>
                <div className="mt-2 space-y-1.5 pl-6">
                  {mod.models.map((m) => {
                    const ids = modelIds.get(`${mod.module}:${m.model}`) ?? [];
                    const mState = groupState(ids);
                    return (
                      <div
                        key={m.model}
                        className="flex flex-wrap items-center gap-x-4 gap-y-1"
                      >
                        <Checkbox
                          className="w-40"
                          checked={mState.all}
                          indeterminate={mState.some}
                          onChange={(e) => toggleMany(ids, e.target.checked)}
                        >
                          <span className="text-muted">{m.label}</span>
                        </Checkbox>
                        {m.permissions.map((p) => (
                          <Checkbox
                            key={p.id}
                            checked={selected.has(p.id)}
                            onChange={() => toggle(p.id)}
                          >
                            {p.label}
                          </Checkbox>
                        ))}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Modal>
  );
}
