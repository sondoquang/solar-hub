import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SapoOrderDetailModal from "./SapoOrderDetailModal.jsx";

const markPaidMutate = vi.fn();
const cancelMutate = vi.fn();

vi.mock("../api/orders.js", () => ({
  useMarkOrderPaid: () => ({ mutate: markPaidMutate, isPending: false }),
  useCancelOrder: () => ({ mutate: cancelMutate, isPending: false }),
}));

const baseOrder = {
  id: 42,
  number: "SP-1001",
  site_name: "Sapo Store",
  hosting_name: null,
  status: "processing",
  payment_status: "pending",
  total: "409940",
  customer_name: "Trần Văn Khách",
  customer_phone: "0901234567",
  customer_email: "khach@example.com",
  shipping_address: "12 Lê Lợi, Q1",
  customer_note: "",
  line_items: [{ sku: "PANEL-1", name: "Tấm pin 450W", quantity: 2, total: "409940" }],
  classification: "genuine",
  risk_score: 0,
  date_created_woo: "2026-06-01T03:00:00Z",
};

function renderModal(order, props = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SapoOrderDetailModal order={order} open onClose={() => {}} {...props} />
    </QueryClientProvider>
  );
}

describe("SapoOrderDetailModal", () => {
  beforeEach(() => {
    markPaidMutate.mockClear();
    cancelMutate.mockClear();
  });

  it("shows the order details including the payment status and line items", () => {
    renderModal(baseOrder);
    expect(screen.getByText("Chi tiết đơn Sapo")).toBeInTheDocument();
    expect(screen.getByText("#SP-1001")).toBeInTheDocument();
    // Payment-status row (Sapo only) + line item.
    expect(screen.getByText("Chưa thanh toán")).toBeInTheDocument();
    expect(screen.getByText("Tấm pin 450W")).toBeInTheDocument();
  });

  it("marks the order paid after confirming", async () => {
    renderModal(baseOrder);
    await userEvent.click(
      screen.getByRole("button", { name: "Đánh dấu đã thanh toán" })
    );
    await userEvent.click(await screen.findByRole("button", { name: "Xác nhận" }));
    expect(markPaidMutate).toHaveBeenCalledTimes(1);
    expect(markPaidMutate.mock.calls[0][0]).toBe(42);
  });

  it("cancels the order after confirming", async () => {
    renderModal(baseOrder);
    await userEvent.click(screen.getByRole("button", { name: /Hủy đơn/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Xác nhận hủy" }));
    expect(cancelMutate).toHaveBeenCalledTimes(1);
    expect(cancelMutate.mock.calls[0][0]).toBe(42);
  });

  it("hides both actions for a paid, cancelled order", () => {
    renderModal({ ...baseOrder, status: "cancelled", payment_status: "paid" });
    expect(
      screen.queryByRole("button", { name: "Đánh dấu đã thanh toán" })
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Hủy đơn/ })).not.toBeInTheDocument();
    // The close button is always present.
    expect(screen.getByRole("button", { name: "Đóng" })).toBeInTheDocument();
  });
});
