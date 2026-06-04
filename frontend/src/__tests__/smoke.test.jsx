import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import EmptyState from "../components/EmptyState.jsx";

describe("EmptyState", () => {
  it("renders the title", () => {
    render(<EmptyState title="Không có gì" />);
    expect(screen.getByText("Không có gì")).toBeInTheDocument();
  });
});
