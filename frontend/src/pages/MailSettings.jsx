import { zodResolver } from "@hookform/resolvers/zod";
import { Button, Input, InputNumber, Select, Switch } from "antd";
import { Mail, Send } from "lucide-react";
import { useEffect } from "react";
import { Controller, useForm } from "react-hook-form";
import toast from "react-hot-toast";
import { z } from "zod";

import {
  useMailSettings,
  useSendTestMail,
  useUpdateMailSettings,
} from "../api/mailSettings.js";
import ErrorState from "../components/ErrorState.jsx";
import PageSkeleton from "../components/PageSkeleton.jsx";
import { useCan } from "../lib/AuthContext.jsx";
import { formatDateTime } from "../lib/format.js";

// Daily send time, "HH:MM" (00:00–23:59). Matches the backend normalizer.
const TIME_RE = /^([01]?\d|2[0-3]):[0-5]\d$/;

// Password is required only when none is saved yet; on a later edit, leaving it
// blank keeps the stored one (mirrors the site consumer_secret edit flow).
const makeSchema = (hasPassword) =>
  z
    .object({
      smtp_host: z.string().min(1, "Bắt buộc"),
      smtp_port: z.number({ invalid_type_error: "Bắt buộc" }).int().min(1).max(65535),
      use_tls: z.boolean(),
      use_ssl: z.boolean(),
      username: z.string().email("Email không hợp lệ"),
      password: hasPassword
        ? z.string().optional()
        : z.string().min(1, "Bắt buộc khi cấu hình lần đầu"),
      from_name: z.string().optional(),
      from_email: z.union([z.string().email("Email không hợp lệ"), z.literal("")]).optional(),
      recipients: z
        .array(z.string().email("Email nhận không hợp lệ"))
        .min(1, "Cần ít nhất một email nhận"),
      // Optional: empty falls back to the order-report recipients on the backend.
      product_sync_recipients: z
        .array(z.string().email("Email nhận không hợp lệ"))
        .optional(),
      product_sync_report_enabled: z.boolean(),
      digest_enabled: z.boolean(),
      digest_times: z
        .array(z.string())
        .refine((arr) => arr.every((t) => TIME_RE.test(t.trim())), {
          message: "Giờ phải dạng HH:MM (ví dụ 09:00), trong khoảng 00:00–23:59.",
        }),
    })
    // A schedule is only meaningful when the auto digest is on.
    .superRefine((v, ctx) => {
      if (v.digest_enabled && v.digest_times.length === 0) {
        ctx.addIssue({
          path: ["digest_times"],
          code: z.ZodIssueCode.custom,
          message: "Cần ít nhất một mốc giờ khi bật gửi tự động.",
        });
      }
    });

const errCls = "mt-1 text-xs text-danger";
const Req = () => <span className="ml-0.5 text-danger">*</span>;

const toForm = (data) => ({
  smtp_host: data?.smtp_host ?? "smtp.gmail.com",
  smtp_port: data?.smtp_port ?? 587,
  use_tls: data?.use_tls ?? true,
  use_ssl: data?.use_ssl ?? false,
  username: data?.username ?? "",
  password: "", // write-only; never pre-filled
  from_name: data?.from_name ?? "Solar Hub",
  from_email: data?.from_email ?? "",
  recipients: data?.recipients ?? [],
  product_sync_recipients: data?.product_sync_recipients ?? [],
  product_sync_report_enabled: data?.product_sync_report_enabled ?? true,
  digest_enabled: data?.digest_enabled ?? true,
  digest_times: data?.digest_times ?? ["09:00", "16:00"],
});

