import { describe, expect, it } from "vitest";

import {
  formatDate,
  formatDuration,
  formatVND,
  friendlySyncError,
  titleCaseName,
} from "./format.js";

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

describe("titleCaseName", () => {
  it("capitalizes the first letter of each word", () => {
    expect(titleCaseName("nguyễn văn an")).toBe("Nguyễn Văn An");
  });
  it("lowercases the rest of all-caps input", () => {
    expect(titleCaseName("TRẦN THỊ B")).toBe("Trần Thị B");
  });
  it("normalizes mixed casing and extra spaces", () => {
    expect(titleCaseName("  lê   vĂN  CưỜng ")).toBe("Lê Văn Cường");
  });
  it("returns empty string for blank input (caller applies its own fallback)", () => {
    expect(titleCaseName("")).toBe("");
    expect(titleCaseName(null)).toBe("");
    expect(titleCaseName(undefined)).toBe("");
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

describe("friendlySyncError", () => {
  it("maps read/generic timeouts to a slow-response message", () => {
    expect(friendlySyncError("ReadTimeout")).toBe(
      "Website phản hồi quá chậm, đã hết thời gian chờ"
    );
    expect(friendlySyncError("PoolTimeout")).toBe(
      "Website phản hồi quá chậm, đã hết thời gian chờ"
    );
  });
  it("distinguishes a connect timeout from connect failures", () => {
    expect(friendlySyncError("ConnectTimeout")).toBe(
      "Không kết nối được tới website — quá thời gian chờ kết nối"
    );
    expect(friendlySyncError("ConnectError")).toBe("Không kết nối được tới website");
  });
  it("maps auth and SSL errors", () => {
    expect(friendlySyncError("HTTPStatusError 401")).toBe(
      "Sai thông tin đăng nhập (key/secret) tới website"
    );
    expect(friendlySyncError("SSLError")).toBe("Lỗi chứng chỉ bảo mật (SSL) của website");
  });
  it("falls back to a generic message for unknown tokens", () => {
    expect(friendlySyncError("SomethingWeird")).toBe(
      "Không đồng bộ được — website không phản hồi đúng"
    );
  });
  it("returns empty string for blank input", () => {
    expect(friendlySyncError("")).toBe("");
    expect(friendlySyncError(null)).toBe("");
  });
});
