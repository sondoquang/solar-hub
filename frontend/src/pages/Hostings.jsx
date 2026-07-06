import { Button, Input, Modal, Popconfirm } from "antd";
import { Pencil, Play, Plus, Server, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";

import {
  useCheckHosting,
  useCreateHosting,
  useDeleteHosting,
  useHostings,
  useImportHostings,
  useUpdateHosting,
} from "../api/hostings.js";
import { useCan } from "../lib/AuthContext.jsx";
import DataTable from "../components/DataTable.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ErrorState from "../components/ErrorState.jsx";
import HostingImport from "../components/HostingImport.jsx";
import HostingRegisterForm from "../components/HostingRegisterForm.jsx";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

// Compact per-hosting health summary: up / down / unknown counts as colored pills.
function HealthSummary({ counts }) {
  const items = [
    { key: "up", label: "Hoạt động", cls: "bg-green-500/15 text-success" },
    { key: "down", label: "Lỗi", cls: "bg-red-500/15 text-danger" },
    { key: "unknown", label: "Chưa rõ", cls: "bg-amber-500/15 text-warning" },
  ];
  return (
    <span className="inline-flex flex-wrap gap-1">
      {items.map(({ key, label, cls }) => (
        <span
          key={key}
          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}
          title={label}
        >
          {counts?.[key] ?? 0} {label}
        </span>
      ))}
    </span>
  );
}

