import {
  BarChart3,
  Bell,
  ChevronDown,
  ChevronUp,
  ClipboardList,
  Globe,
  Headphones,
  LayoutGrid,
  LogOut,
  Package,
  Settings,
  SunMedium,
  Users,
} from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

// Top-level nav. Items with a real route use NavLink; the rest are visual
// placeholders for sections not yet built (kept to match the product design).
const MAIN_NAV = [
  { to: "/", label: "Tổng quan", icon: LayoutGrid, end: true },
  { to: "/orders", label: "Đơn hàng", icon: ClipboardList },
  { to: "/products", label: "Sản phẩm", icon: Package },
  { label: "Khách hàng", icon: Users },
];

const WEBSITE_SUB = [
  { to: "/sites", label: "Quản lý website" },
  { label: "Import Excel" },
  { label: "Lịch sử kiểm tra" },
  { label: "Cài đặt" },
];

const SECONDARY_NAV = [
  { label: "Báo cáo", icon: BarChart3 },
  { label: "Cài đặt hệ thống", icon: Settings },
];

const itemBase =
  "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors";

function navClass({ isActive }) {
  return [
    itemBase,
    isActive ? "bg-amber-50 text-brand" : "text-slate-600 hover:bg-slate-50 hover:text-ink",
  ].join(" ");
}

// A nav row that either navigates (has `to`) or is an inert placeholder.
function NavRow({ item }) {
  const { to, end, label, icon: Icon } = item;
  if (to) {
    return (
      <NavLink to={to} end={end} className={navClass}>
        <Icon size={18} />
        {label}
      </NavLink>
    );
  }
  return (
    <button
      type="button"
      className={`${itemBase} cursor-default text-slate-600 hover:bg-slate-50`}
      title="Sắp ra mắt"
    >
      <Icon size={18} />
      {label}
    </button>
  );
}

function Sidebar() {
  const { pathname } = useLocation();
  const websiteActive = pathname.startsWith("/sites");
  const [websiteOpen, setWebsiteOpen] = useState(websiteActive);

  return (
    <aside className="sticky top-0 flex h-screen w-64 shrink-0 flex-col border-r border-slate-100 bg-white">
      <div className="flex items-center gap-2.5 px-6 py-5">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand text-ink">
          <SunMedium size={22} />
        </span>
        <span className="font-display text-xl font-bold">
          <span className="text-ink">Solar</span> <span className="text-brand">Hub</span>
        </span>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
        {MAIN_NAV.map((item) => (
          <NavRow key={item.label} item={item} />
        ))}

        {/* Website — expandable section, active on /sites */}
        <div>
          <button
            type="button"
            onClick={() => setWebsiteOpen((v) => !v)}
            aria-expanded={websiteOpen}
            className={[
              itemBase,
              "justify-between",
              websiteActive ? "bg-amber-50 text-brand" : "text-slate-600 hover:bg-slate-50 hover:text-ink",
            ].join(" ")}
          >
            <span className="flex items-center gap-3">
              <Globe size={18} />
              Website
            </span>
            {websiteOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
          {websiteOpen && (
            <div className="mt-1 space-y-0.5 pl-4">
              {WEBSITE_SUB.map((sub) =>
                sub.to ? (
                  <NavLink
                    key={sub.label}
                    to={sub.to}
                    className={({ isActive }) =>
                      [
                        "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                        isActive
                          ? "bg-amber-50 font-medium text-brand"
                          : "text-slate-500 hover:bg-slate-50 hover:text-ink",
                      ].join(" ")
                    }
                  >
                    <span className="h-1.5 w-1.5 rounded-full bg-current" />
                    {sub.label}
                  </NavLink>
                ) : (
                  <button
                    key={sub.label}
                    type="button"
                    className="flex w-full cursor-default items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-slate-500 hover:bg-slate-50"
                    title="Sắp ra mắt"
                  >
                    <span className="h-1.5 w-1.5 rounded-full bg-slate-300" />
                    {sub.label}
                  </button>
                )
              )}
            </div>
          )}
        </div>

        {SECONDARY_NAV.map((item) => (
          <NavRow key={item.label} item={item} />
        ))}

        <NavLink to="/login" className={navClass}>
          <LogOut size={18} />
          Đăng xuất
        </NavLink>
      </nav>

      <div className="m-3 rounded-xl bg-slate-50 p-4">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Headphones size={18} className="text-brand" />
          Hỗ trợ
        </div>
        <p className="mt-2 text-xs text-muted">support@solarpower.vn</p>
        <p className="text-xs text-muted">1900 9999</p>
      </div>
    </aside>
  );
}

function Topbar() {
  return (
    <header className="flex items-center justify-end gap-5 px-8 py-4">
      <button
        type="button"
        className="relative rounded-full p-2 text-slate-500 hover:bg-slate-100 hover:text-ink"
        aria-label="Thông báo"
      >
        <Bell size={20} />
        <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold text-white">
          3
        </span>
      </button>
      <div className="flex items-center gap-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-200 text-sm font-semibold text-slate-600">
          NA
        </span>
        <div className="text-right text-sm leading-tight">
          <p className="font-semibold">Nguyễn Văn A</p>
          <p className="text-xs text-muted">Quản trị viên</p>
        </div>
        <ChevronDown size={16} className="text-slate-400" />
      </div>
    </header>
  );
}

export default function AppLayout() {
  return (
    <div className="flex min-h-screen bg-surface">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <main className="flex-1 px-8 pb-10">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
