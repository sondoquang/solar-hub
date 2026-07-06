import { Input, Modal, TreeSelect } from "antd";
import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import { useCreateCategory, useProductCategories, useUpdateCategory } from "../api/products.js";

// Descendant ids of `rootId` (including itself) over the flat category list, so
// the parent picker never offers the edited node's own subtree — a category
// cannot become a child of itself or a descendant (mirrors the backend cycle
// guard in services._would_create_cycle for clearer UX).
function subtreeIds(categories, rootId) {
  if (rootId == null) return new Set();
  const childrenByParent = new Map();
  for (const c of categories) {
    if (!childrenByParent.has(c.parent)) childrenByParent.set(c.parent, []);
    childrenByParent.get(c.parent).push(c.id);
  }
  const ids = new Set([rootId]);
  const stack = [rootId];
  while (stack.length) {
    for (const child of childrenByParent.get(stack.pop()) ?? []) {
      if (!ids.has(child)) {
        ids.add(child);
        stack.push(child);
      }
    }
  }
  return ids;
}

// Build the parent TreeSelect data (value = category id) from the flat list,
// omitting `excludeIds`.
function buildParentTree(categories, excludeIds) {
  const byId = new Map();
  for (const c of categories) {
    if (!excludeIds.has(c.id)) byId.set(c.id, { ...c, children: [] });
  }
  const roots = [];
  for (const node of byId.values()) {
    const parent = node.parent != null ? byId.get(node.parent) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  const toNode = (c) => ({
    value: c.id,
    title: c.name,
    children: c.children.length ? c.children.map(toNode) : undefined,
  });
  return roots.map(toNode);
}

// Shared create/edit modal for a Hub category. Used both on the Danh mục page
// (tree management) and inline in the product form ("Tạo danh mục mới").
//   mode          "create" | "edit"
//   category      the row being edited (edit mode): {id, name, slug, parent}
//   presetParentId preselected parent for a create/"add child" (create mode)
//   onCreated     optional (newCategory) => void — the product form uses it to
//                 auto-select the freshly created category.
export default function CategoryFormModal({
  open,
  onClose,
  mode = "create",
  category = null,
  presetParentId = null,
  onCreated,
}) {
  const isEdit = mode === "edit";
  const { data: categories = [] } = useProductCategories();
  const createCat = useCreateCategory();
  const updateCat = useUpdateCategory();

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [parent, setParent] = useState(null);
  const [nameError, setNameError] = useState("");

  // Seed the fields each time the modal opens (or its target changes).
  useEffect(() => {
    if (!open) return;
    setName(isEdit ? category?.name ?? "" : "");
    setSlug(isEdit ? category?.slug ?? "" : "");
    setParent(isEdit ? category?.parent ?? null : presetParentId ?? null);
    setNameError("");
  }, [open, isEdit, category, presetParentId]);

  const excludeIds = useMemo(
    () => (isEdit ? subtreeIds(categories, category?.id) : new Set()),
    [isEdit, categories, category],
  );
  const parentTree = useMemo(
    () => buildParentTree(categories, excludeIds),
    [categories, excludeIds],
  );

  const pending = createCat.isPending || updateCat.isPending;

  const onError = (e) =>
    toast.error(
      e?.response?.data?.name?.[0] ||
        e?.response?.data?.parent?.[0] ||
        "Lưu danh mục thất bại.",
    );

  const submit = () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setNameError("Bắt buộc");
      return;
    }
    const payload = { name: trimmed, slug, parent: parent ?? null };
    if (isEdit) {
      updateCat.mutate(
        { id: category.id, ...payload },
        {
          onSuccess: () => {
            toast.success("Đã cập nhật danh mục.");
            onClose();
          },
          onError,
        },
      );
    } else {
      createCat.mutate(payload, {
        onSuccess: (cat) => {
          toast.success("Đã tạo danh mục.");
          onCreated?.(cat);
          onClose();
        },
        onError,
      });
    }
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      onOk={submit}
      okText={isEdit ? "Lưu" : "Tạo danh mục"}
      cancelText="Hủy"
      okButtonProps={{ loading: pending }}
      title={isEdit ? "Sửa danh mục" : "Thêm danh mục"}
      destroyOnClose
    >
      <div className="grid gap-3 pt-2">
        <div>
          <label className="mb-1 block text-sm font-medium">
            Tên danh mục<span className="ml-0.5 text-danger">*</span>
          </label>
          <Input
            autoFocus
            value={name}
            status={nameError ? "error" : ""}
            placeholder="VD: Pin mặt trời"
            onChange={(e) => {
              setName(e.target.value);
              setNameError("");
            }}
            onPressEnter={submit}
          />
          {nameError && <p className="mt-1 text-xs text-danger">{nameError}</p>}
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium">Danh mục cha</label>
          <TreeSelect
            allowClear
            showSearch
            treeDefaultExpandAll
            treeNodeFilterProp="title"
            className="w-full"
            placeholder="— Không có (danh mục gốc) —"
            value={parent}
            treeData={parentTree}
            onChange={(v) => setParent(v ?? null)}
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium">Slug (tùy chọn)</label>
          <Input
            value={slug}
            placeholder="pin-mat-troi"
            onChange={(e) => setSlug(e.target.value)}
          />
        </div>
      </div>
    </Modal>
  );
}
