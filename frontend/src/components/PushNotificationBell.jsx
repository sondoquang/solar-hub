import { Popover } from "antd";
import { CircleCheck, Loader, PackageCheck, TriangleAlert } from "lucide-react";
import { useState } from "react";

import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from "../api/notifications.js";
import { timeAgo } from "../lib/format.js";
import { usePushNotifications } from "../lib/PushNotificationContext.jsx";

// Short label for which products a run pushed (from the trigger-time snapshot).
function productLabel(summary) {
  const s = summary || {};
  if (s.all_products) return "Toàn bộ catalog";
  const products = s.products || [];
  if (s.product_count === 1 || products.length === 1) return products[0]?.name || "1 sản phẩm";
  return `${s.product_count ?? products.length} sản phẩm`;
}

// Icon + one-line status for a notification row.
function statusMeta(n) {
  const s = n.summary || {};
  const notOk = (s.error ?? 0) + (s.partial ?? 0);
  if (n.status === "running") {
    return {
      icon: <Loader size={15} className="animate-spin text-info" />,
      text: `Đang đồng bộ… ${n.expected} site`,
      tone: "text-muted",
    };
  }
  if (n.status === "timeout") {
    return {
      icon: <TriangleAlert size={15} className="text-warning" />,
      text: "Chạy lâu hơn dự kiến — kiểm tra lại",
      tone: "text-warning",
    };
  }
  if (notOk) {
    return {
      icon: <TriangleAlert size={15} className="text-warning" />,
      text: `${s.success ?? 0}/${s.site_count ?? n.expected} site OK · ${notOk} site cần xem`,
      tone: "text-warning",
    };
  }
  return {
    icon: <CircleCheck size={15} className="text-success" />,
    text: `Đã đồng bộ ${s.site_count ?? n.expected} site`,
    tone: "text-success",
  };
}

function NotificationRow({ notif, onClick }) {
  const meta = statusMeta(notif);
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "flex w-full items-start gap-2.5 rounded px-2 py-2 text-left transition-colors hover:bg-overlay/5",
        notif.read ? "" : "bg-overlay/[0.04]",
      ].join(" ")}
    >
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-500/15">
        {meta.icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <p className="truncate text-sm font-medium text-ink">{productLabel(notif.summary)}</p>
          <span className="shrink-0 text-xs tabular-nums text-muted">
            {timeAgo(notif.created_at)}
          </span>
        </div>
        <p className={`truncate text-xs ${meta.tone}`}>{meta.text}</p>
      </div>
      {!notif.read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand" />}
    </button>
  );
}

// Bell + unread badge for product-push notifications (separate from the order
// bell). The popover lists recent pushes; a row reopens that run's result modal
// (via the app-wide PushNotificationProvider) and marks it read.
export default function PushNotificationBell() {
  const [open, setOpen] = useState(false);
  const { data } = useNotifications();
  const { openRun } = usePushNotifications();
  const markRead = useMarkNotificationRead();
  const markAll = useMarkAllNotificationsRead();

  const rows = data?.results ?? [];
  const count = data?.unread ?? 0;

  const handleRow = (notif) => {
    setOpen(false);
    openRun(notif.run_id);
    if (!notif.read) markRead.mutate(notif.id);
  };

  const panel = (
    <div className="w-96">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <p className="text-sm font-semibold text-ink">Thông báo đẩy sản phẩm</p>
        {count > 0 && (
          <button
            type="button"
            onClick={() => markAll.mutate()}
            className="text-xs font-medium text-brand hover:underline"
          >
            Đánh dấu đã đọc
          </button>
        )}
      </div>

      {rows.length === 0 ? (
        <p className="px-3 py-6 text-center text-sm text-muted">Chưa có lần đẩy sản phẩm nào.</p>
      ) : (
        <div className="max-h-96 overflow-y-auto p-1">
          {rows.map((notif) => (
            <NotificationRow key={notif.id} notif={notif} onClick={() => handleRow(notif)} />
          ))}
        </div>
      )}
    </div>
  );

  return (
    <Popover
      content={panel}
      trigger={["hover", "click"]}
      placement="bottomRight"
      open={open}
      onOpenChange={setOpen}
      mouseLeaveDelay={0.2}
      styles={{ body: { padding: 0 } }}
      arrow={false}
    >
      <button
        type="button"
        className="relative rounded-full p-1.5 text-muted hover:bg-overlay/5 hover:text-ink"
        aria-label={count > 0 ? `Thông báo đẩy sản phẩm: ${count} chưa đọc` : "Thông báo đẩy sản phẩm"}
      >
        <PackageCheck size={20} />
        {count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold text-white">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>
    </Popover>
  );
}
