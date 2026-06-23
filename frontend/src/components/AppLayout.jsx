import { useIsFetching, useIsMutating } from "@tanstack/react-query";
import {
  BarChart3,
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
} from "lucide-react";
import NProgress from "nprogress";
import "nprogress/nprogress.css";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../lib/AuthContext.jsx";
import NotificationBell from "./NotificationBell.jsx";
import UserMenu from "./UserMenu.jsx";

NProgress.configure({
  showSpinner: false,
  trickleSpeed: 120,
  minimum: 0.1,
  // Mount inside the topbar so the bar positions relative to the content column
  // (right of the sidebar) and sits at the header's bottom edge — see index.css.
  parent: "#app-topbar",
});

// Sidebar header brand mark (logo.png) — larger when expanded, slightly
// smaller when collapsed. Falls back to a SunMedium glyph if the image fails.
function Logo({ collapsed }) {
  const [imgError, setImgError] = useState(false);
  if (imgError) {
    return (
      <span
        className={[
          "flex items-center justify-center rounded-lg bg-brand text-[#16171a]",
          collapsed ? "h-12 w-12" : "h-9 w-9",
        ].join(" ")}
      >
        <SunMedium size={collapsed ? 28 : 22} />
      </span>
    );
  }
  return (
    <img
      src="/logo-v02.png"
      alt="Solar Hub"
      className={collapsed ? "h-12 w-12 object-contain" : "h-16 w-full object-contain"}
      onError={() => setImgError(true)}
    />
  );
}

// Top-level nav. Items with a real route use NavLink; items with `children`
// render as an expandable group (NavGroup); the rest are visual placeholders
// for sections not yet built (kept to match the product design).
const MAIN_NAV = [
  { to: "/", label: "Tổng quan", icon: LayoutGrid, end: true },
  {
    label: "Đơn hàng",
    icon: ClipboardList,
    to: "/orders", // collapsed-mode target
    children: [
      { to: "/orders", label: "WooCommerce" },
      { to: "/sapo-unpaid-orders", label: "Sapo" },
    ],
  },
  {
    label: "Sản phẩm",
    icon: Package,
    to: "/products", // collapsed-mode target
    children: [
      { to: "/products", label: "Danh sách sản phẩm" },
      { to: "/categories", label: "Danh mục" },
    ],
  },
];

const WEBSITE_NAV = {
  label: "Website",
  icon: Globe,
  to: "/sites", // collapsed-mode target
  children: [
    { to: "/hostings", label: "Hosting" },
    { to: "/sites", label: "Quản lý website" },
    { to: "/health-checks", label: "Lịch sử kiểm tra" },
  ],
};

const SECONDARY_NAV = [
  { to: "/reports", label: "Báo cáo", icon: BarChart3 },
  { label: "Cài đặt hệ thống", icon: Settings },
];

const itemBase =
  "flex w-full items-center gap-3 rounded px-2 py-3 text-base font-medium transition-colors border-0";

function navClass(collapsed) {
  return ({ isActive }) =>
    [
      itemBase,
      collapsed && "justify-center",
      isActive ? "bg-brand/15 text-brand" : "text-muted hover:bg-white/5 hover:text-ink",
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
        <Icon size={18} className="shrink-0" />
        {!collapsed && label}
      </NavLink>
    );
  }
  return (
    <button
      type="button"
      className={[
        itemBase,
        "cursor-default text-muted hover:bg-white/5",
        collapsed && "justify-center",
      ]
        .filter(Boolean)
        .join(" ")}
      title={collapsed ? label : "Sắp ra mắt"}
    >
      <Icon size={18} className="shrink-0" />
      {!collapsed && label}
    </button>
  );
}

