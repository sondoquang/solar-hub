import { Button, Drawer, Input, Popconfirm, Select } from "antd";
import { Network, Package, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import {
  useCreateProduct,
  useDeleteProduct,
  useProducts,
  useProductStats,
  useSyncProducts,
  useUpdateProduct,
} from "../api/products.js";
import DataTable from "../components/DataTable.jsx";
import EmptyState from "../components/EmptyState.jsx";
import ErrorState from "../components/ErrorState.jsx";
import ProductRegisterForm, {
  STATUS_OPTIONS as FORM_STATUS,
  STOCK_OPTIONS as FORM_STOCK,
} from "../components/ProductRegisterForm.jsx";
import ProductStats from "../components/ProductStats.jsx";
import ProductStatusBadge from "../components/ProductStatusBadge.jsx";
import ProductSyncStatusModal from "../components/ProductSyncStatusModal.jsx";
import { formatDate, formatVND } from "../lib/format.js";

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

const STATUS_FILTER = [{ value: "all", label: "Tất cả trạng thái" }, ...FORM_STATUS];
const STOCK_FILTER = [{ value: "all", label: "Tất cả kho" }, ...FORM_STOCK];
const STOCK_LABEL = Object.fromEntries(FORM_STOCK.map((o) => [o.value, o.label]));

export default function Products() {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [stockFilter, setStockFilter] = useState("all");
  const [ordering, setOrdering] = useState("-updated_at");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null); // product being edited, or null
  const [syncProduct, setSyncProduct] = useState(null); // product whose sync panel is open

  // Debounce the search box so we re-query once the user pauses.
  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 350);
    return () => clearTimeout(t);
  }, [searchInput]);

  // Shared filter payload — the list and the stats cards both use it.
  const filters = useMemo(
    () => ({
      search: search || undefined,
      status: statusFilter === "all" ? undefined : statusFilter,
      stock_status: stockFilter === "all" ? undefined : stockFilter,
    }),
    [search, statusFilter, stockFilter]
  );

  const { data, isLoading, isFetching, isError, refetch } = useProducts({
    ...filters,
    ordering,
    page,
    page_size: pageSize,
  });
  const { data: stats, isLoading: statsLoading } = useProductStats(filters);

  const createProduct = useCreateProduct();
  const updateProduct = useUpdateProduct();
  const deleteProduct = useDeleteProduct();
  const sync = useSyncProducts();

  const rows = data?.results ?? [];
  const total = data?.count ?? 0;

  const closeForm = () => {
    setShowForm(false);
    setEditing(null);
  };

  const handleSubmit = async (values, { onSuccess }) => {
    try {
      if (editing) {
        await updateProduct.mutateAsync({ id: editing.id, ...values });
        toast.success("Đã cập nhật sản phẩm.");
      } else {
        await createProduct.mutateAsync(values);
        toast.success("Đã tạo sản phẩm.");
      }
      closeForm();
      onSuccess?.();
    } catch (e) {
      const skuErr = e?.response?.data?.sku?.[0];
      toast.error(skuErr || "Lưu thất bại. Kiểm tra lại dữ liệu.");
    }
  };

  const handleDelete = async (product) => {
    try {
      await deleteProduct.mutateAsync(product.id);
      toast.success("Đã xóa sản phẩm.");
    } catch {
      toast.error("Xóa thất bại.");
    }
  };

  // Push the whole catalog to every site (async Celery job). The filters scope
  // the *view*, not the push — sync_now always pushes the full catalog/fleet.
  const handleSync = () => {
    sync.mutate(
      {},
      {
        onSuccess: () => toast.success("Đã kích hoạt đồng bộ sản phẩm xuống các site."),
        onError: () => toast.error("Kích hoạt đồng bộ thất bại."),
      }
    );
  };

  const openEdit = (product) => {
    setEditing(product);
    setShowForm(true);
  };

  // antd drives sort/page through onChange. name/sku/updated_at are
  // server-sortable; a sort or page-size change resets to page 1.
  const handleTableChange = (pagination, _filters, sorter) => {
    let next = "-updated_at";
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
      key: "stt",
      title: "STT",
      width: 64,
      ellipsis: false,
      align: "center",
      render: (_v, _r, i) => (page - 1) * pageSize + i + 1,
    },
    {
      key: "sku",
      dataIndex: "sku",
      title: "Sản phẩm",
      width: 260,
      sorter: true,
      sortOrder: sortOrder("sku"),
      render: (_v, r) => (
        <div className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-50 text-blue-500">
            <Package size={15} />
          </span>
          <div className="min-w-0">
            <p className="truncate font-medium">{r.name}</p>
            <p className="truncate text-xs text-muted">{r.sku}</p>
          </div>
        </div>
      ),
    },
    {
      key: "regular_price",
      dataIndex: "regular_price",
      title: "Giá bán",
      width: 150,
      align: "right",
      render: (v, r) => (
        <div className="min-w-0">
          <p className="font-medium tabular-nums">{formatVND(v)}</p>
          {r.sale_price != null && r.sale_price !== "" && (
            <p className="truncate text-xs text-success tabular-nums">KM {formatVND(r.sale_price)}</p>
          )}
        </div>
      ),
    },
    {
      key: "status",
      dataIndex: "status",
      title: "Trạng thái",
      width: 130,
      ellipsis: false,
      render: (status) => <ProductStatusBadge status={status} />,
    },
    {
      key: "stock_status",
      dataIndex: "stock_status",
      title: "Kho",
      width: 120,
      render: (v) => <span className="text-muted">{STOCK_LABEL[v] || v}</span>,
    },
    {
      key: "mapping_count",
      dataIndex: "mapping_count",
      title: "Đồng bộ site",
      width: 130,
      align: "center",
      render: (v) =>
        v > 0 ? (
          <span className="text-xs font-medium text-success">{v} site</span>
        ) : (
          <span className="text-xs text-muted">Chưa đồng bộ</span>
        ),
    },
    {
      key: "updated_at",
      dataIndex: "updated_at",
      title: "Cập nhật",
      width: 160,
      sorter: true,
      sortOrder: sortOrder("updated_at"),
      render: (v) => <span className="tabular-nums text-muted">{formatDate(v)}</span>,
    },
    {
      key: "actions",
      title: "Thao tác",
      width: 230,
      align: "right",
      hideable: false,
      ellipsis: false,
      render: (_v, r) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            size="small"
            icon={<Network size={14} />}
            onClick={() => setSyncProduct(r)}
            title="Trạng thái đồng bộ theo domain"
          >
            Đồng bộ
          </Button>
          <Button size="small" icon={<Pencil size={14} />} onClick={() => openEdit(r)}>
            Sửa
          </Button>
          <Popconfirm
            title="Xóa sản phẩm này?"
            description="Lần đồng bộ tới sẽ gỡ sản phẩm khỏi các site."
            okText="Xóa"
            cancelText="Hủy"
            onConfirm={() => handleDelete(r)}
          >
            <Button size="small" danger icon={<Trash2 size={14} />}>
              Xóa
            </Button>
          </Popconfirm>
        </div>
      ),
    },
  ];

  const filterActive = search !== "" || statusFilter !== "all" || stockFilter !== "all";

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-1.5">
        <div>
          <h1 className="font-display text-2xl font-bold">Sản phẩm</h1>
          <p className="mt-1 text-sm text-muted">
            Catalog gốc tại Hub — đồng bộ đồng loạt xuống các website WooCommerce.
          </p>
        </div>
        <div className="flex gap-1">
          <Button
            icon={<RefreshCw size={16} />}
            loading={sync.isPending}
            onClick={handleSync}
          >
            Đồng bộ ngay
          </Button>
          <Button
            type="primary"
            icon={<Plus size={16} />}
            onClick={() => {
              setEditing(null);
              setShowForm(true);
            }}
          >
            Thêm sản phẩm
          </Button>
        </div>
      </div>

      <div className="mb-3">
        <ProductStats stats={stats ?? {}} loading={statsLoading} />
      </div>

      <div className="mb-2.5 flex flex-wrap items-center gap-2">
        <Select
          value={statusFilter}
          onChange={(v) => {
            setStatusFilter(v);
            setPage(1);
          }}
          options={STATUS_FILTER}
          className="min-w-44"
        />
        <Select
          value={stockFilter}
          onChange={(v) => {
            setStockFilter(v);
            setPage(1);
          }}
          options={STOCK_FILTER}
          className="min-w-40"
        />
      </div>

      {isError ? (
        <ErrorState message="Không tải được danh sách sản phẩm" onRetry={refetch} />
      ) : (
        <div className="rounded bg-white p-2.5 shadow-card">
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
                placeholder="Tìm theo SKU hoặc tên…"
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
                  title={filterActive ? "Không có sản phẩm phù hợp" : "Chưa có sản phẩm nào"}
                  hint={
                    filterActive
                      ? "Thử đổi từ khóa hoặc bộ lọc."
                      : 'Bấm "Thêm sản phẩm" để tạo catalog gốc.'
                  }
                />
              ),
            }}
          />
        </div>
      )}

      <Drawer
        open={showForm}
        onClose={closeForm}
        destroyOnClose
        width={920}
        title={editing ? "Sửa sản phẩm" : "Thêm sản phẩm"}
      >
        <ProductRegisterForm
          defaultValues={editing ?? undefined}
          onSubmit={handleSubmit}
          onCancel={closeForm}
          pending={createProduct.isPending || updateProduct.isPending}
        />
      </Drawer>

      <ProductSyncStatusModal
        product={syncProduct}
        open={!!syncProduct}
        onClose={() => setSyncProduct(null)}
      />
    </section>
  );
}
