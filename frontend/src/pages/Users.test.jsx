import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toaster } from "react-hot-toast";
import { describe, expect, it } from "vitest";

import Users from "./Users.jsx";

// The default MSW handlers serve the users + groups lists, so the page runs
// against real hooks end-to-end (no router — the page uses no router hooks).
// The Toaster mirrors the real app shell so mutation toasts render.
function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <Toaster />
      <Users />
    </QueryClientProvider>
  );
}

describe("Users page", () => {
  it("lists users with their groups and status", async () => {
    renderPage();
    expect(await screen.findByText("admin")).toBeInTheDocument();
    expect(screen.getByText("Toàn quyền (superuser)")).toBeInTheDocument();
    expect(screen.getByText("marketing01")).toBeInTheDocument();
    expect(screen.getByText("Đã vô hiệu hóa")).toBeInTheDocument();
    // Group tag from the row.
    expect(screen.getByText("Marketing")).toBeInTheDocument();
  });

  it("opens the create modal from the header button", async () => {
    renderPage();
    await screen.findByText("admin");
    await userEvent.click(screen.getByRole("button", { name: /Thêm người dùng/ }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Tên đăng nhập")).toBeInTheDocument();
    expect(within(dialog).getByText("Mật khẩu")).toBeInTheDocument();
  });

  it("reactivates a deactivated user", async () => {
    renderPage();
    await screen.findByText("marketing01");
    // The deactivated row exposes a "Kích hoạt" action.
    await userEvent.click(screen.getByRole("button", { name: /Kích hoạt/ }));
    expect(await screen.findByText("Đã kích hoạt người dùng.")).toBeInTheDocument();
  });
});
