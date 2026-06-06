import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import OrderDetailModal from "./OrderDetailModal.jsx";

const makeOrder = (id) => ({
  id,
  number: `100${id}`,
  site_name: `site-${id}.com`,
  hosting_name: null,
  status: "completed",
  total: "1000",
  customer_name: `Khách ${id}`,
  customer_phone: "",
  customer_email: "",
  shipping_address: "",
  customer_note: "",
  line_items: [],
  date_created_woo: "2026-06-01T00:00:00Z",
});

function renderModal(orders) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <OrderDetailModal orders={orders} open onClose={() => {}} />
    </QueryClientProvider>
  );
}

describe("OrderDetailModal", () => {
  it("hides navigation for a single order", () => {
    renderModal([makeOrder(1)]);
    expect(screen.getByText("#1001")).toBeInTheDocument();
    expect(screen.queryByText(/Đơn \d+\/\d+/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Sau/ })).not.toBeInTheDocument();
  });

  it("navigates between orders with Prev/Next", async () => {
    renderModal([makeOrder(1), makeOrder(2), makeOrder(3)]);

    expect(screen.getByText("Đơn 1/3")).toBeInTheDocument();
    expect(screen.getByText("#1001")).toBeInTheDocument();
    // Prev is disabled on the first order.
    expect(screen.getByRole("button", { name: /Trước/ })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: /Sau/ }));

    expect(screen.getByText("Đơn 2/3")).toBeInTheDocument();
    expect(screen.getByText("#1002")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Trước/ })).toBeEnabled();
  });

  it("moves to the next order with the ArrowRight key", async () => {
    renderModal([makeOrder(1), makeOrder(2)]);

    expect(screen.getByText("#1001")).toBeInTheDocument();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByText("Đơn 2/2")).toBeInTheDocument();
    expect(screen.getByText("#1002")).toBeInTheDocument();
  });
});
