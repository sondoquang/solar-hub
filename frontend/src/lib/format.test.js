import { describe, expect, it } from "vitest";

import { formatDate, formatDuration, formatVND } from "./format.js";

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

describe("formatDuration", () => {
  it("formats under an hour as mm:ss", () => {
    expect(formatDuration(272)).toBe("04:32");
  });
  it("formats an hour or more as hh:mm:ss", () => {
    expect(formatDuration(3723)).toBe("01:02:03");
  });
  it("returns em dash for null/invalid", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(-5)).toBe("—");
  });
});