// One sub-link inside an expanded NavGroup, drawn as a branch of a tree rather
// than a bulleted row. Two dashed pseudo-elements form the connectors:
//   `before` = the vertical trunk down the left. Full height on middle rows so
//     it chains into the next row; half height on the last row to make the └
//     corner; extended slightly upward on the first row so the line appears to
//     drop straight out of the parent's icon.
//   `after`  = the horizontal branch from the trunk into the label.
// Both need an explicit empty `content` (Tailwind doesn't add it). Lines use
// border-strong so they read on the dark surface. Replaces the old leading dot.
function SubNavRow({ sub, isFirst, isLast }) {
  // border-0 first: preflight is disabled (tailwind.config.js), so unset sides
  // keep CSS's default ~3px width and border-dashed would draw all four. Zero
  // them, then add a single 1px dashed side.
  const trunkBase =
    "before:absolute before:left-0 before:w-0 before:border-0 before:border-l before:border-dashed before:border-border-strong before:content-['']";
  // The submenu wrapper is overflow-hidden (expand animation), so the trunk
  // can only reach up to the wrapper's top edge — i.e. the parent row's bottom.
  // The first row extends up by the container's mt-0.5 (2px) to touch it.
  const trunkSize = isLast
    ? "before:top-0 before:h-1/2"
    : isFirst
      ? "before:-top-0.5 before:h-[calc(100%_+_2px)]"
      : "before:top-0 before:h-full";
  const branch =
    "after:absolute after:left-0 after:top-1/2 after:h-0 after:w-4 after:border-0 after:border-t after:border-dashed after:border-border-strong after:content-['']";

  const rowBase = [
    "relative flex cursor-pointer items-center rounded py-3 pl-6 pr-2 text-base transition-colors",
    trunkBase,
    trunkSize,
    branch,
  ].join(" ");

  if (sub.to) {
    return (
      <NavLink
        to={sub.to}
        className={({ isActive }) =>
          [
            rowBase,
            isActive
              ? "bg-brand/15 font-medium text-brand"
              : "text-muted hover:bg-white/5 hover:text-ink",
          ].join(" ")
        }
      >
        {sub.label}
      </NavLink>
    );
  }
  return (
    <button
      type="button"
      className={`${rowBase} w-full text-muted hover:bg-white/5`}
      title="Sắp ra mắt"
    >
      {sub.label}
    </button>
  );
}

