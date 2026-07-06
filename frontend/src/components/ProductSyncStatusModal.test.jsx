import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProductSyncStatusModal from "./ProductSyncStatusModal.jsx";

const mutate = vi.fn();

// Isolate the component from react-query/axios: stub the two hooks it uses.
vi.mock("../api/products.js", () => ({
  useProductSyncStatus: () => ({
    data: [
      { site_id: 1, site_name: "B-Site", site_url: "https://b-site.example.com", site_status: "up", platform: "woocommerce", is_primary: true, hosting_id: 10, hosting_username: "sondo_01", synced: true, woo_product_id: 50, last_synced_at: "2026-06-01T00:00:00Z" },
      { site_id: 2, site_name: "A-Site", site_url: "https://a-site.example.com", site_status: "down", platform: "sapo", is_primary: false, hosting_id: 20, hosting_username: "sondo_02", synced: false, woo_product_id: null, last_synced_at: null },
    ],
    isLoading: false,
  }),
  useSyncProducts: () => ({ mutate, isPending: false }),
}));

const product = { id: 7, name: "Pin mặt trời", sku: "SP-1" };

// The modal is wrapped in a QueryClientProvider only for parity with the app;
// the push no longer polls a run (it is reported by email), so no run query fires.
function renderModal() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ProductSyncStatusModal product={product} open onClose={() => {}} />
    </QueryClientProvider>
  );
}

// Pushing now opens a type-PUSH confirm step: type the keyword, then confirm.
async function confirmPush() {
  await userEvent.type(screen.getByPlaceholderText("PUSH"), "PUSH");
  await userEvent.click(screen.getByRole("button", { name: "Đồng bộ ngay" }));
}

describe("ProductSyncStatusModal", () => {
  beforeEach(() => mutate.mockClear());

  it("lists every site with its sync state, not-synced first", () => {
    renderModal();
    expect(screen.getByText("1/2 site")).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    // Header row is rows[0]; first data row should be the not-synced A-Site.
    expect(within(rows[1]).getByText("A-Site")).toBeInTheDocument();
    expect(screen.getByText("Đã đồng bộ")).toBeInTheDocument();
    expect(screen.getByText("Chưa đồng bộ")).toBeInTheDocument();
  });

  it("syncs the selected (unsynced) sites for this product", async () => {
    renderModal();
    await userEvent.click(screen.getByRole("button", { name: /Chọn site chưa đồng bộ/ }));
    await userEvent.click(screen.getByRole("button", { name: /Đồng bộ site đã chọn/ }));
    await confirmPush();

    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0][0]).toEqual({ sites: [2], products: [7] });
  });

  it("gates the push behind typing PUSH to confirm", async () => {
    renderModal();
    await userEvent.click(screen.getByRole("button", { name: /Chọn site chưa đồng bộ/ }));
    await userEvent.click(screen.getByRole("button", { name: /Đồng bộ site đã chọn/ }));

    // The confirm button is disabled until the keyword is typed.
    const confirmBtn = screen.getByRole("button", { name: "Đồng bộ ngay" });
    expect(confirmBtn).toBeDisabled();
    expect(mutate).not.toHaveBeenCalled();

    await userEvent.type(screen.getByPlaceholderText("PUSH"), "PUSH");
    expect(confirmBtn).toBeEnabled();
  });

  it("keeps selections when a filter hides the selected site", async () => {
    renderModal();
    // Select the unsynced A-Site (status down) while everything is visible.
    await userEvent.click(screen.getByRole("button", { name: /Chọn site chưa đồng bộ/ }));

    // Filter to "Hoạt động" (up) → only B-Site remains, but A-Site stays selected.
    // Comboboxes are [Loại trang, Trạng thái web] in DOM order.
    await userEvent.click(screen.getAllByRole("combobox")[1]);
    await userEvent.click(screen.getByTitle("Hoạt động"));

    expect(screen.queryByText("A-Site")).not.toBeInTheDocument();
    expect(screen.getByText("B-Site")).toBeInTheDocument();
    // The hidden selection is surfaced and the push still targets it.
    expect(screen.getByText(/1 site đã chọn đang ẩn/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Đồng bộ site đã chọn/ }));
    await confirmPush();
    expect(mutate.mock.calls[0][0]).toEqual({ sites: [2], products: [7] });
  });

  it("filters rows to primary sites only", async () => {
    renderModal();
    await userEvent.click(screen.getAllByRole("combobox")[0]);
    await userEvent.click(screen.getByTitle("Trang chính"));

    expect(screen.getByText("B-Site")).toBeInTheDocument(); // is_primary
    expect(screen.queryByText("A-Site")).not.toBeInTheDocument();
  });

  it("filters rows by hosting username", async () => {
    renderModal();
    // Comboboxes are [Loại trang, Trạng thái web, Hosting] in DOM order.
    await userEvent.click(screen.getAllByRole("combobox")[2]);
    await userEvent.click(screen.getByTitle("sondo_01"));

    expect(screen.getByText("B-Site")).toBeInTheDocument(); // hosting sondo_01
    expect(screen.queryByText("A-Site")).not.toBeInTheDocument();
  });

  it("accumulates selections across searches instead of clearing them", async () => {
    renderModal();
    const searchBox = screen.getByPlaceholderText("Tìm theo domain...");

    // Search for A-Site, then tick it (unsynced).
    await userEvent.type(searchBox, "a-site");
    await userEvent.click(screen.getByRole("button", { name: /Chọn site chưa đồng bộ/ }));

    // Search again for B-Site: A-Site is hidden but its selection survives.
    await userEvent.clear(searchBox);
    await userEvent.type(searchBox, "b-site");
    expect(screen.queryByText("A-Site")).not.toBeInTheDocument();
    expect(screen.getByText("B-Site")).toBeInTheDocument();

    // Tick B-Site's row checkbox (checkbox[0] is the header select-all).
    const checkboxes = screen.getAllByRole("checkbox");
    await userEvent.click(checkboxes[checkboxes.length - 1]);

    // Both picks survive — the push targets both sites.
    await userEvent.click(screen.getByRole("button", { name: /Đồng bộ site đã chọn/ }));
    await confirmPush();
    expect(mutate).toHaveBeenCalledTimes(1);
    const arg = mutate.mock.calls[0][0];
    expect(arg.products).toEqual([7]);
    expect([...arg.sites].sort()).toEqual([1, 2]);
  });
});
