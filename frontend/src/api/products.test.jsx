import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../mocks/server.js";
import {
  clearCategorySync,
  getProductCategories,
  useCategoryMappings,
} from "./products.js";

function wrapper({ children }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("useCategoryMappings", () => {
  it("stays disabled until a site is picked", () => {
    const { result } = renderHook(() => useCategoryMappings({}), { wrapper });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("goes loading → data once a site is set (from MSW)", async () => {
    const { result } = renderHook(() => useCategoryMappings({ site: 1 }), { wrapper });
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const row = result.current.data.results[0];
    expect(row.woo_name).toBe(" Pin  mặt trời "); // tên RAW trên site
    expect(row.category_name).toBe("Pin mặt trời"); // tên Hub đã chuẩn hóa
  });
});

describe("getProductCategories", () => {
  it("walks every page so the picker gets the FULL catalog", async () => {
    // The bug this guards against: one request capped at max_page_size left
    // later categories (e.g. "Solarcity") invisible in the product form.
    server.use(
      http.get("*/products/categories/", ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get("page") ?? 1);
        const pages = {
          1: { next: "/products/categories/?page=2", results: [{ id: 1, name: "Inverter", parent: null }] },
          2: { next: null, results: [{ id: 87, name: "Solarcity", parent: null }] },
        };
        return HttpResponse.json({ count: 2, previous: null, ...pages[page] });
      })
    );

    const cats = await getProductCategories();
    expect(cats.map((c) => c.name)).toEqual(["Inverter", "Solarcity"]);
  });
});

describe("clearCategorySync", () => {
  it("POSTs to clear_all and returns the cleared/kept counts", async () => {
    let method;
    server.use(
      http.post("*/products/categories/clear_all/", ({ request }) => {
        method = request.method;
        return HttpResponse.json({
          categories_cleared: 10,
          categories_kept: 2,
          mappings_cleared: 30,
          history_cleared: 4,
        });
      })
    );

    const res = await clearCategorySync();
    expect(method).toBe("POST");
    expect(res).toEqual({
      categories_cleared: 10,
      categories_kept: 2,
      mappings_cleared: 30,
      history_cleared: 4,
    });
  });
});