// Expandable nav section with sub-links (e.g. Sản phẩm, Website). Collapsed
// sidebar shows just the icon linking to the group's main route; expanded it
// toggles a sub-list. Starts open when the current route belongs to the group.
function NavGroup({ item, collapsed, open, onToggle }) {
  const { pathname } = useLocation();
  const { to, label, icon: Icon, children } = item;
  const active = children.some((sub) => sub.to && pathname.startsWith(sub.to));

  if (collapsed) {
    return (
      <NavLink to={to} title={label} className={navClass(true)}>
        <Icon size={18} className="shrink-0" />
      </NavLink>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className={[
          itemBase,
          "cursor-pointer justify-between",
          active ? "bg-brand/15 text-brand" : "text-muted hover:bg-white/5 hover:text-ink",
        ].join(" ")}
      >
        <span className="flex items-center gap-3">
          <Icon size={18} className="shrink-0" />
          {label}
        </span>
        {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>
      <div
        className={[
          "overflow-hidden transition-all duration-300 ease-in-out",
          open ? "max-h-40 opacity-100" : "max-h-0 opacity-0",
        ].join(" ")}
      >
        {/* ml-[17px] lines the dashed trunk up under the parent icon's centre
            (parent row: px-2 = 8px + half of an 18px icon = 17px). */}
        <div className="mt-0.5 ml-[17px] space-y-0.5">
          {children.map((sub, i) => (
            <SubNavRow
              key={sub.label}
              sub={sub}
              isFirst={i === 0}
              isLast={i === children.length - 1}
            />
          ))}
        </div>
      </div>
    </div>
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
        "text-muted hover:bg-white/5 hover:text-ink",
        collapsed && "justify-center",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <LogOut size={18} className="shrink-0" />
      {!collapsed && "Đăng xuất"}
    </button>
  );
}

// All expandable groups, in render order. Used to derive which group should
// start open based on the current route.
const NAV_GROUPS = [...MAIN_NAV.filter((item) => item.children), WEBSITE_NAV];

function Sidebar() {
  const { pathname } = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  // Only one group is open at a time (accordion). Initialise to the group that
  // owns the current route, if any.
  const [openGroup, setOpenGroup] = useState(
    () =>
      NAV_GROUPS.find((group) =>
        group.children.some((sub) => sub.to && pathname.startsWith(sub.to)),
      )?.label ?? null,
  );

  const toggleGroup = (label) => setOpenGroup((current) => (current === label ? null : label));

  return (
    <aside
      className={[
        "sticky top-0 flex h-screen shrink-0 flex-col border-r border-border bg-surface-raised transition-[width] duration-300 ease-in-out",
        collapsed ? "w-16" : "w-[220px]",
      ].join(" ")}
    >
      {/* Header: brand logo + collapse toggle */}
      <div
        className={[
          "flex items-center py-2.5",
          collapsed ? "flex-col gap-2 px-2" : "justify-between gap-2 px-3",
        ].join(" ")}
      >
        <Logo collapsed={collapsed} />
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          aria-label={collapsed ? "Mở rộng menu" : "Thu gọn menu"}
          title={collapsed ? "Mở rộng" : "Thu gọn"}
          className="rounded p-1 text-muted hover:bg-white/5 hover:text-ink"
        >
          {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
        </button>
      </div>

      <nav
        className={[
          "flex-1 space-y-0.5 overflow-y-auto py-1",
          collapsed ? "px-2" : "px-4",
        ].join(" ")}
      >
        {MAIN_NAV.map((item) =>
          item.children ? (
            <NavGroup
              key={item.label}
              item={item}
              collapsed={collapsed}
              open={openGroup === item.label}
              onToggle={() => toggleGroup(item.label)}
            />
          ) : (
            <NavRow key={item.label} item={item} collapsed={collapsed} />
          ),
        )}

        <NavGroup
          item={WEBSITE_NAV}
          collapsed={collapsed}
          open={openGroup === WEBSITE_NAV.label}
          onToggle={() => toggleGroup(WEBSITE_NAV.label)}
        />

        {SECONDARY_NAV.map((item) => (
          <NavRow key={item.label} item={item} collapsed={collapsed} />
        ))}

        <LogoutButton collapsed={collapsed} />
      </nav>
    </aside>
  );
}

// Drives NProgress off React Query's in-flight queries/mutations — the real
// loading signal here, since routes use React Query (no router loaders).
function useNProgress() {
  const fetching = useIsFetching();
  const mutating = useIsMutating();
  const active = fetching + mutating > 0;

  useEffect(() => {
    if (active) NProgress.start();
    else NProgress.done();
  }, [active]);

  // Tidy up if the layout unmounts mid-request (e.g. logout).
  useEffect(() => () => NProgress.done(), []);
}

function Topbar() {
  useNProgress();

  return (
    <header
      id="app-topbar"
      className="relative flex items-center gap-3 border-b border-border bg-surface-raised px-4 py-2"
    >
      {/* Search */}
      <div className="w-[560px]">
        <label className="flex cursor-text items-center gap-2.5 rounded-md bg-surface-muted px-4 py-2 text-sm text-muted transition-all focus-within:ring-2 focus-within:ring-brand/40">
          <Search size={16} className="shrink-0 text-muted" />
          <input
            type="text"
            placeholder="Tìm kiếm (Ctrl + K)"
            className="w-full bg-transparent text-text outline-none border-0 placeholder:text-muted"
          />
        </label>
      </div>

      {/* Right actions */}
      <div className="ml-auto flex items-center gap-1.5">
        <NotificationBell />
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
