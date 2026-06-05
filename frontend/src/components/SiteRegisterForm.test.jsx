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
});
