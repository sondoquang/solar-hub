import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CategoryRunDetailModal from "./CategoryRunDetailModal.jsx";

const exportCategoryRun = vi.fn().mockResolvedValue(undefined);
let runState;

// Isolate the component from react-query/axios: stub the hook + export call.
vi.mock("../api/syncReports.js", () => ({
  useCategoryRun: () => runState,
  exportCategoryRun: (...args) => exportCategoryRun(...args),
}));

const detail = {
  run_id: "11111111-2222-3333-4444-555555555555",
  started_at: "2026-06-11T03:00:00Z",
  site_count: 2,
  total_pulled: 3,
  total_mapped: 2,
  error_count: 1,
  status: "partial",
  sites: [
    {
      site_id: 1,
      site_name: "A-Site",
      site_url: "https://a-site.example.com",
      hosting: "TenTen",
      status: "success",
      error: "",
      pulled: 3,
      mapped: 2,
      categories: [
        { woo_id: 10, woo_name: "Pin mặt trời", hub_id: 1, hub_name: "Pin mặt trời" },
      ],
    },
    {
      site_id: 2,
      site_name: "B-Site",
      site_url: "https://b-site.example.com",
      hosting: "",
      status: "error",
      error: "ConnectError",
      pulled: 0,
      mapped: 0,
      categories: [],
    },
  ],
};

function renderModal() {
  return render(
    <CategoryRunDetailModal runId={detail.run_id} open onClose={() => {}} />
  );
}

describe("CategoryRunDetailModal", () => {
  beforeEach(() => {
    exportCategoryRun.mockClear();
    runState = { data: detail, isLoading: false, isError: false, refetch: vi.fn() };
  });

  it("shows the run summary and one row per site (hosting + result)", () => {
    renderModal();
    expect(
      screen.getByText(/2 site — 3 danh mục, đã ánh xạ\s*2 vào Hub/)
    ).toBeInTheDocument();
    expect(screen.getByText("A-Site")).toBeInTheDocument();
    expect(screen.getByText("TenTen")).toBeInTheDocument();
    expect(screen.getByText("Thành công")).toBeInTheDocument();
    expect(screen.getByText("ConnectError")).toBeInTheDocument();
  });

  it("expands a site row to its woo→hub category snapshot", async () => {
    renderModal();
    // Only A-Site has categories, so exactly one expand toggle renders.
    await userEvent.click(screen.getByRole("button", { name: /expand/i }));
    expect(screen.getByText("Danh mục trên site")).toBeInTheDocument();
    expect(screen.getAllByText("Pin mặt trời").length).toBeGreaterThanOrEqual(2); // woo + hub
  });

  it("exports the run as Excel", async () => {
    renderModal();
    await userEvent.click(screen.getByRole("button", { name: /Xuất Excel/ }));
    expect(exportCategoryRun).toHaveBeenCalledWith(detail.run_id);
  });

  it("shows the error state with retry when the detail fails to load", () => {
    runState = { data: undefined, isLoading: false, isError: true, refetch: vi.fn() };
    renderModal();
    expect(
      screen.getByText("Không tải được chi tiết lần đồng bộ")
    ).toBeInTheDocument();
  });
});
