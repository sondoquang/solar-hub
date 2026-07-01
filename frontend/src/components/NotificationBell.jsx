import { Popover } from "antd";
import { Bell, ClipboardList } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useNewOrders } from "../api/orders.js";
import { formatVND, timeAgo, titleCaseName } from "../lib/format.js";

// Orders the user has already acknowledged are remembered in localStorage so the
// same unprocessed order doesn't keep re-alerting across reloads. We store ids
// only (no PII).
const SEEN_KEY = "solar_hub_seen_orders";

function readSeen() {
  try {
    const parsed = JSON.parse(localStorage.getItem(SEEN_KEY));
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch {
    return new Set();
  }
}

function writeSeen(set) {
  try {
    localStorage.setItem(SEEN_KEY, JSON.stringify([...set]));
  } catch {
    /* storage may be unavailable (private mode) — non-fatal */
  }
}

// Where a notification leads depends on the order's platform: WooCommerce
// orders open the Orders tab pre-filtered to unprocessed orders; Sapo orders
// live on their own "Đơn Sapo chưa thanh toán" screen (Sapo never appears on
// the Woo Orders tab). `linkFor` picks the right destination per order; the
// footer "view all" still points at the Woo unprocessed list.
const WOO_ORDERS_LINK = "/orders?status=processing";
const SAPO_ORDERS_LINK = "/sapo-unpaid-orders";

const linkFor = (order) =>
  order?.platform === "sapo" ? SAPO_ORDERS_LINK : WOO_ORDERS_LINK;

function OrderRow({ order, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-start gap-2.5 rounded px-2 py-2 text-left transition-colors hover:bg-white/5"
    >
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-500/15 text-blue-300">
        <ClipboardList size={15} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <p className="truncate text-sm font-medium text-ink">#{order.number}</p>
          <span className="shrink-0 text-xs tabular-nums text-muted">
            {timeAgo(order.date_created_woo)}
          </span>
        </div>
        <p className="truncate text-xs text-muted">
          {titleCaseName(order.customer_name) || "Khách lẻ"} · {order.site_name}
        </p>
        <p className="truncate text-xs font-medium tabular-nums text-text">
          {formatVND(order.total)}
        </p>
      </div>
    </button>
  );
}

// Bell + count badge in the topbar. Hover/click opens a popover listing the new
// unprocessed orders; each row (and the footer) navigates to the Orders tab.
export default function NotificationBell() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState(readSeen);

  const { data } = useNewOrders();
  const orders = useMemo(() => data?.results ?? [], [data]);
  const unread = orders.filter((o) => !seen.has(o.id));
  const count = unread.length;

  const markAllSeen = useCallback(() => {
    const next = new Set(orders.map((o) => o.id));
    setSeen(next);
    writeSeen(next);
  }, [orders]);

  // Following any link clears the badge and closes the popover. Pass an order
  // to land on the screen that owns it (Woo Orders vs Sapo unpaid); omit it for
  // the footer "view all", which defaults to the Woo unprocessed list.
  const goToOrders = useCallback(
    (order) => {
      markAllSeen();
      setOpen(false);
      navigate(linkFor(order));
    },
    [markAllSeen, navigate],
  );

  const panel = (
    <div className="w-80">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <p className="text-sm font-semibold text-ink">Đơn hàng chưa xử lý</p>
        {count > 0 && (
          <button
            type="button"
            onClick={markAllSeen}
            className="text-xs font-medium text-brand hover:underline"
          >
            Đánh dấu đã đọc
          </button>
        )}
      </div>

      {count === 0 ? (
        <p className="px-3 py-6 text-center text-sm text-muted">
          Không có đơn hàng mới chưa xử lý.
        </p>
      ) : (
        <div className="max-h-80 overflow-y-auto p-1">
          {unread.map((order) => (
            <OrderRow key={order.id} order={order} onClick={() => goToOrders(order)} />
          ))}
        </div>
      )}

      <button
        type="button"
        onClick={() => goToOrders()}
        className="block w-full border-t border-border px-3 py-2 text-center text-sm font-medium text-brand hover:bg-white/5"
      >
        Xem tất cả đơn chưa xử lý
      </button>
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
        className="relative rounded-full p-1.5 text-muted hover:bg-white/5 hover:text-ink"
        aria-label={count > 0 ? `Thông báo: ${count} đơn hàng chưa xử lý` : "Thông báo"}
      >
        <Bell size={20} />
        {count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold text-white">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>
    </Popover>
  );
}
