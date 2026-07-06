import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import Domains from "./Domains.jsx";

// The default MSW handlers already serve the domain-info list + detail, so the
// page runs against real hooks end-to-end.
function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <Domains />
    </QueryClientProvider>
  );
}

describe("Domains page", () => {
  it("lists each site's domain with its expiry badges", async () => {
    renderPage();
    expect(await screen.findByText("Shop A")).toBeInTheDocument();
    expect(screen.getByText("example.com")).toBeInTheDocument();
    // SSL expires in 20 days (amber threshold) → "Còn 20 ngày".
    expect(screen.getByText("Còn 20 ngày")).toBeInTheDocument();
    expect(screen.getByText("Sạch")).toBeInTheDocument();
  });

  it("opens the per-site detail modal from the row action", async () => {
    renderPage();
    await screen.findByText("Shop A");
    await userEvent.click(screen.getByRole("button", { name: /Chi tiết/ }));

    const dialog = await screen.findByRole("dialog");
    // The modal fetches the full snapshot (WHOIS registrar) from MSW.
    expect(await within(dialog).findByText("GoDaddy.com, LLC")).toBeInTheDocument();
  });
});
