import { describe, expect, it } from "vitest";

import { formatDate, formatVND } from "./format.js";

describe("formatVND", () => {
  it("formats a number as VND", () => {
    expect(formatVND(1000000)).toContain("1.000.000");
  });
  it("returns em dash for non-numeric", () => {
    expect(formatVND("abc")).toBe("—");
  });
});

describe("formatDate", () => {
  it("returns em dash for empty input", () => {
    expect(formatDate(null)).toBe("—");
  });
});
