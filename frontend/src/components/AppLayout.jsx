import {
  BarChart3,
  Bell,
  ChevronDown,
  ChevronUp,
  ClipboardList,
  Globe,
  LayoutGrid,
  LogOut,
  Package,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Settings,
  SunMedium,
  Users,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigation } from "react-router-dom";

import { useAuth } from "../lib/AuthContext.jsx";
import UserMenu from "./UserMenu.jsx";

// Sidebar header. Expanded: full brand logo. Collapsed: compact icon mark.
function Logo({ collapsed }) {
  const [imgError, setImgError] = useState(false);
  if (imgError) {
    return (
      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand text-white">
        <SunMedium size={22} />
      </span>
    );
  }
  return (
    <img
      src={collapsed ? "/logo.png" : "/logo-admin-page.png"}
      alt="Solar Hub"
      className={collapsed ? "h-9 w-9 object-contain" : "h-16 w-auto object-contain"}
      onError={() => setImgError(true)}
    />
  );
}

// Top-level nav. Items with a real route use NavLink; the rest are visual
// placeholders for sections not yet built (kept to match the product design).
const MAIN_NAV = [
  { to: "/", label: "Tổng quan", icon: LayoutGrid, end: true },
  { to: "/orders", label: "Đơn hàng", icon: ClipboardList },
  { to: "/products", label: "Sản phẩm", icon: Package },
  { label: "Khách hàng", icon: Users },
];

const WEBSITE_SUB = [
  { to: "/hostings", label: "Hosting" },
  { to: "/sites", label: "Quản lý website" },
  { to: "/health-checks", label: "Lịch sử kiểm tra" },
];

const SECONDARY_NAV = [
  { label: "Báo cáo", icon: BarChart3 },
  { label: "Cài đặt hệ thống", icon: Settings },
];

const itemBase =
  "flex w-full items-center gap-3 rounded px-2 py-3 text-sm font-medium transition-colors border-0";

function navClass(collapsed) {
  return ({ isActive }) =>
    [
      itemBase,
      collapsed && "justify-center",
      isActive ? "bg-amber-50 text-brand" : "text-slate-600 hover:bg-slate-50 hover:text-ink",
    ]
      .filter(Boolean)
      .join(" ");
}

// A nav row that either navigates (has `to`) or is an inert placeholder.
// When `collapsed`, only the icon shows and the label moves to a tooltip.
function NavRow({ item, collapsed }) {
  const { to, end, label, icon: Icon } = item;
  if (to) {
    return (
      <NavLink
        to={to}
        end={end}
        className={navClass(collapsed)}
        title={collapsed ? label : undefined}
      >
        <Icon size={18} />
        {!collapsed && label}
      </NavLink>
    );
  }
  return (
    <button
      type="button"
      className={[
        itemBase,
        "cursor-default text-slate-600 hover:bg-slate-50",
        collapsed && "justify-center",
      ]
        .filter(Boolean)
        .join(" ")}
      title={collapsed ? label : "Sắp ra mắt"}
    >
      <Icon size={18} />
      {!collapsed && label}
    </button>
  );
}

