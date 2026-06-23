import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProductRunDetailModal from "./ProductRunDetailModal.jsx";

const exportProductRun = vi.fn().mockResolvedValue(undefined);
let runState;

// Isolate the component from react-query/axios: stub the hook + export call.
vi.mock("../api/syncReports.js", () => ({
  useProductRun: () => runState,
  exportProductRun: (...args) => exportProductRun(...args),
}));

const detail = {
  run_id: "11111111-2222-3333-4444-555555555555",
  started_at: "2026-06-11T03:00:00Z",
  site_count: 2,
  total_created: 4,
  total_updated: 1,
  total_adopted: 2,
  total_failed: 1,
  error_count: 1,
  status: "partial",
  sites: [
    {
      site_id: 1,
      site_name: "A-Site",
      site_url: "https://a-site.example.com",
      hosting: "TenTen",
      status: "partial",
      error: "",
      created: 4,
      updated: 1,
      deleted: 0,
      planned: 5,
      adopted_count: 2,
      adopted: ["SP-A", "SP-B"],
      ambiguous: [],
      recreated_stale: 0,
      variations: {},
      failed: [
        {
          sku: "SP-DUP",
          op: "create",
          code: "product_invalid_sku",
          message: "dup",
          kind: "duplicate",
        },
      ],
    },
    {
      site_id: 2,
      site_name: "B-Site",
      site_url: "https://b-site.example.com",
      hosting: "",
      status: "error",
      error: "ConnectError",
      created: 0,
      updated: 0,
      deleted: 0,
      planned: 0,
      adopted_count: 0,
      adopted: [],
      ambiguous: [],
      recreated_stale: 0,
      variations: {},
      failed: [],
    },
  ],
};

function renderModal() {
  return render(<ProductRunDetailModal runId={detail.run_id} open onClose={() => {}} />);
}

describe("ProductRunDetailModal", () => {
  beforeEach(() => {
    exportProductRun.mockClear();
    runState = { data: detail, isLoading: false, isError: false, refetch: vi.fn() };
  });

  it("shows the run summary and one row per site (adopted + result)", () => {
    renderModal();
    expect(
      screen.getByText(/2 site — tạo mới 4, cập nhật\s*1, đã nhận theo tên 2/)
    ).toBeInTheDocument();
    expect(screen.getByText("A-Site")).toBeInTheDocument();
    expect(screen.getByText("TenTen")).toBeInTheDocument();
    expect(screen.getByText("ConnectError")).toBeInTheDocument();
  });

  it("expands a site row to its failed SKUs with reasons", async () => {
    renderModal();
    // Only A-Site has failures, so exactly one expand toggle renders.
    await userEvent.click(screen.getByRole("button", { name: /expand/i }));
    expect(screen.getByText("SP-DUP")).toBeInTheDocument();
    expect(screen.getByText("product_invalid_sku")).toBeInTheDocument();
  });

  it("exports the run as Excel", async () => {
    renderModal();
    await userEvent.click(screen.getByRole("button", { name: /Xuất Excel/ }));
    expect(exportProductRun).toHaveBeenCalledWith(detail.run_id);
  });

  it("shows the error state when the detail fails to load", () => {
    runState = { data: undefined, isLoading: false, isError: true, refetch: vi.fn() };
    renderModal();
    expect(screen.getByText("Không tải được chi tiết lần đồng bộ")).toBeInTheDocument();
  });
});
