import { zodResolver } from "@hookform/resolvers/zod";
import { Button, Input, InputNumber, Select } from "antd";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

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

const schema = z.object({
  sku: z.string().min(1, "Bắt buộc"),
  name: z.string().min(1, "Bắt buộc"),
  status: z.string(),
  stock_status: z.string(),
  regular_price: z.number({ invalid_type_error: "Bắt buộc" }).min(0, "≥ 0"),
  sale_price: z.number().min(0, "≥ 0").nullable(),
  weight: z.number().min(0, "≥ 0").nullable(),
  short_description: z.string().optional(),
  description: z.string().optional(),
  categories: z.array(z.string()).optional(),
  images: z.array(z.string()).optional(),
});

const errCls = "mt-1 text-xs text-danger";
const Req = () => <span className="ml-0.5 text-danger">*</span>;

const EMPTY = {
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
};

// Coerce a product row (prices come back as strings, e.g. "150000.00") into the
// numeric shape the form controls expect.
const toForm = (d) => ({
  ...EMPTY,
  ...d,
  regular_price: d?.regular_price != null ? Number(d.regular_price) : 0,
  sale_price: d?.sale_price != null ? Number(d.sale_price) : null,
  weight: d?.weight != null ? Number(d.weight) : null,
  categories: d?.categories ?? [],
  images: d?.images ?? [],
});

const priceProps = {
  className: "w-full",
  size: "large",
  min: 0,
  formatter: (v) => (v == null ? "" : `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ".")),
  parser: (v) => (v ? Number(v.replace(/\./g, "")) : null),
};

export default function ProductRegisterForm({
  onSubmit,
  onCancel,
  pending,
  defaultValues,
}) {
  const {
    control,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(schema),
    defaultValues: toForm(defaultValues),
  });

  const submit = async (values) => {
    await onSubmit(values, { onSuccess: () => reset(toForm()) });
  };

  const busy = pending || isSubmitting;

  return (
    <form onSubmit={handleSubmit(submit)} className="grid gap-2">
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="mb-1 block text-sm font-medium">SKU<Req /></label>
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
          <label className="mb-1 block text-sm font-medium">Trạng thái</label>
          <Controller
            name="status"
            control={control}
            render={({ field }) => (
              <Select {...field} size="large" className="w-full" options={STATUS_OPTIONS} />
            )}
          />
        </div>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">Tên sản phẩm<Req /></label>
        <Controller
          name="name"
          control={control}
          render={({ field }) => (
            <Input {...field} size="large" status={errors.name ? "error" : ""} />
          )}
        />
        {errors.name && <p className={errCls}>{errors.name.message}</p>}
      </div>

      <div className="grid grid-cols-3 gap-2">
        <div>
          <label className="mb-1 block text-sm font-medium">Giá bán<Req /></label>
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
          <label className="mb-1 block text-sm font-medium">Giá khuyến mãi</label>
          <Controller
            name="sale_price"
            control={control}
            render={({ field }) => <InputNumber {...field} {...priceProps} />}
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium">Kho</label>
          <Controller
            name="stock_status"
            control={control}
            render={({ field }) => (
              <Select {...field} size="large" className="w-full" options={STOCK_OPTIONS} />
            )}
          />
        </div>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">Khối lượng (kg)</label>
        <Controller
          name="weight"
          control={control}
          render={({ field }) => (
            <InputNumber {...field} className="w-full" size="large" min={0} step={0.1} />
          )}
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">Danh mục</label>
        <Controller
          name="categories"
          control={control}
          render={({ field }) => (
            <Select
              {...field}
              mode="tags"
              size="large"
              className="w-full"
              placeholder="Nhập tên danh mục, Enter để thêm"
              tokenSeparators={[","]}
              open={false}
            />
          )}
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">Ảnh (URL)</label>
        <Controller
          name="images"
          control={control}
          render={({ field }) => (
            <Select
              {...field}
              mode="tags"
              size="large"
              className="w-full"
              placeholder="Dán URL ảnh, Enter để thêm"
              tokenSeparators={[",", " "]}
              open={false}
            />
          )}
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">Mô tả ngắn</label>
        <Controller
          name="short_description"
          control={control}
          render={({ field }) => <Input.TextArea {...field} rows={2} />}
        />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">Mô tả</label>
        <Controller
          name="description"
          control={control}
          render={({ field }) => <Input.TextArea {...field} rows={4} />}
        />
      </div>

      <div className="flex gap-1 pt-1">
        <Button type="primary" htmlType="submit" size="large" loading={busy}>
          {busy ? "Đang lưu…" : "Lưu sản phẩm"}
        </Button>
        {onCancel && (
          <Button size="large" onClick={onCancel}>
            Hủy
          </Button>
        )}
      </div>
    </form>
  );
}
