import { Button, Input, Popconfirm, Select, Tag } from "antd";
import { KeyRound, Plus, UserPlus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import { useGroups } from "../api/groups.js";
import { useActivateUser, useDeactivateUser, useUsers } from "../api/users.js";
import DataTable from "../components/DataTable.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ErrorState from "../components/ErrorState.jsx";
import SetPasswordModal from "../components/SetPasswordModal.jsx";
import UserFormModal from "../components/UserFormModal.jsx";
import { formatDate } from "../lib/format.js";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

const STATUS_OPTIONS = [
  { value: "all", label: "Tất cả trạng thái" },
  { value: "true", label: "Đang hoạt động" },
  { value: "false", label: "Đã vô hiệu hóa" },
];

// User management: create login accounts, assign RBAC groups, deactivate
// (never hard-delete — audit FKs survive), and reset passwords.
export default function Users() {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [groupFilter, setGroupFilter] = useState(null);
  const [ordering, setOrdering] = useState("-date_joined");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const [formState, setFormState] = useState({ open: false, mode: "create", user: null });
  const [pwUser, setPwUser] = useState(null);

  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(t);
  }, [searchInput]);

  const params = useMemo(
    () => ({
      search: search || undefined,
      is_active: statusFilter === "all" ? undefined : statusFilter,
      group: groupFilter ?? undefined,
      ordering,
      page,
      page_size: pageSize,
    }),
    [search, statusFilter, groupFilter, ordering, page, pageSize]
  );

  const { data, isLoading, isFetching, isError, refetch } = useUsers(params);
  const { data: groupsData } = useGroups();
  const deactivate = useDeactivateUser();
  const activate = useActivateUser();

  const rows = data?.results ?? [];
  const total = data?.count ?? 0;

  const groupFilterOptions = [
    { value: null, label: "Tất cả nhóm" },
    ...(groupsData?.results ?? []).map((g) => ({ value: g.id, label: g.name })),
  ];

  const handleDeactivate = (user) =>
    deactivate.mutate(user.id, {
      onSuccess: () => toast.success("Đã vô hiệu hóa người dùng."),
      onError: (e) =>
        toast.error(e?.response?.data?.detail || "Vô hiệu hóa thất bại."),
    });

  const handleActivate = (user) =>
    activate.mutate(user.id, {
      onSuccess: () => toast.success("Đã kích hoạt người dùng."),
      onError: () => toast.error("Kích hoạt thất bại."),
    });

  const handleTableChange = (pagination, _filters, sorter) => {
    let next = ordering;
    if (sorter?.order) {
      const prefix = sorter.order === "descend" ? "-" : "";
      next = `${prefix}${sorter.field}`;
    }
    const resets = pagination.pageSize !== pageSize || next !== ordering;
    setOrdering(next);
    setPageSize(pagination.pageSize);
    setPage(resets ? 1 : pagination.current);
  };

  const sortOrder = (field) =>
    ordering === field ? "ascend" : ordering === `-${field}` ? "descend" : null;

  const columns = [
    {
      key: "username",
      dataIndex: "username",
      title: "Tên đăng nhập",
      width: 180,
      sorter: true,
      sortOrder: sortOrder("username"),
      render: (v, r) => (
        <div className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand/15 text-brand">
            <UserPlus size={15} />
          </span>
          <div className="min-w-0">
            <p className="truncate font-medium">{v}</p>
            {r.full_name !== v && (
              <p className="truncate text-xs text-muted">{r.full_name}</p>
            )}
          </div>
        </div>
      ),
    },
    {
      key: "email",
      dataIndex: "email",
      title: "Email",
      width: 200,
      render: (v) => v || <span className="text-muted">—</span>,
    },
    {
      key: "groups",
      title: "Nhóm quyền",
      width: 220,
      ellipsis: false,
      render: (_v, r) =>
        r.is_superuser ? (
          <Tag color="gold">Toàn quyền (superuser)</Tag>
        ) : r.groups?.length ? (
          <span className="flex flex-wrap gap-1">
            {r.groups.map((g) => (
              <Tag key={g.id} className="!m-0">
                {g.name}
              </Tag>
            ))}
          </span>
        ) : (
          <span className="text-muted">—</span>
        ),
    },
    {
      key: "is_active",
      dataIndex: "is_active",
      title: "Trạng thái",
      width: 140,
      ellipsis: false,
      render: (active) =>
        active ? (
          <Tag color="green">Đang hoạt động</Tag>
        ) : (
          <Tag color="red">Đã vô hiệu hóa</Tag>
        ),
    },
    {
      key: "last_login",
      dataIndex: "last_login",
      title: "Đăng nhập gần nhất",
      width: 170,
      sorter: true,
      sortOrder: sortOrder("last_login"),
      render: (v) => (
        <span className="tabular-nums text-muted">
          {v ? formatDate(v) : "Chưa đăng nhập"}
        </span>
      ),
    },
    {
      key: "actions",
      title: "Thao tác",
      width: 240,
      align: "right",
      hideable: false,
      ellipsis: false,
      render: (_v, r) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            type="link"
            size="small"
            onClick={() => setFormState({ open: true, mode: "edit", user: r })}
          >
            Sửa
          </Button>
          <Button
            type="link"
            size="small"
            icon={<KeyRound size={14} />}
            onClick={() => setPwUser(r)}
          >
            Mật khẩu
          </Button>
          {r.is_active ? (
            <Popconfirm
              title="Vô hiệu hóa người dùng?"
              description="Tài khoản sẽ không thể đăng nhập cho tới khi được kích hoạt lại."
              okText="Vô hiệu hóa"
              cancelText="Hủy"
              okButtonProps={{ danger: true }}
              onConfirm={() => handleDeactivate(r)}
            >
              <Button type="link" size="small" danger>
                Vô hiệu hóa
              </Button>
            </Popconfirm>
          ) : (
            <Button type="link" size="small" onClick={() => handleActivate(r)}>
              Kích hoạt
            </Button>
          )}
        </div>
      ),
    },
  ];

  const filterActive = search !== "" || statusFilter !== "all" || groupFilter != null;

  return (
    <section className="pt-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-1.5">
        <h1 className="font-display text-2xl font-bold">Quản lý người dùng</h1>
        <Button
          type="primary"
          icon={<Plus size={16} />}
          onClick={() => setFormState({ open: true, mode: "create", user: null })}
        >
          Thêm người dùng
        </Button>
      </div>

      <div className="mb-2.5 flex flex-wrap items-center gap-2">
        <Select
          value={statusFilter}
          onChange={(v) => {
            setStatusFilter(v);
            setPage(1);
          }}
          options={STATUS_OPTIONS}
          className="min-w-44"
        />
        <Select
          value={groupFilter}
          onChange={(v) => {
            setGroupFilter(v);
            setPage(1);
          }}
          options={groupFilterOptions}
          className="min-w-44"
        />
      </div>

      {isError ? (
        <ErrorState message="Không tải được danh sách người dùng" onRetry={refetch} />
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
                placeholder="Tìm theo tên đăng nhập, email…"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="w-64"
              />
            }
            onChange={handleTableChange}
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              pageSizeOptions: PAGE_SIZE_OPTIONS,
              showTotal: (t, r) => `${r[0]}–${r[1]} trên ${t}`,
            }}
            locale={{
              emptyText: (
                <EmptyState
                  title={filterActive ? "Không có người dùng phù hợp" : "Chưa có người dùng"}
                  hint={
                    filterActive
                      ? "Thử đổi từ khóa hoặc bộ lọc."
                      : "Bấm “Thêm người dùng” để tạo tài khoản đăng nhập đầu tiên."
                  }
                />
              ),
            }}
          />
        </div>
      )}

      <UserFormModal
        open={formState.open}
        mode={formState.mode}
        user={formState.user}
        onClose={() => setFormState((s) => ({ ...s, open: false }))}
      />
      <SetPasswordModal
        open={pwUser != null}
        user={pwUser}
        onClose={() => setPwUser(null)}
      />
    </section>
  );
}
