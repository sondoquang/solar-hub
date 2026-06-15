import { zodResolver } from "@hookform/resolvers/zod";
import { Button, Empty, Input, InputNumber, Select, Switch, Table, Tabs, TreeSelect } from "antd";
import { ImagePlus, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Controller, useFieldArray, useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { z } from "zod";

import { useProductCategories, useProductSearch, useSyncCategories } from "../api/products.js";
import MediaLibraryModal from "./MediaLibraryModal.jsx";
import RichTextEditor from "./RichTextEditor.jsx";

export const STATUS_OPTIONS = [
  { value: "draft", label: "Nháp" },
  { value: "publish", label: "Đã đăng" },
  { value: "pending", label: "Chờ duyệt" },
  { value: "private", label: "Riêng tư" },
];

export const STOCK_OPTIONS = [
  { value: "instock", label: "Còn hàng" },
  { value: "outofstock", label: "Hết hàng" },
  { value: "onbackorder", label: "Đặt trước" },
];

export const TYPE_OPTIONS = [
  { value: "simple", label: "Sản phẩm đơn giản" },
  { value: "grouped", label: "Sản phẩm nhóm" },
  { value: "external", label: "Sản phẩm liên kết ngoài" },
  { value: "variable", label: "Sản phẩm có biến thể" },
];

// --- Validation: a discriminated union so only the active type's fields run ----
const base = {
  sku: z.string().min(1, "Bắt buộc"),
  name: z.string().min(1, "Bắt buộc"),
  status: z.string(),
  short_description: z.string().optional(),
  description: z.string().optional(),
  categories: z.array(z.string()).optional(),
  images: z.array(z.string()).optional(),
};

const priceBlock = {
  regular_price: z.number({ invalid_type_error: "Bắt buộc" }).min(0, "≥ 0"),
  sale_price: z.number().min(0, "≥ 0").nullable(),
  stock_status: z.string(),
  weight: z.number().min(0, "≥ 0").nullable(),
};

const attributeSchema = z.object({
  name: z.string().min(1, "Bắt buộc"),
  options: z.array(z.string()).min(1, "Thêm ít nhất 1 giá trị"),
  variation: z.boolean(),
  visible: z.boolean(),
});

const variationSchema = z.object({
  sku: z.string().min(1, "Bắt buộc"),
  regular_price: z.number().min(0, "≥ 0").nullable(),
  sale_price: z.number().min(0, "≥ 0").nullable(),
  stock_status: z.string(),
  weight: z.number().min(0, "≥ 0").nullable(),
  attributes: z.record(z.string(), z.string()),
  image: z.string().optional(),
});

const schema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("simple"), ...base, ...priceBlock }),
  z.object({
    type: z.literal("external"),
    ...base,
    external_url: z.string().url("URL không hợp lệ"),
    button_text: z.string().optional(),
    regular_price: z.number().min(0, "≥ 0").nullable(),
    sale_price: z.number().min(0, "≥ 0").nullable(),
  }),
  z.object({
    type: z.literal("grouped"),
    ...base,
    grouped_skus: z.array(z.string()).min(1, "Chọn ít nhất 1 sản phẩm"),
  }),
  z.object({
    type: z.literal("variable"),
    ...base,
    attributes: z.array(attributeSchema).min(1, "Thêm ít nhất 1 thuộc tính"),
    variations: z.array(variationSchema),
  }),
]);

const errCls = "mt-1 text-xs text-danger";
const Req = () => <span className="ml-0.5 text-danger">*</span>;
const Label = ({ children, required }) => (
  <label className="mb-1 block text-sm font-medium">
    {children}
    {required && <Req />}
  </label>
);

// WP-style metabox: bordered card with a labelled header
function Postbox({ title, action, children }) {
  return (
    <div className="rounded border border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-3 py-2">
        <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
        {action}
      </div>
      <div className="p-3">{children}</div>
    </div>
  );
}

const EMPTY = {
  type: "simple",
  sku: "",
  name: "",
  status: "draft",
  stock_status: "instock",
  regular_price: 0,
  sale_price: null,
  weight: null,
  short_description: "",
  description: "",
  categories: [],
  images: [],
  external_url: "",
  button_text: "",
  grouped_skus: [],
  attributes: [],
  variations: [],
};