function MailSettingsForm({ data }) {
  const update = useUpdateMailSettings();
  const sendTest = useSendTestMail();
  const hasPassword = !!data?.has_password;
  const can = useCan();
  const canChange = can("mailer.change_mailsettings");
  const canTest = can("mailer.test_mailsettings");

  const {
    control,
    handleSubmit,
    reset,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(makeSchema(hasPassword)),
    defaultValues: toForm(data),
  });

  // Re-seed the form whenever the saved settings change (e.g. after a save).
  useEffect(() => {
    reset(toForm(data));
  }, [data, reset]);

  const submit = (values) => {
    const payload = { ...values };
    if (!payload.password) delete payload.password; // blank = keep stored secret
    update.mutate(payload, {
      onSuccess: () => toast.success("Đã lưu cấu hình Mail SMTP."),
      onError: (e) =>
        toast.error(e?.response?.data?.detail || "Lưu cấu hình thất bại."),
    });
  };

  // "Gửi thử" uses the SAVED SMTP account (the just-typed password isn't stored
  // until you save) but sends to ALL recipients in the form — so you can verify
  // every configured address actually receives mail, not just the first.
  const handleTest = () => {
    const recipients = getValues("recipients") ?? [];
    if (!recipients.length) {
      toast.error("Thêm ít nhất một email nhận rồi lưu trước khi gửi thử.");
      return;
    }
    sendTest.mutate(recipients, {
      onSuccess: () =>
        toast.success(
          recipients.length === 1
            ? `Đã gửi email thử tới ${recipients[0]}.`
            : `Đã gửi email thử tới ${recipients.length} địa chỉ.`,
        ),
      onError: (e) =>
        toast.error(e?.response?.data?.detail || "Gửi email thử thất bại."),
    });
  };

  const busy = update.isPending || isSubmitting;

  return (
    <form onSubmit={handleSubmit(submit)} className="grid max-w-2xl gap-4">
      <div className="grid gap-3 rounded border border-border bg-surface-raised p-4">
        <h2 className="text-sm font-semibold text-muted">Máy chủ SMTP</h2>
        <div className="grid grid-cols-[1fr_140px] gap-2">
          <div>
            <label className="mb-1 block text-sm font-medium">
              SMTP host
              <Req />
            </label>
            <Controller
              name="smtp_host"
              control={control}
              render={({ field }) => (
                <Input {...field} placeholder="smtp.gmail.com" status={errors.smtp_host ? "error" : ""} />
              )}
            />
            {errors.smtp_host && <p className={errCls}>{errors.smtp_host.message}</p>}
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">
              Port
              <Req />
            </label>
            <Controller
              name="smtp_port"
              control={control}
              render={({ field }) => (
                <InputNumber {...field} className="w-full" min={1} max={65535} />
              )}
            />
          </div>
        </div>
        <div className="flex items-center gap-6">
          <Controller
            name="use_tls"
            control={control}
            render={({ field }) => (
              <label className="flex items-center gap-2 text-sm">
                <Switch size="small" checked={!!field.value} onChange={field.onChange} />
                TLS (cổng 587)
              </label>
            )}
          />
          <Controller
            name="use_ssl"
            control={control}
            render={({ field }) => (
              <label className="flex items-center gap-2 text-sm">
                <Switch size="small" checked={!!field.value} onChange={field.onChange} />
                SSL (cổng 465)
              </label>
            )}
          />
        </div>
      </div>

      <div className="grid gap-3 rounded border border-border bg-surface-raised p-4">
        <h2 className="text-sm font-semibold text-muted">Tài khoản gửi</h2>
        <div>
          <label className="mb-1 block text-sm font-medium">
            Email gửi (tài khoản SMTP)
            <Req />
          </label>
          <Controller
            name="username"
            control={control}
            render={({ field }) => (
              <Input {...field} placeholder="ban@gmail.com" status={errors.username ? "error" : ""} />
            )}
          />
          {errors.username && <p className={errCls}>{errors.username.message}</p>}
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium">
            Mật khẩu ứng dụng
            {hasPassword ? " (để trống nếu không đổi)" : <Req />}
          </label>
          <Controller
            name="password"
            control={control}
            render={({ field }) => (
              <Input.Password
                {...field}
                placeholder={hasPassword ? "••••••••••••" : "App password 16 ký tự"}
                status={errors.password ? "error" : ""}
              />
            )}
          />
          {errors.password ? (
            <p className={errCls}>{errors.password.message}</p>
          ) : (
            <p className="mt-1 text-xs text-muted">
              Với Gmail: bật xác thực 2 bước rồi tạo “Mật khẩu ứng dụng” (App password),
              dán vào đây — không dùng mật khẩu đăng nhập thường.
            </p>
          )}
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="mb-1 block text-sm font-medium">Tên hiển thị</label>
            <Controller
              name="from_name"
              control={control}
              render={({ field }) => <Input {...field} placeholder="Solar Hub" />}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">
              Email hiển thị (tùy chọn)
            </label>
            <Controller
              name="from_email"
              control={control}
              render={({ field }) => (
                <Input
                  {...field}
                  placeholder="Mặc định = tài khoản SMTP"
                  status={errors.from_email ? "error" : ""}
                />
              )}
            />
            {errors.from_email && <p className={errCls}>{errors.from_email.message}</p>}
          </div>
        </div>
      </div>

      <div className="grid gap-3 rounded border border-border bg-surface-raised p-4">
        <h2 className="text-sm font-semibold text-muted">Báo cáo đơn hàng tự động</h2>
        <div>
          <label className="mb-1 block text-sm font-medium">
            Email nhận báo cáo
            <Req />
          </label>
          <Controller
            name="recipients"
            control={control}
            render={({ field }) => (
              <Select
                {...field}
                mode="tags"
                className="w-full"
                placeholder="Nhập email rồi nhấn Enter (có thể thêm nhiều)"
                tokenSeparators={[",", " ", ";"]}
                open={false}
                status={errors.recipients ? "error" : ""}
              />
            )}
          />
          {errors.recipients && <p className={errCls}>{errors.recipients.message}</p>}
        </div>
        <Controller
          name="digest_enabled"
          control={control}
          render={({ field }) => (
            <label className="flex items-center gap-2 text-sm">
              <Switch size="small" checked={!!field.value} onChange={field.onChange} />
              Tự động gửi báo cáo hằng ngày vào các mốc giờ bên dưới (chỉ đơn của khách hàng thật)
            </label>
          )}
        />
        <div>
          <label className="mb-1 block text-sm font-medium">
            Mốc giờ gửi hằng ngày
            <Req />
          </label>
          <Controller
            name="digest_times"
            control={control}
            render={({ field }) => (
              <Select
                {...field}
                mode="tags"
                className="w-full"
                placeholder="Nhập giờ dạng HH:MM (vd 09:00, 16:00) rồi nhấn Enter"
                tokenSeparators={[",", " ", ";"]}
                open={false}
                status={errors.digest_times ? "error" : ""}
              />
            )}
          />
          {errors.digest_times ? (
            <p className={errCls}>{errors.digest_times.message}</p>
          ) : (
            <p className="mt-1 text-xs text-muted">
              Giờ theo múi giờ Việt Nam (Asia/Ho_Chi_Minh). Có thể thêm nhiều mốc,
              ví dụ 09:00 và 16:00.
            </p>
          )}
        </div>
        {data?.last_digest_sent_at && (
          <p className="text-xs text-muted">
            Lần gửi tự động gần nhất: {formatDateTime(data.last_digest_sent_at)}
          </p>
        )}
      </div>

      <div className="grid gap-3 rounded border border-border bg-surface-raised p-4">
        <h2 className="text-sm font-semibold text-muted">Báo cáo đồng bộ sản phẩm</h2>
        <div>
          <label className="mb-1 block text-sm font-medium">Email nhận báo cáo đồng bộ</label>
          <Controller
            name="product_sync_recipients"
            control={control}
            render={({ field }) => (
              <Select
                {...field}
                mode="tags"
                className="w-full"
                placeholder="Nhập email rồi nhấn Enter (để trống = dùng email nhận báo cáo đơn hàng)"
                tokenSeparators={[",", " ", ";"]}
                open={false}
                status={errors.product_sync_recipients ? "error" : ""}
              />
            )}
          />
          {errors.product_sync_recipients ? (
            <p className={errCls}>{errors.product_sync_recipients.message}</p>
          ) : (
            <p className="mt-1 text-xs text-muted">
              Nhận email tổng hợp (kèm file Excel) sau mỗi lần đồng bộ sản phẩm xuống các site.
              Để trống sẽ dùng danh sách “Email nhận báo cáo” ở trên.
            </p>
          )}
        </div>
        <Controller
          name="product_sync_report_enabled"
          control={control}
          render={({ field }) => (
            <label className="flex items-center gap-2 text-sm">
              <Switch size="small" checked={!!field.value} onChange={field.onChange} />
              Gửi email báo cáo sau khi đồng bộ sản phẩm hoàn tất
            </label>
          )}
        />
      </div>

      {(canChange || canTest) && (
        <div className="flex gap-2">
          {canChange && (
            <Button type="primary" htmlType="submit" icon={<Mail size={16} />} loading={busy}>
              {busy ? "Đang lưu…" : "Lưu cấu hình"}
            </Button>
          )}
          {canTest && (
            <Button icon={<Send size={16} />} loading={sendTest.isPending} onClick={handleTest}>
              Gửi email thử
            </Button>
          )}
        </div>
      )}
    </form>
  );
}

export default function MailSettings() {
  const { data, isLoading, isError, refetch } = useMailSettings();

  return (
    <section className="pt-4">
      <div className="mb-4">
        <h1 className="font-display text-2xl font-bold">Cấu hình Mail SMTP</h1>
        <p className="mt-1 text-sm text-muted">
          Tài khoản email dùng để gửi báo cáo đơn hàng tự động theo lịch và
          gửi đơn thủ công từ trang Đơn hàng.
        </p>
      </div>

      {isLoading ? (
        <PageSkeleton stats={0} filters={false} />
      ) : isError ? (
        <ErrorState message="Không tải được cấu hình Mail" onRetry={refetch} />
      ) : (
        <MailSettingsForm data={data} />
      )}
    </section>
  );
}
