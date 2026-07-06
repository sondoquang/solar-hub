import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { AuthContext } from "../lib/AuthContext.jsx";
import { server } from "../mocks/server.js";
import Products from "./Products.jsx";

const PRODUCT = {
  id: 42,
  sku: "SP-100",
  name: "Pin mặt trời 450W",
  type: "simple",
  regular_price: "1500000.00",
  sale_price: null,
  status: "publish",
  stock_status: "instock",
  images: [],
  categories: [],
  mappings: [],
  mapping_count: 0,
  updated_at: "2026-06-01T00:00:00Z",
};

// Render Products with an injected `hasPerm` so we can assert the RBAC gating
// hides action buttons the user has no permission for (the backend enforces;
// this only declutters the UI).
function renderWithPerms(hasPerm) {
  server.use(
    http.get("*/products/", () =>
      HttpResponse.json({ count: 1, next: null, previous: null, results: [PRODUCT] }),
    ),
    http.get("*/products/stats/", () =>
      HttpResponse.json({ total: 1, mapped: 0, unmapped: 1, by_status: {} }),
    ),
  );
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <AuthContext.Provider value={{ hasPerm }}>
      <QueryClientProvider client={qc}>
        <Products />
      </QueryClientProvider>
    </AuthContext.Provider>,
  );
}

describe("Products — RBAC button gating", () => {
  it("hides every action button for a view-only user", async () => {
    renderWithPerms(() => false);
    // The row still renders (view), so the page is usable read-only…
    expect(await screen.findByText("Pin mặt trời 450W")).toBeInTheDocument();
    // …but no create/sync/import/edit/delete/duplicate controls are shown.
    expect(screen.queryByRole("button", { name: /Thêm sản phẩm/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Đồng bộ ngay/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Nhập từ website chính/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Sửa$/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Xóa$/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Nhân bản/ })).toBeNull();
  });

  it("shows the matching buttons when the permissions are granted", async () => {
    const granted = new Set([
      "catalog.add_masterproduct",
      "catalog.change_masterproduct",
      "catalog.delete_masterproduct",
      "catalog.push_masterproduct",
    ]);
    renderWithPerms((perm) => granted.has(perm));
    expect(await screen.findByText("Pin mặt trời 450W")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Thêm sản phẩm/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Đồng bộ ngay/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Sửa$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Xóa$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Nhân bản/ })).toBeInTheDocument();
  });
});