export default function Hostings() {
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [checkingId, setCheckingId] = useState(null);
  const [searchInput, setSearchInput] = useState(""); // raw text in the input
  const [search, setSearch] = useState(""); // debounced term sent to the backend
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  // Debounce typing so we re-query the backend ~once the user pauses, not on
  // every keystroke. A new search always resets to page 1.
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const { data, isLoading, isFetching, isError, refetch } = useHostings({
    page,
    page_size: pageSize,
    search: search || undefined,
  });
  const createHosting = useCreateHosting();
  const updateHosting = useUpdateHosting();
  const deleteHosting = useDeleteHosting();
  const checkHosting = useCheckHosting();
  const importHostings = useImportHostings();
  const can = useCan();
  const canAdd = can("sites.add_hosting");
  const canChange = can("sites.change_hosting");
  const canDelete = can("sites.delete_hosting");

  const hostings = data?.results ?? [];
  const total = data?.count ?? 0;

  const closeForm = () => {
    setShowForm(false);
    setEditing(null);
  };

  const handleSubmit = async (values, { onSuccess }) => {
    try {
      if (editing) {
        await updateHosting.mutateAsync({ id: editing.id, ...values });
        toast.success("Đã cập nhật hosting.");
      } else {
        await createHosting.mutateAsync(values);
        toast.success("Đã tạo hosting.");
      }
      closeForm();
      onSuccess?.();
    } catch {
      toast.error("Lưu thất bại. Kiểm tra lại dữ liệu.");
    }
  };

  const handleCheck = async (hosting) => {
    setCheckingId(hosting.id);
    try {
      const { results } = await checkHosting.mutateAsync(hosting.id);
      const up = results.filter((r) => r.ok).length;
      toast.success(`Đã kiểm tra ${results.length} site, ${up} hoạt động.`);
    } catch {
      toast.error("Kiểm tra hosting thất bại.");
    } finally {
      setCheckingId(null);
    }
  };

  const handleDelete = async (hosting) => {
    try {
      await deleteHosting.mutateAsync(hosting.id);
      toast.success("Đã xóa hosting.");
    } catch {
      toast.error("Xóa thất bại.");
    }
  };

  const handleImport = async ({ file }) => {
    try {
      const res = await importHostings.mutateAsync({ file });
      if (res.errors?.length) {
        toast(`Tạo ${res.created} hosting, ${res.errors.length} dòng lỗi.`, { icon: "⚠️" });
      } else {
        toast.success(`Đã import ${res.created} hosting.`);
      }
    } catch {
      toast.error("Import thất bại.");
    }
  };

  const openEdit = (hosting) => {
    setEditing(hosting);
    setShowForm(true);
  };

  const handleTableChange = (pagination) => {
    const resets = pagination.pageSize !== pageSize;
    setPageSize(pagination.pageSize);
    setPage(resets ? 1 : pagination.current);
  };

  const columns = [
    {
      key: "name",
      dataIndex: "name",
      title: "Hosting",
      width: 220,
      render: (name) => (
        <span className="inline-flex items-center gap-2.5 font-medium">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-500/15 text-info">
            <Server size={15} />
          </span>
          <span className="truncate">{name}</span>
        </span>
      ),
    },
    {
      key: "provider",
      dataIndex: "provider",
      title: "Nhà cung cấp",
      width: 160,
      render: (v) => <span className="text-muted">{v || "—"}</span>,
    },
    {
      key: "account_username",
      dataIndex: "account_username",
      title: "Tài khoản",
      width: 160,
      render: (v) => <span className="text-muted">{v || "—"}</span>,
    },
    {
      key: "site_count",
      dataIndex: "site_count",
      title: "Số site",
      width: 110,
      render: (v) => <span className="tabular-nums">{v}</span>,
    },
    {
      key: "check_concurrency",
      dataIndex: "check_concurrency",
      title: "Đồng thời",
      width: 120,
      render: (v) => <span className="tabular-nums">{v}</span>,
    },
    {
      key: "status_counts",
      dataIndex: "status_counts",
      title: "Sức khỏe",
      width: 240,
      ellipsis: false,
      render: (counts) => <HealthSummary counts={counts} />,
    },
    {
      key: "actions",
      title: "Hành động",
      width: 280,
      align: "right",
      hideable: false,
      ellipsis: false,
      render: (_, h) => {
        const checking = checkingId === h.id;
        return (
          <div className="flex items-center justify-end gap-1">
            {canChange && (
              <Button
                size="small"
                icon={<Play size={14} />}
                loading={checking}
                disabled={h.site_count === 0}
                onClick={() => handleCheck(h)}
              >
                {checking ? "Đang kiểm tra…" : "Check ngay"}
              </Button>
            )}
            {canChange && (
              <Button size="small" icon={<Pencil size={14} />} onClick={() => openEdit(h)}>
                Sửa
              </Button>
            )}
            {canDelete && (
              <Popconfirm
                title="Xóa hosting này?"
                description="Các site sẽ được gỡ khỏi nhóm nhưng không bị xóa."
                okText="Xóa"
                cancelText="Hủy"
                onConfirm={() => handleDelete(h)}
              >
                <Button size="small" danger icon={<Trash2 size={14} />}>
                  Xóa
                </Button>
              </Popconfirm>
            )}
          </div>
        );
      },
    },
  ];

  return (
    <section className="pt-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-1.5">
        <div>
          <h1 className="font-display text-2xl font-bold">Quản lý hosting</h1>
        </div>
        {canAdd && (
          <Button
            type="primary"
            icon={<Plus size={16} />}
            onClick={() => {
              setEditing(null);
              setShowForm(true);
            }}
          >
            Thêm hosting
          </Button>
        )}
      </div>

      {canAdd && (
        <div className="mb-2.5">
          <HostingImport onImport={handleImport} pending={importHostings.isPending} />
        </div>
      )}

      {isError ? (
        <ErrorState message="Không tải được danh sách hosting" onRetry={refetch} />
      ) : (
        <div className="rounded bg-surface-raised p-2.5 border border-border">
          <DataTable
            columns={columns}
            dataSource={hostings}
            rowKey="id"
            size="middle"
            loading={isLoading || isFetching}
            onRefresh={refetch}
            refreshing={isFetching}
            searchSlot={
              <Input.Search
                allowClear
                placeholder="Tìm theo tên / NCC / tài khoản…"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="w-60"
              />
            }
            onChange={handleTableChange}
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              pageSizeOptions: PAGE_SIZE_OPTIONS,
              showTotal: (t, range) => `${range[0]}–${range[1]} trên ${t}`,
            }}
            locale={{
              emptyText: (
                <EmptyState
                  title={search ? "Không có hosting phù hợp" : "Chưa có hosting"}
                  hint={
                    search
                      ? "Thử đổi từ khóa tìm kiếm."
                      : "Bấm “Thêm hosting” hoặc import Excel."
                  }
                />
              ),
            }}
          />
        </div>
      )}

      <Modal
        open={showForm}
        onCancel={closeForm}
        footer={null}
        destroyOnHidden
        title={editing ? "Sửa hosting" : "Thêm hosting"}
      >
        <HostingRegisterForm
          defaultValues={editing ?? undefined}
          onSubmit={handleSubmit}
          onCancel={closeForm}
          pending={createHosting.isPending || updateHosting.isPending}
        />
      </Modal>
    </section>
  );
}
