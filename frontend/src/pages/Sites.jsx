import { Button, Input, Modal, Popconfirm, Select } from "antd";
import {
  ClipboardCheck,
  ExternalLink,
  Globe,
  NotebookPen,
  Pencil,
  Play,
  Plus,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";

import { hostingLabel, useHostings } from "../api/hostings.js";
import {
  useCreateSite,
  useDeleteSite,
  useImportSites,
  useSites,
  useSiteStats,
  useTestConnection,
  useTestConnections,
  useUpdateSite,
} from "../api/sites.js";
import DataTable from "../components/DataTable.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ErrorState from "../components/ErrorState.jsx";
import SiteImport from "../components/SiteImport.jsx";
import SiteNotesModal from "../components/SiteNotesModal.jsx";
import SiteRegisterForm from "../components/SiteRegisterForm.jsx";
import SiteStats from "../components/SiteStats.jsx";
import StatusDot from "../components/StatusDot.jsx";
import { formatDate } from "../lib/format.js";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

export default function Sites() {
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null); // site being edited, or null
  const [notesSite, setNotesSite] = useState(null); // site whose notes are open, or null
  const [selectedKeys, setSelectedKeys] = useState([]);
  const [ordering, setOrdering] = useState(null); // null | "name" | "-name"
  const [hostingFilter, setHostingFilter] = useState("all"); // "all" | "none" | hosting id
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

  // Server-side params: any change re-queries the backend (page / size / sort / filter / search).
  const { data, isLoading, isFetching, isError, refetch } = useSites({
    page,
    page_size: pageSize,
    ordering: ordering ?? undefined,
    hosting: hostingFilter === "all" ? undefined : hostingFilter,
    search: search || undefined,
  });
  const { data: stats, isLoading: statsLoading } = useSiteStats();
  // Large page so the filter dropdown lists every hosting, not just page 1.
  const { data: hostingData } = useHostings({ page_size: 100 });

  const createSite = useCreateSite();
  const updateSite = useUpdateSite();
  const deleteSite = useDeleteSite();
  const testConn = useTestConnection();
  const bulkTest = useTestConnections();
  const importSites = useImportSites();

  const sites = data?.results ?? [];
  const total = data?.count ?? 0;
  const hostings = hostingData?.results ?? [];
  const testingId = testConn.isPending ? testConn.variables : null;

  const closeForm = () => {
    setShowForm(false);
    setEditing(null);
  };

  const handleSubmit = async (values, { onSuccess }) => {
    try {
      if (editing) {
        await updateSite.mutateAsync({ id: editing.id, ...values });
        toast.success("Đã cập nhật site.");
      } else {
        await createSite.mutateAsync(values);
        toast.success("Đã đăng ký site.");
      }
      closeForm();
      onSuccess?.();
    } catch {
      toast.error("Lưu thất bại. Kiểm tra lại dữ liệu.");
    }
  };

  const handleTest = async (site) => {
    try {
      const res = await testConn.mutateAsync(site.id);
      res.ok ? toast.success(res.detail) : toast.error(res.detail);
    } catch {
      toast.error("Không kết nối được site.");
    }
  };

  const handleBulkTest = async () => {
    if (selectedKeys.length === 0) return;
    try {
      const { results } = await bulkTest.mutateAsync(selectedKeys);
      const up = results.filter((r) => r.ok).length;
      toast.success(`Đã kiểm tra ${results.length} site, ${up} hoạt động.`);
    } catch {
      toast.error("Kiểm tra hàng loạt thất bại.");
    }
  };

  const handleDelete = async (site) => {
    try {
      await deleteSite.mutateAsync(site.id);
      setSelectedKeys((prev) => prev.filter((id) => id !== site.id));
      toast.success("Đã xóa site.");
    } catch {
      toast.error("Xóa thất bại.");
    }
  };

  const handleImport = async ({ file, hosting }) => {
    try {
      const res = await importSites.mutateAsync({ file, hosting });
      if (res.errors?.length) {
        toast(`Tạo ${res.created} site, ${res.errors.length} dòng lỗi.`, { icon: "⚠️" });
      } else {
        toast.success(`Đã import ${res.created} site.`);
      }
    } catch {
      toast.error("Import thất bại.");
    }
  };

  const openEdit = (site) => {
    setEditing(site);
    setShowForm(true);
  };

  // antd drives page / page-size / sort changes through onChange. A page-size or
  // sort change resets to page 1; otherwise honour the requested page.
  const handleTableChange = (pagination, _filters, sorter) => {
    const nextOrdering = !sorter?.order ? null : sorter.order === "ascend" ? "name" : "-name";
    const resets = pagination.pageSize !== pageSize || nextOrdering !== ordering;
    setOrdering(nextOrdering);
    setPageSize(pagination.pageSize);
    setPage(resets ? 1 : pagination.current);
  };

  const columns = [
    {
      key: "name",
      dataIndex: "name",
      title: "Tên website",
      width: 240,
      sorter: true,
      sortOrder: ordering === "name" ? "ascend" : ordering === "-name" ? "descend" : null,
      render: (name) => (
        <span className="inline-flex items-center gap-2.5 font-medium">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-50 text-blue-500">
            <Globe size={15} />
          </span>
          <span className="truncate">{name}</span>
        </span>
      ),
    },
    {
      key: "base_url",
      dataIndex: "base_url",
      title: "Base URL",
      width: 260,
      render: (url) => (
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 text-blue-600 hover:underline"
        >
          <span className="truncate">{url}</span>
          <ExternalLink size={14} className="shrink-0 text-slate-400" />
        </a>
      ),
    },
    {
      key: "hosting_name",
      dataIndex: "hosting_name",
      title: "Hosting",
      width: 160,
      render: (v) => <span className="text-muted">{v || "—"}</span>,
    },
    {
      key: "status",
      dataIndex: "status",
      title: "Trạng thái",
      width: 150,
      ellipsis: false,
      render: (status) => <StatusDot status={status} />,
    },
    {
      key: "last_checked_at",
      dataIndex: "last_checked_at",
      title: "Kiểm tra lúc",
      width: 170,
      render: (v) => <span className="tabular-nums text-muted">{formatDate(v)}</span>,
    },
    {
      key: "actions",
      title: "Hành động",
      width: 360,
      align: "right",
      hideable: false,
      ellipsis: false,
      render: (_, site) => {
        const testing = testingId === site.id;
        return (
          <div className="flex items-center justify-end gap-1">
            <Button
              size="small"
              icon={<Play size={14} />}
              loading={testing}
              onClick={() => handleTest(site)}
            >
              {testing ? "Đang kiểm tra…" : "Test"}
            </Button>
            <Button
              size="small"
              icon={<NotebookPen size={14} />}
              onClick={() => setNotesSite(site)}
            >
              Ghi chú
            </Button>
            <Button size="small" icon={<Pencil size={14} />} onClick={() => openEdit(site)}>
              Sửa
            </Button>
            <Popconfirm
              title="Xóa website này?"
              description="Site sẽ bị gỡ khỏi hệ thống Hub."
              okText="Xóa"
              cancelText="Hủy"
              onConfirm={() => handleDelete(site)}
            >
              <Button size="small" danger icon={<Trash2 size={14} />}>
                Xóa
              </Button>
            </Popconfirm>
          </div>
        );
      },
    },
  ];

  const filterActive = hostingFilter !== "all" || search !== "";

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-1.5">
        <div>
          <h1 className="font-display text-2xl font-bold">Quản lý website</h1>
          <p className="mt-1 text-sm text-muted">
            Quản lý danh sách website và trạng thái hoạt động
          </p>
        </div>
        <div className="flex gap-1">
          <Button
            icon={<ClipboardCheck size={16} />}
            onClick={handleBulkTest}
            disabled={selectedKeys.length === 0}
            loading={bulkTest.isPending}
          >
            {bulkTest.isPending
              ? "Đang kiểm tra…"
              : `Kiểm tra đã chọn (${selectedKeys.length})`}
          </Button>
          <Button
            type="primary"
            icon={<Plus size={16} />}
            onClick={() => {
              setEditing(null);
              setShowForm(true);
            }}
          >
            Thêm website
          </Button>
        </div>
      </div>

      <div className="mb-2.5">
        <SiteImport onImport={handleImport} pending={importSites.isPending} hostings={hostings} />
      </div>

      <div className="mb-3">
        <SiteStats counts={stats ?? {}} loading={statsLoading} />
      </div>

      {hostings.length > 0 && (
        <div className="mb-2.5 flex items-center gap-2">
          <span className="text-sm text-muted">Lọc theo hosting:</span>
          <Select
            value={hostingFilter}
            onChange={(v) => {
              setHostingFilter(v);
              setPage(1);
            }}
            className="min-w-52"
            options={[
              { value: "all", label: "Tất cả hosting" },
              { value: "none", label: "Chưa gán hosting" },
              ...hostings.map((h) => ({ value: h.id, label: hostingLabel(h) })),
            ]}
          />
        </div>
      )}

      {isError ? (
        <ErrorState message="Không tải được danh sách site" onRetry={refetch} />
      ) : (
        <div className="rounded bg-white p-2.5 shadow-card">
          <DataTable
            columns={columns}
            dataSource={sites}
            rowKey="id"
            size="middle"
            loading={isLoading || isFetching}
            onRefresh={refetch}
            refreshing={isFetching}
            searchSlot={
              <Input.Search
                allowClear
                placeholder="Tìm theo tên hoặc URL…"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="w-60"
              />
            }
            rowSelection={{
              selectedRowKeys: selectedKeys,
              onChange: setSelectedKeys,
              preserveSelectedRowKeys: true,
            }}
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
                  title={filterActive ? "Không có website phù hợp" : "Chưa có website"}
                  hint={
                    filterActive
                      ? "Thử đổi từ khóa tìm kiếm hoặc bộ lọc hosting."
                      : "Bấm “Thêm website” hoặc import Excel."
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
        title={editing ? "Sửa website" : "Thêm website"}
      >
        <SiteRegisterForm
          mode={editing ? "edit" : "create"}
          defaultValues={editing ?? undefined}
          hostings={hostings}
          onSubmit={handleSubmit}
          onCancel={closeForm}
          pending={createSite.isPending || updateSite.isPending}
        />
      </Modal>

      <SiteNotesModal
        site={notesSite}
        open={!!notesSite}
        onClose={() => setNotesSite(null)}
      />
    </section>
  );
}