function LogoutButton({ collapsed }) {
  const { logout } = useAuth();
  return (
    <button
      type="button"
      onClick={logout}
      title={collapsed ? "Đăng xuất" : undefined}
      className={[
        itemBase,
        "text-slate-600 hover:bg-slate-50 hover:text-ink",
        collapsed && "justify-center",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <LogOut size={18} />
      {!collapsed && "Đăng xuất"}
    </button>
  );
}

function Sidebar() {
  const { pathname } = useLocation();
  const websiteActive =
    pathname.startsWith("/sites") ||
    pathname.startsWith("/hostings") ||
    pathname.startsWith("/health-checks");
  const [collapsed, setCollapsed] = useState(false);
  const [websiteOpen, setWebsiteOpen] = useState(websiteActive);

  return (
    <aside
      className={[
        "sticky top-0 flex h-screen shrink-0 flex-col border-r border-slate-100 bg-white transition-[width] duration-300 ease-in-out",
        collapsed ? "w-16" : "w-[220px]",
      ].join(" ")}
    >
      {/* Header: brand logo + collapse toggle */}
      <div
        className={[
          "flex items-center px-3 py-2.5",
          collapsed ? "flex-col gap-2" : "justify-between gap-2",
        ].join(" ")}
      >
        <Logo collapsed={collapsed} />
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          aria-label={collapsed ? "Mở rộng menu" : "Thu gọn menu"}
          title={collapsed ? "Mở rộng" : "Thu gọn"}
          className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-ink"
        >
          {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
        </button>
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto px-4 py-1">
        {MAIN_NAV.map((item) => (
          <NavRow key={item.label} item={item} collapsed={collapsed} />
        ))}

        {/* Website — expandable section, active on /sites */}
        {collapsed ? (
          <NavLink to="/sites" title="Website" className={navClass(true)}>
            <Globe size={18} />
          </NavLink>
        ) : (
          <div>
            <button
              type="button"
              onClick={() => setWebsiteOpen((v) => !v)}
              aria-expanded={websiteOpen}
              className={[
                itemBase,
                "cursor-pointer justify-between",
                websiteActive
                  ? "bg-amber-50 text-brand"
                  : "text-slate-600 hover:bg-slate-50 hover:text-ink",
              ].join(" ")}
            >
              <span className="flex items-center gap-3">
                <Globe size={18} />
                Website
              </span>
              {websiteOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
            <div
              className={[
                "overflow-hidden transition-all duration-300 ease-in-out",
                websiteOpen ? "max-h-40 opacity-100" : "max-h-0 opacity-0",
              ].join(" ")}
            >
              <div className="mt-0.5 space-y-0.5 pl-2">
                {WEBSITE_SUB.map((sub) =>
                  sub.to ? (
                    <NavLink
                      key={sub.label}
                      to={sub.to}
                      className={({ isActive }) =>
                        [
                          "flex cursor-pointer items-center gap-2.5 rounded px-2 py-3 text-sm transition-colors",
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
                      className="flex w-full cursor-pointer items-center gap-2.5 rounded px-2 py-3 text-sm text-slate-500 hover:bg-slate-50"
                      title="Sắp ra mắt"
                    >
                      <span className="h-1.5 w-1.5 rounded-full bg-slate-300" />
                      {sub.label}
                    </button>
                  ),
                )}
              </div>
            </div>
          </div>
        )}

        {SECONDARY_NAV.map((item) => (
          <NavRow key={item.label} item={item} collapsed={collapsed} />
        ))}

        <LogoutButton collapsed={collapsed} />
      </nav>
    </aside>
  );
}

// Yellow progress bar that runs left→right while a route is loading.
function TopProgressBar({ loading }) {
  const [width, setWidth] = useState(0);
  const [visible, setVisible] = useState(false);
  const timerRef = useRef(null);

  useEffect(() => {
    const clear = () => clearTimeout(timerRef.current);
    if (loading) {
      clear();
      setVisible(true);
      setWidth(0);
      // Double-rAF so the browser paints width:0 before transitioning to 75%.
      requestAnimationFrame(() => requestAnimationFrame(() => setWidth(75)));
    } else if (visible) {
      setWidth(100);
      timerRef.current = setTimeout(() => {
        setVisible(false);
        setWidth(0);
      }, 400);
    }
    return clear;
  }, [loading]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!visible) return null;

  return (
    <div
      className="absolute inset-x-0 bottom-0 bg-brand"
      style={{
        height: "3px",
        width: `${width}%`,
        transition: loading ? "width 600ms ease-out" : "width 200ms ease-in",
      }}
    />
  );
}

function Topbar() {
  const { state } = useNavigation();
  const loading = state !== "idle";

  return (
    <header className="relative flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-2">
      <TopProgressBar loading={loading} />

      {/* Search */}
      <div className="w-[560px]">
        <label className="flex cursor-text items-center gap-2.5 rounded-md bg-slate-100 px-4 py-2 text-sm text-slate-400 transition-all focus-within:bg-white focus-within:ring-2 focus-within:ring-brand/40">
          <Search size={16} className="shrink-0 text-slate-400" />
          <input
            type="text"
            placeholder="Tìm kiếm (Ctrl + K)"
            className="w-full bg-transparent outline-none  border-noneplaceholder:text-slate-400"
          />
        </label>
      </div>

      {/* Right actions */}
      <div className="ml-auto flex items-center gap-1.5">
        <button
          type="button"
          className="relative rounded-full p-1.5 text-slate-500 hover:bg-slate-100 hover:text-ink"
          aria-label="Thông báo"
        >
          <Bell size={20} />
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold text-white">
            3
          </span>
        </button>
        <UserMenu />
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
        <main className="flex-1 px-4 pb-5">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
