import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

const makeSchema = (mode) =>
  z.object({
    name: z.string().min(1, "Bắt buộc"),
    base_url: z.string().url("URL không hợp lệ"),
    consumer_key: z.string().min(1, "Bắt buộc"),
    consumer_secret:
      mode === "edit" ? z.string().optional() : z.string().min(1, "Bắt buộc"),
  });

const field = "w-full rounded border px-3 py-2 text-sm";
const errCls = "mt-1 text-xs text-danger";

const EMPTY = { name: "", base_url: "", consumer_key: "", consumer_secret: "" };

export default function SiteRegisterForm({ onSubmit, onCancel, pending, mode = "create", defaultValues }) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(makeSchema(mode)),
    defaultValues: { ...EMPTY, ...defaultValues, consumer_secret: "" },
  });

  const submit = async (values) => {
    // On edit, an empty secret means "keep the current one" — don't send it.
    if (mode === "edit" && !values.consumer_secret) delete values.consumer_secret;
    await onSubmit(values, { onSuccess: () => reset({ ...EMPTY }) });
  };

  const busy = pending || isSubmitting;

  return (
    <form onSubmit={handleSubmit(submit)} className="grid gap-3">
      <div>
        <label className="text-sm font-medium">Tên site</label>
        <input className={field} {...register("name")} aria-invalid={!!errors.name} />
        {errors.name && <p className={errCls}>{errors.name.message}</p>}
      </div>
      <div>
        <label className="text-sm font-medium">Base URL</label>
        <input
          className={field}
          placeholder="https://shop.example.com"
          {...register("base_url")}
          aria-invalid={!!errors.base_url}
        />
        {errors.base_url && <p className={errCls}>{errors.base_url.message}</p>}
      </div>
      <div>
        <label className="text-sm font-medium">Consumer key</label>
        <input className={field} {...register("consumer_key")} aria-invalid={!!errors.consumer_key} />
        {errors.consumer_key && <p className={errCls}>{errors.consumer_key.message}</p>}
      </div>
      <div>
        <label className="text-sm font-medium">
          Consumer secret{mode === "edit" && " (để trống nếu không đổi)"}
        </label>
        <input
          type="password"
          className={field}
          {...register("consumer_secret")}
          aria-invalid={!!errors.consumer_secret}
        />
        {errors.consumer_secret && <p className={errCls}>{errors.consumer_secret.message}</p>}
      </div>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          className="rounded bg-brand px-4 py-2 font-medium text-ink disabled:opacity-50"
        >
          {busy ? "Đang lưu…" : "Lưu site"}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel} className="rounded border px-4 py-2 font-medium">
            Hủy
          </button>
        )}
      </div>
    </form>
  );
}
