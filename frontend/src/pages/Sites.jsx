import { Button, Modal } from "antd";
import { ClipboardCheck, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import {
  useCreateSite,
  useDeleteSite,
  useImportSites,
  useSites,
  useTestConnection,
  useTestConnections,
  useUpdateSite,
} from "../api/sites.js";
import EmptyState from "../components/EmptyState.jsx";
import ErrorState from "../components/ErrorState.jsx";
import Loading from "../components/Loading.jsx";
import SiteImport from "../components/SiteImport.jsx";
import SiteRegisterForm from "../components/SiteRegisterForm.jsx";
import SitesTable from "../components/SitesTable.jsx";
import SiteStats from "../components/SiteStats.jsx";
import TablePagination from "../components/TablePagination.jsx";

export default function Sites() {
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null); // site being edited, or null
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [sortDir, setSortDir] = useState(null); // null | "asc" | "desc"
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const { data, isLoading, isError, refetch } = useSites();
  const createSite = useCreateSite();
  const updateSite = useUpdateSite();
  const deleteSite = useDeleteSite();
  const testConn = useTestConnection();
  const bulkTest = useTestConnections();
  const importSites = useImportSites();

  const sites = useMemo(() => data?.results ?? [], [data]);
  const testingId = testConn.isPending ? testConn.variables : null;

  const counts = useMemo(
    () => ({
      total: sites.length,
      up: sites.filter((s) => s.status === "up").length,
      down: sites.filter((s) => s.status === "down").length,
      unknown: sites.filter((s) => s.status !== "up" && s.status !== "down").length,
    }),
    [sites]
  );

  const sorted = useMemo(() => {
    if (!sortDir) return sites;
    const dir = sortDir === "asc" ? 1 : -1;
    return [...sites].sort((a, b) => a.name.localeCompare(b.name, "vi") * dir);
  }, [sites, sortDir]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pageSites = sorted.slice((safePage - 1) * pageSize, safePage * pageSize);

  // Keep the page in range when the list shrinks (delete / page-size change).
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

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
    const ids = [...selectedIds];
    if (ids.length === 0) return;
    try {
      const { results } = await bulkTest.mutateAsync(ids);
      const up = results.filter((r) => r.ok).length;
      toast.success(`Đã kiểm tra ${results.length} site, ${up} hoạt động.`);
    } catch {
      toast.error("Kiểm tra hàng loạt thất bại.");
    }
  };

  const handleDelete = async (site) => {
    try {
      await deleteSite.mutateAsync(site.id);
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(site.id);
        return next;
      });
      toast.success("Đã xóa site.");
    } catch {
      toast.error("Xóa thất bại.");
    }
  };

  const handleImport = async (file) => {
    try {
      const res = await importSites.mutateAsync(file);
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

  const toggleSort = () =>
    setSortDir((prev) => (prev === "asc" ? "desc" : prev === "desc" ? null : "asc"));

  const toggle = (id) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  // Header checkbox toggles the rows on the current page.
  const toggleAll = () =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      const allOnPage = pageSites.every((s) => next.has(s.id));
      pageSites.forEach((s) => (allOnPage ? next.delete(s.id) : next.add(s.id)));
      return next;
    });

  return (
    <section>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-bold">Quản lý website</h1>
          <p className="mt-1 text-sm text-muted">
            Quản lý danh sách website và trạng thái hoạt động
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            icon={<ClipboardCheck size={16} />}
            onClick={handleBulkTest}
            disabled={selectedIds.size === 0}
            loading={bulkTest.isPending}
          >
            {bulkTest.isPending ? "Đang kiểm tra…" : `Kiểm tra đã chọn (${selectedIds.size})`}
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

      <div className="mb-5">
        <SiteImport onImport={handleImport} pending={importSites.isPending} />
      </div>

      <div className="mb-6">
        <SiteStats counts={counts} />
      </div>

      {isLoading && <Loading />}
      {isError && <ErrorState message="Không tải được danh sách site" onRetry={refetch} />}
      {!isLoading && !isError && sites.length === 0 && (
        <EmptyState title="Chưa có website" hint="Bấm “Thêm website” hoặc import Excel." />
      )}
      {!isLoading && !isError && sites.length > 0 && (
        <div className="overflow-hidden rounded-xl bg-white shadow-card">
          <div className="overflow-x-auto">
            <SitesTable
              sites={pageSites}
              selectedIds={selectedIds}
              onToggle={toggle}
              onToggleAll={toggleAll}
              onTest={handleTest}
              testingId={testingId}
              onEdit={openEdit}
              onDelete={handleDelete}
              sortDir={sortDir}
              onToggleSort={toggleSort}
            />
          </div>
          <div className="border-t border-slate-100">
            <TablePagination
              page={safePage}
              pageSize={pageSize}
              total={sorted.length}
              onPageChange={setPage}
              onPageSizeChange={(n) => {
                setPageSize(n);
                setPage(1);
              }}
            />
          </div>
        </div>
      )}

      <Modal
        open={showForm}
        onCancel={closeForm}
        footer={null}
        destroyOnClose
        title={editing ? "Sửa website" : "Thêm website"}
      >
        <SiteRegisterForm
          mode={editing ? "edit" : "create"}
          defaultValues={editing ?? undefined}
          onSubmit={handleSubmit}
          onCancel={closeForm}
          pending={createSite.isPending || updateSite.isPending}
        />
      </Modal>
    </section>
  );
}
