import { NavLink, Outlet } from "react-router-dom";

const links = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/orders", label: "Đơn hàng" },
  { to: "/products", label: "Sản phẩm" },
  { to: "/sites", label: "Website" },
];

function navClass({ isActive }) {
  return [
    "rounded px-3 py-2 text-sm font-medium",
    isActive ? "bg-brand text-ink" : "text-muted hover:text-ink",
  ].join(" ");
}

export default function AppLayout() {
  return (
    <div className="min-h-screen">
      <header className="border-b bg-white">
        <nav className="mx-auto flex max-w-6xl items-center gap-2 px-4 py-3">
          <span className="font-display text-lg font-bold">Solar Hub</span>
          <div className="ml-6 flex gap-1">
            {links.map((l) => (
              <NavLink key={l.to} to={l.to} end={l.end} className={navClass}>
                {l.label}
              </NavLink>
            ))}
          </div>
        </nav>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
