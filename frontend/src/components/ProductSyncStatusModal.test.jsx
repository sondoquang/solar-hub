import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProductSyncStatusModal from "./ProductSyncStatusModal.jsx";

const mutate = vi.fn();

// Isolate the component from react-query/axios: stub the two hooks it uses.
vi.mock("../api/products.js", () => ({
  useProductSyncStatus: () => ({
    data: [
      { site_id: 1, site_name: "B-Site", site_url: "https://b-site.example.com", site_status: "up", is_primary: true, synced: true, woo_product_id: 50, last_synced_at: "2026-06-01T00:00:00Z" },
      { site_id: 2, site_name: "A-Site", site_url: "https://a-site.example.com", site_status: "down", is_primary: false, synced: false, woo_product_id: null, last_synced_at: null },
    ],
    isLoading: false,
  }),
  useSyncProducts: () => ({ mutate, isPending: false }),
}));

const product = { id: 7, name: "Pin mặt trời", sku: "SP-1" };

function renderModal() {
  return render(<ProductSyncStatusModal product={product} open onClose={() => {}} />);
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

    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0][0]).toEqual({ sites: [2], products: [7] });
  });

  it("filters rows by website status and prunes hidden selections", async () => {
    renderModal();
    // Select the unsynced A-Site (status down) while everything is visible.
    await userEvent.click(screen.getByRole("button", { name: /Chọn site chưa đồng bộ/ }));

    // Filter to "Hoạt động" (up) → only B-Site remains, A-Site selection is pruned.
    // Comboboxes are [Loại trang, Trạng thái web] in DOM order.
    await userEvent.click(screen.getAllByRole("combobox")[1]);
    await userEvent.click(screen.getByTitle("Hoạt động"));

    expect(screen.queryByText("A-Site")).not.toBeInTheDocument();
    expect(screen.getByText("B-Site")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Đồng bộ site đã chọn" })
    ).toBeDisabled();
  });

  it("filters rows to primary sites only", async () => {
    renderModal();
    await userEvent.click(screen.getAllByRole("combobox")[0]);
    await userEvent.click(screen.getByTitle("Trang chính"));

    expect(screen.getByText("B-Site")).toBeInTheDocument(); // is_primary
    expect(screen.queryByText("A-Site")).not.toBeInTheDocument();
  });

  it("filters rows by domain search and prunes hidden selections", async () => {
    renderModal();
    expect(screen.getByText("a-site.example.com")).toBeInTheDocument();

    // Select unsynced A-Site, then search for B-Site's domain → selection pruned.
    await userEvent.click(screen.getByRole("button", { name: /Chọn site chưa đồng bộ/ }));
    await userEvent.type(screen.getByPlaceholderText("Tìm theo domain..."), "b-site");

    expect(screen.queryByText("A-Site")).not.toBeInTheDocument();
    expect(screen.getByText("B-Site")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Đồng bộ site đã chọn" })
    ).toBeDisabled();
  });
});
