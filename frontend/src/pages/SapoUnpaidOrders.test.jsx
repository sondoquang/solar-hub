import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SapoUnpaidOrders from "./SapoUnpaidOrders.jsx";

// Isolate the page from react-query/axios by stubbing the hooks it uses; the
// two row actions (mark paid / cancel) are vi.fn so we assert what they receive.
const markPaidMutate = vi.fn();
const cancelMutate = vi.fn();

const order = {
  id: 42,
  number: "SP-1001",
  site_name: "Sapo Store",
  platform: "sapo",
  status: "processing",
  payment_status: "pending",
  total: "409940",
  customer_name: "Trần Văn Khách",
  customer_phone: "0901234567",
  date_created_woo: "2026-06-01T03:00:00Z",
};

vi.mock("../api/orders.js", () => ({
  useOrders: () => ({
    data: { results: [order], count: 1 },
    isLoading: false,
    isFetching: false,
    isError: false,
    refetch: vi.fn(),
  }),
  usePollOrders: () => ({ mutate: vi.fn(), isPending: false }),
  useCancelOrder: () => ({ mutate: cancelMutate, isPending: false, variables: undefined }),
  useMarkOrderPaid: () => ({ mutate: markPaidMutate, isPending: false, variables: undefined }),
}));

vi.mock("../api/sites.js", () => ({
  useSites: () => ({ data: { results: [{ id: 1, name: "Sapo Store" }] } }),
}));

vi.mock("../api/syncReports.js", () => ({
  SYNC_OPS: { orders: "poll_orders" },
  useSyncRunProgress: () => ({ activeRun: null, doneSites: 0, start: vi.fn() }),
}));

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SapoUnpaidOrders />
    </QueryClientProvider>
  );
}

describe("SapoUnpaidOrders", () => {
  beforeEach(() => {
    markPaidMutate.mockClear();
    cancelMutate.mockClear();
  });

  it("lists an unpaid Sapo order with its payment-status badge", () => {
    renderPage();
    expect(screen.getByText("#SP-1001")).toBeInTheDocument();
    expect(screen.getByText("Trần Văn Khách")).toBeInTheDocument();
    expect(screen.getByText("Chưa thanh toán")).toBeInTheDocument();
  });

  it("marks an order paid after confirming", async () => {
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: /Đã thanh toán/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Xác nhận" }));
    expect(markPaidMutate).toHaveBeenCalledTimes(1);
    expect(markPaidMutate.mock.calls[0][0]).toBe(42);
  });

  it("cancels an order after confirming", async () => {
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: /Hủy đơn/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Xác nhận hủy" }));
    expect(cancelMutate).toHaveBeenCalledTimes(1);
    expect(cancelMutate.mock.calls[0][0]).toBe(42);
  });
});
