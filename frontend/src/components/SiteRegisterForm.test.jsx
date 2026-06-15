import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import SiteRegisterForm from "./SiteRegisterForm.jsx";

describe("SiteRegisterForm", () => {
  it("shows validation errors and does not submit when empty", async () => {
    const onSubmit = vi.fn();
    render(<SiteRegisterForm onSubmit={onSubmit} />);

    await userEvent.click(screen.getByRole("button", { name: /lưu site/i }));

    await waitFor(() => expect(screen.getAllByText("Bắt buộc").length).toBeGreaterThan(0));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("switches credential labels when the platform is Sapo", async () => {
    render(<SiteRegisterForm onSubmit={vi.fn()} />);

    expect(screen.getByText("Consumer key")).toBeInTheDocument();

    // the platform Select is the first combobox (hosting is the second)
    await userEvent.click(screen.getAllByRole("combobox")[0]);
    await userEvent.click(await screen.findByTitle("Sapo Web"));

    expect(screen.getByText("API key")).toBeInTheDocument();
    expect(screen.getByText(/API secret/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText("https://store.mysapo.net")).toBeInTheDocument();
  });
});
