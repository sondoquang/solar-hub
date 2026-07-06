import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import Groups from "./Groups.jsx";

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <Groups />
    </QueryClientProvider>
  );
}

describe("Groups page", () => {
  it("lists groups with permission and user counts", async () => {
    renderPage();
    expect(await screen.findByText("Quản trị viên")).toBeInTheDocument();
    expect(screen.getByText("83 quyền")).toBeInTheDocument();
    expect(screen.getByText("Marketing")).toBeInTheDocument();
  });

  it("opens the permission matrix modal and shows VN labels", async () => {
    renderPage();
    await screen.findByText("Quản trị viên");
    await userEvent.click(screen.getByRole("button", { name: /Thêm nhóm/ }));

    const dialog = await screen.findByRole("dialog");
    // Module label (unique — the "Đơn hàng" model label differs from module).
    expect(await within(dialog).findByText("Tên miền")).toBeInTheDocument();
    // "Đơn hàng" appears as both a module and a model header.
    expect(within(dialog).getAllByText("Đơn hàng").length).toBeGreaterThan(0);
    // Standard action label + a custom business permission label.
    expect(within(dialog).getAllByText("Xem").length).toBeGreaterThan(0);
    expect(
      within(dialog).getByText("Có thể chuyển đơn sang marketing")
    ).toBeInTheDocument();
  });
});
