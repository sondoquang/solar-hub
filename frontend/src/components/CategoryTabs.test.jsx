import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import CategoryOverviewTab from "./CategoryOverviewTab.jsx";
import CategorySyncHistoryTab from "./CategorySyncHistoryTab.jsx";
import CategoryTreeTab from "./CategoryTreeTab.jsx";

// Integration-style: real hooks → axios → MSW (handlers in src/mocks/handlers.js).
// These assert the screens render DYNAMICALLY off the API responses.
function renderWithClient(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("CategoryOverviewTab", () => {
  it("renders the cross-site matrix with one dynamic column per site", async () => {
    renderWithClient(<CategoryOverviewTab onPull={() => {}} pulling={false} />);

    // The matrix cell is built from the response's per-site `cells` map.
    expect(await screen.findByText("ID: 124")).toBeInTheDocument();
    expect(screen.getByText("Ắc Quy Phoenix")).toBeInTheDocument();
    // Column headers come from the response's `sites` list (demowp has no cell).
    expect(screen.getByRole("columnheader", { name: "demowp.com" })).toBeInTheDocument();
    // Stat card reflects the overview endpoint.
    expect(screen.getByText("Trong tổng số 1.328 danh mục")).toBeInTheDocument();
  });
});

describe("CategorySyncHistoryTab", () => {
  it("shows the run's người chạy and duration from the API", async () => {
    renderWithClient(<CategorySyncHistoryTab />);

    expect(await screen.findByText("admin")).toBeInTheDocument(); // triggered_by
    expect(screen.getByText("04:32")).toBeInTheDocument(); // 272s → mm:ss
    expect(screen.getByText("156")).toBeInTheDocument(); // total runs stat
  });
});

describe("CategoryTreeTab", () => {
  it("loads a node's site links when the node is selected", async () => {
    renderWithClient(<CategoryTreeTab />);

    const node = await screen.findByText("Ắc quy");
    await userEvent.click(node);

    // The detail panel fetches /categories/{id}/sites/ on selection.
    expect(await screen.findByText("Liên kết với website")).toBeInTheDocument();
    expect(await screen.findByText("Chưa liên kết")).toBeInTheDocument(); // demowp not linked
  });
});
