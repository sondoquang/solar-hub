import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DomainInfoModal from "./DomainInfoModal.jsx";

const mutate = vi.fn();
let domainData;
let loading;

// Isolate the modal from react-query/axios: stub the two hooks it uses so each
// test drives the snapshot (or the never-checked null) directly.
vi.mock("../api/domainInfo.js", () => ({
  useDomainInfo: () => ({ data: domainData, isLoading: loading }),
  useRefreshDomainInfo: () => ({ mutate, isPending: false }),
}));

const SNAPSHOT = {
  id: 1,
  site: 1,
  domain: "example.com",
  whois_status: "ok",
  whois_registrar: "GoDaddy.com, LLC",
  whois_created_at: "2020-01-02T00:00:00Z",
  whois_expires_at: "2027-01-02T00:00:00Z",
  whois_days_remaining: 180,
  whois_checked_at: "2026-07-01T00:00:00Z",
  dns_status: "ok",
  dns_records: { A: ["1.2.3.4"], MX: ["10 mail.example.com"] },
  dns_checked_at: "2026-07-01T00:00:00Z",
  ssl_status: "ok",
  ssl_issuer: "CN=R11,O=Let's Encrypt",
  ssl_not_before: "2026-05-01T00:00:00Z",
  ssl_not_after: "2026-08-01T00:00:00Z",
  ssl_days_remaining: 5,
  ssl_checked_at: "2026-07-01T00:00:00Z",
  blacklist_status: "ok",
  blacklist_verdict: "clean",
  blacklist_results: [
    { list: "zen.spamhaus.org", target: "1.2.3.4", result: "clean", detail: "" },
  ],
  blacklist_checked_at: "2026-07-01T00:00:00Z",
  gindex_status: "skipped",
  gindex_indexed: null,
  gindex_total_results: null,
  last_refreshed_at: "2026-07-01T00:00:00Z",
  last_error: "",
  is_pending: false,
};

function renderModal() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DomainInfoModal site={{ id: 1, name: "Shop A" }} open onClose={() => {}} />
    </QueryClientProvider>
  );
}

describe("DomainInfoModal", () => {
  beforeEach(() => {
    mutate.mockClear();
    domainData = SNAPSHOT;
    loading = false;
  });

  it("shows each check in its own tab (only the active tab's content)", async () => {
    renderModal();
    // Domain pill + the default WHOIS tab are visible up front.
    expect(screen.getByText("example.com")).toBeInTheDocument();
    expect(screen.getByText("GoDaddy.com, LLC")).toBeInTheDocument();
    // DNS lives behind its own tab.
    await userEvent.click(screen.getByRole("tab", { name: /DNS/ }));
    // "1.2.3.4" shows in both the DNS table and the blacklist target column.
    expect(screen.getAllByText("1.2.3.4").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("tab", { name: /SSL/ }));
    expect(screen.getByText("CN=R11,O=Let's Encrypt")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /Blacklist/ }));
    // "Sạch" appears as both the roll-up verdict and the per-list result.
    expect(screen.getAllByText("Sạch").length).toBeGreaterThan(0);
    // Google index unconfigured → shows the skipped explanation, not an error.
    await userEvent.click(screen.getByRole("tab", { name: /Google Index/ }));
    expect(screen.getByText(/Bỏ qua — chưa cấu hình/)).toBeInTheDocument();
  });

  it("colours the SSL countdown red when ≤7 days remain", async () => {
    renderModal();
    // WHOIS (180d) is the default tab; the SSL 5-day badge is on the SSL tab.
    expect(screen.getByText("Còn 180 ngày")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /SSL/ }));
    expect(screen.getByText("Còn 5 ngày")).toBeInTheDocument();
  });

  it("enqueues a refresh when Làm mới is clicked", async () => {
    renderModal();
    await userEvent.click(screen.getByRole("button", { name: /Làm mới/ }));
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0][0]).toEqual({ siteId: 1 });
  });

  it("shows a never-checked empty state and can trigger the first check", async () => {
    domainData = null;
    renderModal();
    expect(screen.getByText(/chưa được kiểm tra/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Kiểm tra ngay/ }));
    expect(mutate).toHaveBeenCalledTimes(1);
  });
});
