import { Button, Input, Popconfirm, Tag } from "antd";
import { Plus, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import { useDeleteGroup, useGroups } from "../api/groups.js";
import DataTable from "../components/DataTable.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ErrorState from "../components/ErrorState.jsx";
import GroupFormModal from "../components/GroupFormModal.jsx";

// RBAC group management: each group carries a set of permissions (the matrix in
// GroupFormModal) and users are assigned to groups on the Users page. Deleting
// a group is blocked by the backend while it still has members.
export default function Groups() {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [formState, setFormState] = useState({ open: false, mode: "create", group: null });

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 350);
    return () => clearTimeout(t);
  }, [searchInput]);

  // Groups are few — fetch them all in one page (UI pagination is off).
  const params = useMemo(
    () => ({ search: search || undefined, page_size: 100 }),
    [search]
  );
  const { data, isLoading, isFetching, isError, refetch } = useGroups(params);
  const deleteGroup = useDeleteGroup();

  const rows = data?.results ?? [];

  const handleDelete = (group) =>
    deleteGroup.mutate(group.id, {
      onSuccess: () => toast.success("Đã xóa nhóm."),
      onError: (e) => toast.error(e?.response?.data?.detail || "Xóa nhóm thất bại."),
    });

  const columns = [
    {
      key: "name",
      dataIndex: "name",
      title: "Tên nhóm",
      width: 240,
      render: (v) => (
        <div className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand/15 text-brand">
            <ShieldCheck size={15} />
          </span>
          <span className="truncate font-medium">{v}</span>
        </div>
      ),
    },
    {
      key: "permission_count",
      dataIndex: "permission_count",
      title: "Số quyền",
      width: 120,
      ellipsis: false,
      render: (v) => <Tag>{v} quyền</Tag>,
    },
    {
      key: "user_count",
      dataIndex: "user_count",
      title: "Số người dùng",
      width: 140,
      ellipsis: false,
      render: (v) => <span className="tabular-nums text-muted">{v}</span>,
    },
    {
      key: "actions",
      title: "Thao tác",
      width: 160,
      align: "right",
      hideable: false,
      ellipsis: false,
      render: (_v, r) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            type="link"
            size="small"
            onClick={() => setFormState({ open: true, mode: "edit", group: r })}
          >
            Sửa
          </Button>
          <Popconfirm
            title="Xóa nhóm quyền?"
            description={
              r.user_count > 0
                ? `Nhóm đang có ${r.user_count} người dùng — hãy chuyển họ sang nhóm khác trước.`
                : "Thao tác này không thể hoàn tác."
            }
            okText="Xóa"
            cancelText="Hủy"
            okButtonProps={{ danger: true }}
            onConfirm={() => handleDelete(r)}
          >
            <Button type="link" size="small" danger>
              Xóa
            </Button>
          </Popconfirm>
        </div>
      ),
    },
  ];

  return (
    <section className="pt-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-1.5">
        <h1 className="font-display text-2xl font-bold">Nhóm & phân quyền</h1>
        <Button
          type="primary"
          icon={<Plus size={16} />}
          onClick={() => setFormState({ open: true, mode: "create", group: null })}
        >
          Thêm nhóm
        </Button>
      </div>

      {isError ? (
        <ErrorState message="Không tải được danh sách nhóm" onRetry={refetch} />
      ) : (
        <div className="rounded bg-surface-raised p-2.5 border border-border">
          <DataTable
            columns={columns}
            dataSource={rows}
            rowKey="id"
            size="middle"
            loading={isLoading || isFetching}
            onRefresh={refetch}
            refreshing={isFetching}
            searchSlot={
              <Input.Search
                allowClear
                placeholder="Tìm theo tên nhóm…"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="w-64"
              />
            }
            pagination={false}
            locale={{
              emptyText: (
                <EmptyState
                  title={search ? "Không có nhóm phù hợp" : "Chưa có nhóm quyền"}
                  hint={
                    search
                      ? "Thử đổi từ khóa tìm kiếm."
                      : "Bấm “Thêm nhóm” để tạo nhóm quyền đầu tiên."
                  }
                />
              ),
            }}
          />
        </div>
      )}

      <GroupFormModal
        open={formState.open}
        mode={formState.mode}
        group={formState.group}
        onClose={() => setFormState((s) => ({ ...s, open: false }))}
      />
    </section>
  );
}
