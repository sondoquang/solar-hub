import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PaymentStatusBadge from "./PaymentStatusBadge.jsx";

describe("PaymentStatusBadge", () => {
  it("maps known payment statuses to Vietnamese labels", () => {
    const { rerender } = render(<PaymentStatusBadge status="paid" />);
    expect(screen.getByText("Đã thanh toán")).toBeInTheDocument();

    rerender(<PaymentStatusBadge status="pending" />);
    expect(screen.getByText("Chưa thanh toán")).toBeInTheDocument();

    rerender(<PaymentStatusBadge status="partially_paid" />);
    expect(screen.getByText("Thanh toán một phần")).toBeInTheDocument();
  });

  it("falls back to the raw value for an unknown status", () => {
    render(<PaymentStatusBadge status="mystery" />);
    expect(screen.getByText("mystery")).toBeInTheDocument();
  });
});