const num = (v) => (v != null && v !== "" ? Number(v) : null);

// Coerce a product row (prices come back as strings, e.g. "150000.00") into the
// numeric shape the form controls expect, including nested variation prices.
const toForm = (d) => ({
  ...EMPTY,
  ...d,
  type: d?.type ?? "simple",
  regular_price: d?.regular_price != null ? Number(d.regular_price) : 0,
  sale_price: num(d?.sale_price),
  weight: num(d?.weight),
  categories: d?.categories ?? [],
  images: d?.images ?? [],
  grouped_skus: d?.grouped_skus ?? [],
  attributes: d?.attributes ?? [],
  variations: (d?.variations ?? []).map((v) => ({
    stock_status: "instock",
    attributes: {},
    image: "",
    ...v,
    regular_price: num(v?.regular_price),
    sale_price: num(v?.sale_price),
    weight: num(v?.weight),
  })),
});

const priceProps = {
  className: "w-full",
  size: "large",
  min: 0,
  formatter: (v) => (v == null ? "" : `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ".")),
  parser: (v) => (v ? Number(v.replace(/\./g, "")) : null),
};

// All attribute combinations (cartesian product) of the variation-flagged
// attributes, e.g. [{Màu:"Đỏ",Size:"M"}, {Màu:"Đỏ",Size:"L"}, ...].
const cartesian = (attrs) =>
  (attrs || [])
    .filter((a) => a.variation && a.name && a.options?.length)
    .reduce(
      (acc, a) => acc.flatMap((combo) => a.options.map((opt) => ({ ...combo, [a.name]: opt }))),
      [{}],
    );

const sig = (attrsObj) => JSON.stringify(Object.entries(attrsObj || {}).sort());

const comboLabel = (attrsObj) => Object.values(attrsObj || {}).join(" / ") || "—";

export default function ProductRegisterForm({ formId, onSubmit, defaultValues }) {
  const {
    control,
    handleSubmit,
    reset,
    watch,
    setValue,
    getValues,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(schema),
    defaultValues: toForm(defaultValues),
  });

  const type = watch("type");
  const watchImages = watch("images");
  const featuredUrl = watchImages?.[0] ?? "";
  const albumUrls = (watchImages ?? []).slice(1);
  // Which slot the media picker fills: "featured" | "album" | {variation: i}.
  const [picker, setPicker] = useState(null);

  const attrArray = useFieldArray({ control, name: "attributes" });
  const varArray = useFieldArray({ control, name: "variations" });

  const categoriesQuery = useProductCategories();
  const syncCategories = useSyncCategories();
  const [groupedSearch, setGroupedSearch] = useState("");
  const groupedResults = useProductSearch(groupedSearch);

  const submit = async (values) => {
    await onSubmit(values, { onSuccess: () => reset(toForm()) });
  };

  // Build the WooCommerce-style category tree from the flat list the API
  // returns (each row carries its `parent` id; null = root). Node value/title is
  // the category NAME because the product stores categories by name. Values that
  // aren't in the synced catalog (e.g. a product edited with a custom name) still
  // render as tags — AntD shows the raw value when it has no matching node.
  const categoryTreeData = useMemo(() => {
    const cats = categoriesQuery.data ?? [];
    const byId = new Map(cats.map((c) => [c.id, { ...c, children: [] }]));
    const roots = [];
    for (const node of byId.values()) {
      const parent = node.parent != null ? byId.get(node.parent) : undefined;
      if (parent) parent.children.push(node);
      else roots.push(node);
    }
    const toNode = (c) => ({
      value: c.name,
      title: c.name,
      key: c.id,
      children: c.children.length ? c.children.map(toNode) : undefined,
    });
    return roots.map(toNode);
  }, [categoriesQuery.data]);

  const pullCategories = () => {
    syncCategories.mutate(undefined, {
      onSuccess: () => toast.success("Đã kích hoạt cập nhật danh mục từ các site."),
      onError: () => toast.error("Cập nhật danh mục thất bại."),
    });
  };

  // `images[0]` is the featured slot, the rest is the album (Woo semantics).
  const handlePicked = (urls) => {
    const imgs = getValues("images") ?? [];
    if (picker === "featured") {
      setValue("images", [urls[0], ...imgs.slice(1)]);
    } else if (picker === "album") {
      // Append after the featured slot; with no featured yet the first picked
      // image becomes the featured (ảnh đầu tiên là ảnh đại diện).
      setValue("images", [...imgs, ...urls]);
    } else if (picker && typeof picker === "object") {
      setValue(`variations.${picker.variation}.image`, urls[0]);
    }
  };

  const removeImageAt = (index) => {
    const imgs = getValues("images") ?? [];
    setValue(
      "images",
      imgs.filter((_, i) => i !== index),
    );
  };

  // Append the attribute combinations that don't already have a variation row,
  // keyed by their attribute signature so re-running keeps prices already typed.
  const generateVariations = () => {
    const existing = new Set(getValues("variations").map((v) => sig(v.attributes)));
    const combos = cartesian(getValues("attributes"));
    const fresh = combos.filter((c) => !existing.has(sig(c)));
    if (!fresh.length) {
      toast("Không có biến thể mới để tạo.");
      return;
    }
    const baseSku = getValues("sku") || "SP";
    varArray.append(
      fresh.map((attrs, i) => ({
        sku: `${baseSku}-${getValues("variations").length + i + 1}`,
        regular_price: null,
        sale_price: null,
        stock_status: "instock",
        weight: null,
        attributes: attrs,
        image: "",
      })),
    );
  };

  // --- "Product data" tabs, filtered by the selected type ---------------------
  const generalTab = {
    key: "general",
    label: "Chung",
    children: (
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label required={type !== "external"}>Giá bán</Label>
          <Controller
            name="regular_price"
            control={control}
            render={({ field }) => (
              <InputNumber
                {...field}
                {...priceProps}
                status={errors.regular_price ? "error" : ""}
              />
            )}
          />
          {errors.regular_price && <p className={errCls}>{errors.regular_price.message}</p>}
        </div>
        <div>
          <Label>Giá khuyến mãi</Label>
          <Controller
            name="sale_price"
            control={control}
            render={({ field }) => <InputNumber {...field} {...priceProps} />}
          />
        </div>
      </div>
    ),
  };

  const inventoryTab = {
    key: "inventory",
    label: "Tồn kho",
    children: (
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label>Tình trạng kho</Label>
          <Controller
            name="stock_status"
            control={control}
            render={({ field }) => (
              <Select {...field} size="large" className="w-full" options={STOCK_OPTIONS} />
            )}
          />
        </div>
        <div>
          <Label>Khối lượng (kg)</Label>
          <Controller
            name="weight"
            control={control}
            render={({ field }) => (
              <InputNumber {...field} size="large" className="w-full" min={0} step={0.1} />
            )}
          />
        </div>
      </div>
    ),
  };

  const externalTab = {
    key: "external",
    label: "Liên kết ngoài",
    children: (
      <div className="grid gap-3">
        <div>
          <Label required>Đường dẫn sản phẩm (URL)</Label>
          <Controller
            name="external_url"
            control={control}
            render={({ field }) => (
              <Input
                {...field}
                size="large"
                status={errors.external_url ? "error" : ""}
                placeholder="https://…"
              />
            )}
          />
          {errors.external_url && <p className={errCls}>{errors.external_url.message}</p>}
        </div>
        <div>
          <Label>Nhãn nút mua</Label>
          <Controller
            name="button_text"
            control={control}
            render={({ field }) => <Input {...field} size="large" placeholder="Mua ngay" />}
          />
        </div>
      </div>
    ),
  };

  const groupedTab = {
    key: "grouped",
    label: "Sản phẩm nhóm",
    children: (
      <div>
        <Label required>Sản phẩm con (theo SKU)</Label>
        <Controller
          name="grouped_skus"
          control={control}
          render={({ field }) => (
            <Select
              {...field}
              mode="multiple"
              size="large"
              className="w-full"
              placeholder="Tìm và chọn sản phẩm…"
              filterOption={false}
              onSearch={setGroupedSearch}
              loading={groupedResults.isFetching}
              status={errors.grouped_skus ? "error" : ""}
              options={(groupedResults.data?.results ?? []).map((p) => ({
                value: p.sku,
                label: `${p.name} (${p.sku})`,
              }))}
            />
          )}
        />
        {errors.grouped_skus && <p className={errCls}>{errors.grouped_skus.message}</p>}
        <p className="mt-1 text-xs text-muted">
          Khi đồng bộ, mỗi SKU con được map sang ID sản phẩm tương ứng trên từng site.
        </p>
      </div>
    ),
  };

  const attributesTab = {
    key: "attributes",
    label: "Thuộc tính",
    children: (
      <div className="grid gap-2">
        {attrArray.fields.length === 0 && (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Chưa có thuộc tính" />
        )}
        {attrArray.fields.map((f, i) => (
          <div key={f.id} className="rounded border border-slate-200 p-2">
            <div className="grid grid-cols-[1fr_2fr_auto] items-end gap-2">
              <div>
                <Label>Tên thuộc tính</Label>
                <Controller
                  name={`attributes.${i}.name`}
                  control={control}
                  render={({ field }) => <Input {...field} size="large" placeholder="VD: Màu" />}
                />
              </div>
              <div>
                <Label>Giá trị</Label>
                <Controller
                  name={`attributes.${i}.options`}
                  control={control}
                  render={({ field }) => (
                    <Select
                      {...field}
                      mode="tags"
                      size="large"
                      className="w-full"
                      placeholder="Nhập giá trị, Enter để thêm"
                      tokenSeparators={[","]}
                      open={false}
                    />
                  )}
                />
              </div>
              <Button
                danger
                type="text"
                icon={<Trash2 size={16} />}
                onClick={() => attrArray.remove(i)}
              />
            </div>
            <div className="mt-2 flex items-center gap-4 text-sm">
              <Controller
                name={`attributes.${i}.variation`}
                control={control}
                render={({ field }) => (
                  <label className="flex items-center gap-1.5">
                    <Switch size="small" checked={field.value} onChange={field.onChange} />
                    Dùng cho biến thể
                  </label>
                )}
              />
              <Controller
                name={`attributes.${i}.visible`}
                control={control}
                render={({ field }) => (
                  <label className="flex items-center gap-1.5">
                    <Switch size="small" checked={field.value} onChange={field.onChange} />
                    Hiển thị
                  </label>
                )}
              />
            </div>
          </div>
        ))}
        {typeof errors.attributes?.message === "string" && (
          <p className={errCls}>{errors.attributes.message}</p>
        )}
        <Button
          type="dashed"
          icon={<Plus size={15} />}
          onClick={() =>
            attrArray.append({ name: "", options: [], variation: true, visible: true })
          }
        >
          Thêm thuộc tính
        </Button>
      </div>
    ),
  };

  const variationColumns = [
    {
      key: "combo",
      title: "Biến thể",
      width: 140,
      render: (_v, _r, i) => (
        <span className="text-xs font-medium">
          {comboLabel(getValues(`variations.${i}.attributes`))}
        </span>
      ),
    },
    {
      key: "sku",
      title: "SKU",
      width: 140,
      render: (_v, _r, i) => (
        <Controller
          name={`variations.${i}.sku`}
          control={control}
          render={({ field }) => <Input {...field} size="small" />}
        />
      ),
    },
    {
      key: "regular_price",
      title: "Giá",
      width: 120,
      render: (_v, _r, i) => (
        <Controller
          name={`variations.${i}.regular_price`}
          control={control}
          render={({ field }) => <InputNumber {...field} {...priceProps} size="small" />}
        />
      ),
    },
    {
      key: "sale_price",
      title: "Giá KM",
      width: 120,
      render: (_v, _r, i) => (
        <Controller
          name={`variations.${i}.sale_price`}
          control={control}
          render={({ field }) => <InputNumber {...field} {...priceProps} size="small" />}
        />
      ),
    },
    {
      key: "stock_status",
      title: "Kho",
      width: 120,
      render: (_v, _r, i) => (
        <Controller
          name={`variations.${i}.stock_status`}
          control={control}
          render={({ field }) => (
            <Select {...field} size="small" className="w-full" options={STOCK_OPTIONS} />
          )}
        />
      ),
    },
    {
      key: "image",
      title: "Ảnh",
      width: 110,
      render: (_v, _r, i) => (
        <Controller
          name={`variations.${i}.image`}
          control={control}
          render={({ field }) =>
            field.value ? (
              <div className="group relative h-10 w-10 overflow-hidden rounded border border-slate-200">
                <img src={field.value} alt="Ảnh biến thể" className="h-full w-full object-cover" />
                <button
                  type="button"
                  title="Xóa ảnh"
                  onClick={() => field.onChange("")}
                  className="absolute inset-0 hidden items-center justify-center bg-white/70 text-danger group-hover:flex"
                >
                  <X size={14} />
                </button>
              </div>
            ) : (
              <Button
                size="small"
                icon={<ImagePlus size={13} />}
                onClick={() => setPicker({ variation: i })}
              />
            )
          }
        />
      ),
    },
    {
      key: "actions",
      title: "",
      width: 48,
      render: (_v, _r, i) => (
        <Button
          danger
          type="text"
          size="small"
          icon={<Trash2 size={14} />}
          onClick={() => varArray.remove(i)}
        />
      ),
    },
  ];

  const variationsTab = {
    key: "variations",
    label: "Biến thể",
    children: (
      <div className="grid gap-2">
        <div className="flex gap-1.5">
          <Button icon={<RefreshCw size={14} />} onClick={generateVariations}>
            Tạo tất cả biến thể
          </Button>
          <Button
            icon={<Plus size={14} />}
            onClick={() =>
              varArray.append({
                sku: "",
                regular_price: null,
                sale_price: null,
                stock_status: "instock",
                weight: null,
                attributes: {},
                image: "",
              })
            }
          >
            Thêm thủ công
          </Button>
        </div>
        <Table
          rowKey="id"
          size="small"
          columns={variationColumns}
          dataSource={varArray.fields}
          pagination={false}
          scroll={{ x: true, y: 320 }}
          locale={{ emptyText: "Chưa có biến thể — tạo từ thuộc tính ở trên" }}
        />
      </div>
    ),
  };

  const tabsByType = {
    simple: [generalTab, inventoryTab],
    external: [generalTab, externalTab],
    grouped: [groupedTab],
    variable: [attributesTab, variationsTab],
  };
  const dataTabs = tabsByType[type] ?? [generalTab, inventoryTab];

  return (
    <form id={formId} onSubmit={handleSubmit(submit)} className="flex flex-col gap-4">
      {/* Single column — sections stack vertically and the modal body scrolls.
          Action buttons live in the modal footer (submit via the form id). */}

      {/* Tên & SKU */}
      <Postbox title="Thông tin chung">
        <div className="grid gap-3">
          <div>
            <Label required>Tên sản phẩm</Label>
            <Controller
              name="name"
              control={control}
              render={({ field }) => (
                <Input
                  {...field}
                  size="large"
                  status={errors.name ? "error" : ""}
                  placeholder="Nhập tên sản phẩm…"
                />
              )}
            />
            {errors.name && <p className={errCls}>{errors.name.message}</p>}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <Label required>SKU</Label>
              <Controller
                name="sku"
                control={control}
                render={({ field }) => (
                  <Input {...field} size="large" status={errors.sku ? "error" : ""} />
                )}
              />
              {errors.sku && <p className={errCls}>{errors.sku.message}</p>}
            </div>
            <div>
              <Label>Trạng thái</Label>
              <Controller
                name="status"
                control={control}
                render={({ field }) => (
                  <Select {...field} size="large" className="w-full" options={STATUS_OPTIONS} />
                )}
              />
            </div>
          </div>
        </div>
      </Postbox>

      {/* Dữ liệu sản phẩm */}
      <Postbox
        title="Dữ liệu sản phẩm"
        action={
          <Controller
            name="type"
            control={control}
            render={({ field }) => (
              <Select {...field} size="small" className="min-w-48" options={TYPE_OPTIONS} />
            )}
          />
        }
      >
        <Tabs tabPosition="left" items={dataTabs} size="small" className="wp-product-data-tabs" />
      </Postbox>

      {/* Danh mục */}
      <Postbox
        title="Danh mục sản phẩm"
        action={
          <Button
            type="link"
            size="small"
            className="px-0"
            loading={syncCategories.isPending}
            onClick={pullCategories}
          >
            Cập nhật từ site
          </Button>
        }
      >
        <Controller
          name="categories"
          control={control}
          render={({ field }) => (
            <TreeSelect
              {...field}
              multiple
              size="large"
              treeDefaultExpandAll
              showSearch
              treeNodeFilterProp="title"
              className="w-full"
              placeholder="Chọn danh mục (theo cây)"
              loading={categoriesQuery.isLoading}
              treeData={categoryTreeData}
              notFoundContent={
                categoriesQuery.isLoading
                  ? "Đang tải…"
                  : "Chưa có danh mục — bấm “Cập nhật từ site”"
              }
            />
          )}
        />
      </Postbox>

      {/* Ảnh sản phẩm (ảnh đại diện) */}
      <Postbox title="Ảnh sản phẩm">
        {featuredUrl ? (
          <div className="grid gap-2">
            <img
              src={featuredUrl}
              alt="Ảnh sản phẩm"
              className="w-full rounded border border-slate-200 object-contain"
              style={{ maxHeight: 220 }}
            />
            <div className="flex gap-2">
              <Button icon={<ImagePlus size={14} />} onClick={() => setPicker("featured")}>
                Thay ảnh
              </Button>
              <Button danger icon={<Trash2 size={14} />} onClick={() => removeImageAt(0)}>
                Xóa ảnh
              </Button>
            </div>
          </div>
        ) : (
          <Button
            type="dashed"
            block
            icon={<ImagePlus size={15} />}
            onClick={() => setPicker("featured")}
          >
            Đặt ảnh sản phẩm (tải lên hoặc chọn từ thư viện)
          </Button>
        )}
      </Postbox>

      {/* Album hình ảnh (ảnh phụ) */}
      <Postbox
        title="Album hình ảnh sản phẩm"
        action={
          <Button
            type="link"
            size="small"
            className="px-0"
            icon={<Plus size={14} />}
            onClick={() => setPicker("album")}
          >
            Thêm ảnh vào album
          </Button>
        }
      >
        {albumUrls.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="Chưa có ảnh phụ — bấm “Thêm ảnh vào album”"
          />
        ) : (
          <div className="grid grid-cols-4 gap-2 sm:grid-cols-6">
            {albumUrls.map((url, i) => (
              <div
                key={`${url}-${i}`}
                className="group relative aspect-square overflow-hidden rounded border border-slate-200"
              >
                <img src={url} alt={`Ảnh phụ ${i + 1}`} className="h-full w-full object-cover" />
                <button
                  type="button"
                  title="Xóa khỏi album"
                  onClick={() => removeImageAt(i + 1)}
                  className="absolute right-1 top-1 hidden rounded-full bg-white/90 p-0.5 text-danger shadow group-hover:block"
                >
                  <X size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
        <p className="mt-2 text-xs text-muted">
          Ảnh phụ hiển thị trong gallery của sản phẩm trên từng site.
        </p>
      </Postbox>

      {/* Mô tả */}
      <Postbox title="Mô tả">
        <Controller
          name="description"
          control={control}
          render={({ field }) => (
            <RichTextEditor
              value={field.value}
              onChange={field.onChange}
              minHeight="200px"
              enableImage
            />
          )}
        />
      </Postbox>

      {/* Mô tả ngắn */}
      <Postbox title="Mô tả ngắn của sản phẩm">
        <Controller
          name="short_description"
          control={control}
          render={({ field }) => (
            <RichTextEditor value={field.value} onChange={field.onChange} minHeight="160px" />
          )}
        />
      </Postbox>

      {/* Media picker (ảnh đại diện / album / ảnh biến thể) */}
      <MediaLibraryModal
        open={picker !== null}
        multiple={picker === "album"}
        title={
          picker === "album"
            ? "Thêm ảnh vào album sản phẩm"
            : picker === "featured"
              ? "Đặt ảnh sản phẩm"
              : "Chọn ảnh biến thể"
        }
        onClose={() => setPicker(null)}
        onSelect={handlePicked}
      />
    </form>
  );
}
