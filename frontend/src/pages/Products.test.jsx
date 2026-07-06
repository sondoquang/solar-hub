import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../mocks/server.js";
import Products from "./Products.jsx";

const PRODUCT = {
  id: 42,
  sku: "SP-100",
  name: "Pin mặt trời 450W",
  match_name: "Pin mặt trời 450W",
  type: "simple",
  description: "<p>Mô tả dài</p>",
  short_description: "",
  regular_price: "1500000.00",
  sale_price: null,
  status: "publish",
  stock_status: "instock",
  weight: null,
  images: [],
  categories: [],
  external_url: "",
  button_text: "",
  grouped_skus: [],
  attributes: [],
  variations: [],
  mappings: [{ site: 1, site_name: "Shop A", woo_product_id: 7, last_synced_at: null }],
  mapping_count: 1,
  source_site: 3,
  source_site_name: "Trang chính",
  imported_at: "2026-05-01T00:00:00Z",
  created_at: "2026-05-01T00:00:00Z",
  updated_at: "2026-06-01T00:00:00Z",
};

function renderPage() {
  server.use(
    http.get("*/products/", () =>
      HttpResponse.json({ count: 1, next: null, previous: null, results: [PRODUCT] }),
    ),
    http.get("*/products/stats/", () =>
      HttpResponse.json({ total: 1, mapped: 1, unmapped: 0, by_status: {} }),
    ),
  );
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <Products />
    </QueryClientProvider>,
  );
}

describe("Products — Nhân bản (duplicate)", () => {
  it("opens the create form pre-filled with a copy (suggested SKU/name, no source id)", async () => {
    const user = userEvent.setup();
    renderPage();

    // Wait for the row to render, then click its "Nhân bản" button.
    expect(await screen.findByText("Pin mặt trời 450W")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Nhân bản/i }));

    // The modal opens in CREATE mode with the duplicate title.
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Nhân bản sản phẩm")).toBeInTheDocument();

    // SKU + name are pre-filled with the suggested copy values.
    await waitFor(() => {
      expect(screen.getByDisplayValue("SP-100-COPY")).toBeInTheDocument();
      expect(screen.getByDisplayValue("Pin mặt trời 450W (Copy)")).toBeInTheDocument();
    });
  });
});
