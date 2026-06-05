import { zodResolver } from "@hookform/resolvers/zod";
import { Button, Input, InputNumber } from "antd";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

const schema = z.object({
  name: z.string().min(1, "Bắt buộc"),
  provider: z.string().optional(),
  account_username: z.string().optional(),
  check_concurrency: z
    .number({ invalid_type_error: "Phải là số" })
    .int("Phải là số nguyên")
    .min(1, "Tối thiểu 1")
    .max(50, "Tối đa 50"),
  note: z.string().optional(),
});

const errCls = "mt-1 text-xs text-danger";
const Req = () => <span className="ml-0.5 text-danger">*</span>;
const EMPTY = {
  name: "",
  provider: "",
  account_username: "",
  check_concurrency: 5,
  note: "",
};

export default function HostingRegisterForm({ onSubmit, onCancel, pending, defaultValues }) {
  const {
    control,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(schema),
    defaultValues: { ...EMPTY, ...defaultValues },
  });

  const submit = async (values) => {
    await onSubmit(values, { onSuccess: () => reset({ ...EMPTY }) });
  };

  const busy = pending || isSubmitting;

  return (
    <form onSubmit={handleSubmit(submit)} className="grid gap-2">
      <div>
        <label className="mb-1 block text-sm font-medium">Tên hosting<Req /></label>
        <Controller
          name="name"
          control={control}
          render={({ field }) => (
            <Input {...field} size="large" placeholder="VD: TenTen - Server A" status={errors.name ? "error" : ""} />
          )}
        />
        {errors.name && <p className={errCls}>{errors.name.message}</p>}
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium">Nhà cung cấp</label>
        <Controller
          name="provider"
          control={control}
          render={({ field }) => <Input {...field} size="large" placeholder="VD: TenTen" />}
        />
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium">Tài khoản đăng nhập</label>
        <Controller
          name="account_username"
          control={control}
          render={({ field }) => <Input {...field} size="large" placeholder="username hosting" />}
        />
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium">
          Số domain kiểm tra đồng thời<Req />
        </label>
        <Controller
          name="check_concurrency"
          control={control}
          render={({ field }) => (
            <InputNumber
              {...field}
              size="large"
              min={1}
              max={50}
              className="w-full"
              status={errors.check_concurrency ? "error" : ""}
            />
          )}
        />
        <p className="mt-1 text-xs text-muted">
          Hosting yếu nên đặt thấp để tránh dội request cùng lúc.
        </p>
        {errors.check_concurrency && <p className={errCls}>{errors.check_concurrency.message}</p>}
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium">Ghi chú</label>
        <Controller
          name="note"
          control={control}
          render={({ field }) => <Input.TextArea {...field} rows={2} />}
        />
      </div>
      <div className="flex gap-1 pt-1">
        <Button type="primary" htmlType="submit" size="large" loading={busy}>
          {busy ? "Đang lưu…" : "Lưu hosting"}
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
