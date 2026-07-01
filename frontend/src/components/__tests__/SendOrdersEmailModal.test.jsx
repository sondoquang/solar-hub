import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import SendOrdersEmailModal from "../SendOrdersEmailModal.jsx";

function renderModal(props = {}) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <SendOrdersEmailModal open orderIds={[1, 2]} onClose={() => {}} {...props} />
    </QueryClientProvider>,
  );
}

describe("SendOrdersEmailModal", () => {
  it("disables send until a valid email is entered", async () => {
    const user = userEvent.setup();
    renderModal();

    const sendBtn = screen.getByRole("button", { name: "Gửi" });
    expect(sendBtn).toBeDisabled();

    const input = screen.getByPlaceholderText("nguoinhan@example.com");
    await user.type(input, "buyer@example.com");
    expect(sendBtn).toBeEnabled();
  });

  it("sends the selected orders and closes on success", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onSent = vi.fn();
    renderModal({ onClose, onSent });

    await user.type(
      screen.getByPlaceholderText("nguoinhan@example.com"),
      "buyer@example.com",
    );
    await user.click(screen.getByRole("button", { name: "Gửi" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onSent).toHaveBeenCalled();
  });

  it("shows the number of selected orders in the title", () => {
    renderModal({ orderIds: [1, 2, 3] });
    expect(screen.getByText("Gửi 3 đơn hàng qua email")).toBeInTheDocument();
  });
});
