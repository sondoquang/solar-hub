import { zodResolver } from "@hookform/resolvers/zod";
import { Button, Input, Select, Switch } from "antd";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

import { hostingLabel } from "../api/hostings.js";

const makeSchema = (mode) =>
  z.object({
    name: z.string().min(1, "Bắt buộc"),
    base_url: z.string().url("URL không hợp lệ"),
    platform: z.enum(["woocommerce", "sapo"]),
    consumer_key: z.string().min(1, "Bắt buộc"),
    consumer_secret: mode === "edit" ? z.string().optional() : z.string().min(1, "Bắt buộc"),
    hosting: z.number().nullable().optional(),
    is_primary: z.boolean().optional(),
  });

// Per-platform credential labels: the backend stores both pairs in the same
// consumer_key/consumer_secret fields, only the meaning differs.
const PLATFORM_OPTIONS = [
  { value: "woocommerce", label: "WooCommerce" },
  { value: "sapo", label: "Sapo Web" },
];
const PLATFORM_UI = {
  woocommerce: {
    urlPlaceholder: "https://shop.example.com",
    keyLabel: "Consumer key",
    secretLabel: "Consumer secret",
    hint: "REST API key của WooCommerce (WooCommerce → Settings → Advanced → REST API).",
  },
  sapo: {
    urlPlaceholder: "https://store.mysapo.net",
    keyLabel: "API key",
    secretLabel: "API secret",
    hint: "Tạo Ứng dụng riêng (Private App) trong Sapo Web của store này để lấy API key/secret.",
  },
};

const errCls = "mt-1 text-xs text-danger";
const Req = () => <span className="ml-0.5 text-danger">*</span>;
const EMPTY = {
  name: "",
  base_url: "",
  platform: "woocommerce",
  consumer_key: "",
  consumer_secret: "",
  hosting: null,
  is_primary: false,
};

export default function SiteRegisterForm({
  onSubmit,
  onCancel,
  pending,
  mode = "create",
  defaultValues,
  hostings = [],
}) {
  const {
    control,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(makeSchema(mode)),
    defaultValues: { ...EMPTY, ...defaultValues, consumer_secret: "" },
  });

  const platformUi = PLATFORM_UI[watch("platform")] ?? PLATFORM_UI.woocommerce;

  const submit = async (values) => {
    if (mode === "edit" && !values.consumer_secret) delete values.consumer_secret;
    await onSubmit(values, { onSuccess: () => reset({ ...EMPTY }) });
  };

  const busy = pending || isSubmitting;

  return (
    <form onSubmit={handleSubmit(submit)} className="grid gap-2">
      <div>
        <label className="mb-1 block text-sm font-medium">
          Tên site
          <Req />
        </label>
        <Controller
          name="name"
          control={control}
          render={({ field }) => <Input {...field} status={errors.name ? "error" : ""} />}
        />
        {errors.name && <p className={errCls}>{errors.name.message}</p>}
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium">
          Nền tảng
          <Req />
        </label>
        <Controller
          name="platform"
          control={control}
          render={({ field }) => (
            <Select {...field} className="w-full" options={PLATFORM_OPTIONS} />
          )}
        />
        <p className="mt-1 text-xs text-muted">{platformUi.hint}</p>
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium">
          Base URL
          <Req />
        </label>
        <Controller
          name="base_url"
          control={control}
          render={({ field }) => (
            <Input
              {...field}
              placeholder={platformUi.urlPlaceholder}
              status={errors.base_url ? "error" : ""}
            />
          )}
        />
        {errors.base_url && <p className={errCls}>{errors.base_url.message}</p>}
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium">
          {platformUi.keyLabel}
          <Req />
        </label>
        <Controller
          name="consumer_key"
          control={control}
          render={({ field }) => <Input {...field} status={errors.consumer_key ? "error" : ""} />}
        />
        {errors.consumer_key && <p className={errCls}>{errors.consumer_key.message}</p>}
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium">
          {platformUi.secretLabel}
          {mode === "edit" ? " (để trống nếu không đổi)" : <Req />}
        </label>
        <Controller
          name="consumer_secret"
          control={control}
          render={({ field }) => (
            <Input.Password {...field} status={errors.consumer_secret ? "error" : ""} />
          )}
        />
        {errors.consumer_secret && <p className={errCls}>{errors.consumer_secret.message}</p>}
      </div>
      <div>
        <label className="mb-1 block text-sm font-medium">Hosting</label>
        <Controller
          name="hosting"
          control={control}
          render={({ field }) => (
            <Select
              {...field}
              className="w-full"
              allowClear
              placeholder="Chọn hosting (tùy chọn)"
              options={hostings.map((h) => ({ value: h.id, label: hostingLabel(h) }))}
              onChange={(v) => field.onChange(v ?? null)}
            />
          )}
        />
      </div>
      <div className="flex items-center gap-2">
        <Controller
          name="is_primary"
          control={control}
          render={({ field }) => (
            <Switch size="small" checked={!!field.value} onChange={field.onChange} />
          )}
        />
        <span className="text-sm font-medium">Trang chính</span>
        <span className="text-xs text-muted">(ưu tiên kiểm tra trước mỗi ngày)</span>
      </div>
      <div className="flex gap-1 pt-1">
        <Button type="primary" htmlType="submit" loading={busy}>
          {busy ? "Đang lưu…" : "Lưu site"}
        </Button>
        {onCancel && <Button onClick={onCancel}>Hủy</Button>}
      </div>
    </form>
  );
}
