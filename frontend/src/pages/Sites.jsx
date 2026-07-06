import { Button, Input, Modal, Popconfirm, Select, Tag, Tooltip } from "antd";
import {
  ClipboardCheck,
  ExternalLink,
  Globe,
  NotebookPen,
  Pencil,
  Play,
  Plus,
  ShieldCheck,
  Star,
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
import { useCan } from "../lib/AuthContext.jsx";
import DataTable from "../components/DataTable.jsx";
import DomainInfoModal from "../components/DomainInfoModal.jsx";
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
  const [domainSite, setDomainSite] = useState(null); // site whose domain info is open, or null
  const [selectedKeys, setSelectedKeys] = useState([]);
  const [ordering, setOrdering] = useState(null); // null | "name" | "-name"
  const [hostingFilter, setHostingFilter] = useState("all"); // "all" | "none" | hosting id
  const [statusFilter, setStatusFilter] = useState("all"); // "all" | "up" | "down" | "unknown"
  const [platformFilter, setPlatformFilter] = useState("all"); // "all" | "woocommerce" | "sapo"
  const [primaryFilter, setPrimaryFilter] = useState("all"); // "all" | "true" | "false"
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
    status: statusFilter === "all" ? undefined : statusFilter,
    platform: platformFilter === "all" ? undefined : platformFilter,
    is_primary: primaryFilter === "all" ? undefined : primaryFilter,
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
  const can = useCan();
  const canAddSite = can("sites.add_site");
  const canChangeSite = can("sites.change_site");
  const canDeleteSite = can("sites.delete_site");

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

  // Quick toggle from the list — primary sites ("trang chính") are the ones
  // checked first every day, so flagging must not require opening the form.
  const handleTogglePrimary = async (site) => {
    try {
      await updateSite.mutateAsync({ id: site.id, is_primary: !site.is_primary });
      toast.success(
        site.is_primary ? "Đã bỏ đánh dấu trang chính." : "Đã đánh dấu trang chính."
      );
    } catch {
      toast.error("Cập nhật thất bại.");
    }
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
      render: (name, site) => (
        <span className="inline-flex max-w-full items-center gap-1.5 font-medium">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-500/15 text-info">
            <Globe size={15} />
          </span>
          <span className="truncate">{name}</span>
          <Tag
            color={site.platform === "sapo" ? "green" : "purple"}
            className="!mr-0 shrink-0"
          >
            {site.platform === "sapo" ? "Sapo" : "Woo"}
          </Tag>
          {canChangeSite ? (
            <Tooltip
              title={site.is_primary ? "Bỏ đánh dấu trang chính" : "Đánh dấu trang chính"}
            >
              <Button
                type="text"
                size="small"
                aria-label={site.is_primary ? "Bỏ đánh dấu trang chính" : "Đánh dấu trang chính"}
                onClick={() => handleTogglePrimary(site)}
                icon={
                  <Star
                    size={15}
                    className={
                      site.is_primary
                        ? "fill-amber-400 text-amber-400"
                        : "text-muted hover:text-amber-400"
                    }
                  />
                }
              />
            </Tooltip>
          ) : (
            site.is_primary && (
              <Star size={15} className="shrink-0 fill-amber-400 text-amber-400" aria-label="Trang chính" />
            )
          )}
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
          className="inline-flex items-center gap-1.5 text-brand hover:underline"
        >
          <span className="truncate">{url}</span>
          <ExternalLink size={14} className="shrink-0 text-muted" />
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
      width: 440,
      align: "right",
      hideable: false,
      ellipsis: false,
      render: (_, site) => {
        const testing = testingId === site.id;
        return (
          <div className="flex items-center justify-end gap-1">
            {canChangeSite && (
              <Button
                size="small"
                icon={<Play size={14} />}
                loading={testing}
                onClick={() => handleTest(site)}
              >
                {testing ? "Đang kiểm tra…" : "Test"}
              </Button>
            )}
            <Button
              size="small"
              icon={<ShieldCheck size={14} />}
              onClick={() => setDomainSite(site)}
            >
              Tên miền
            </Button>
            <Button
              size="small"
              icon={<NotebookPen size={14} />}
              onClick={() => setNotesSite(site)}
            >
              Ghi chú
            </Button>
            {canChangeSite && (
              <Button size="small" icon={<Pencil size={14} />} onClick={() => openEdit(site)}>
                Sửa
              </Button>
            )}
            {canDeleteSite && (
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
            )}
          </div>
        );
      },
    },
  ];

  const filterActive =
    hostingFilter !== "all" ||
    statusFilter !== "all" ||
    platformFilter !== "all" ||
    primaryFilter !== "all" ||
    search !== "";

  return (
    <section className="pt-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-1.5">
        <div>
          <h1 className="font-display text-2xl font-bold">Quản lý website</h1>
        </div>
        <div className="flex gap-1">
          {canChangeSite && (
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
          )}
          {canAddSite && (
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
          )}
        </div>
      </div>

      {canAddSite && (
        <div className="mb-2.5">
          <SiteImport onImport={handleImport} pending={importSites.isPending} hostings={hostings} />
        </div>
      )}

      <div className="mb-3">
        <SiteStats counts={stats ?? {}} loading={statsLoading} />
      </div>

      <div className="mb-2.5 flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted">Trạng thái:</span>
          <Select
            value={statusFilter}
            onChange={(v) => {
              setStatusFilter(v);
              setPage(1);
            }}
            className="min-w-44"
            options={[
              { value: "all", label: "Tất cả trạng thái" },
              { value: "up", label: "Hoạt động" },
              { value: "down", label: "Không hoạt động" },
              { value: "unknown", label: "Chưa kiểm tra" },
            ]}
          />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted">Nền tảng:</span>
          <Select
            value={platformFilter}
            onChange={(v) => {
              setPlatformFilter(v);
              setPage(1);
            }}
            className="min-w-40"
            options={[
              { value: "all", label: "Tất cả nền tảng" },
              { value: "woocommerce", label: "WooCommerce" },
              { value: "sapo", label: "Sapo Web" },
            ]}
          />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted">Loại trang:</span>
          <Select
            value={primaryFilter}
            onChange={(v) => {
              setPrimaryFilter(v);
              setPage(1);
            }}
            className="min-w-40"
            options={[
              { value: "all", label: "Tất cả" },
              { value: "true", label: "Trang chính" },
              { value: "false", label: "Trang thường" },
            ]}
          />
        </div>
        {hostings.length > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted">Hosting:</span>
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
      </div>

      {isError ? (
        <ErrorState message="Không tải được danh sách site" onRetry={refetch} />
      ) : (
        <div className="rounded bg-surface-raised p-2.5 border border-border">
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
            rowSelection={
              canChangeSite
                ? {
                    selectedRowKeys: selectedKeys,
                    onChange: setSelectedKeys,
                    preserveSelectedRowKeys: true,
                  }
                : undefined
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
                  title={filterActive ? "Không có website phù hợp" : "Chưa có website"}
                  hint={
                    filterActive
                      ? "Thử đổi từ khóa tìm kiếm hoặc các bộ lọc trạng thái / nền tảng / loại trang / hosting."
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

      <DomainInfoModal
        site={domainSite}
        open={!!domainSite}
        onClose={() => setDomainSite(null)}
      />
    </section>
  );
}
