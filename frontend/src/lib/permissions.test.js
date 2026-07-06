import { describe, expect, it } from "vitest";

import { can } from "./permissions.js";

describe("can()", () => {
  it("returns false for no user", () => {
    expect(can(null, "orders.view_order")).toBe(false);
  });

  it("grants everything to a superuser", () => {
    const su = { is_superuser: true, permissions: [] };
    expect(can(su, "anything.at_all")).toBe(true);
  });

  it("matches an owned permission", () => {
    const user = { is_superuser: false, permissions: ["orders.view_order"] };
    expect(can(user, "orders.view_order")).toBe(true);
    expect(can(user, "orders.add_order")).toBe(false);
  });

  it("requires ALL permissions when several are passed", () => {
    const user = {
      is_superuser: false,
      permissions: ["auth.view_user", "auth.view_group"],
    };
    expect(can(user, "auth.view_user", "auth.view_group")).toBe(true);
    expect(can(user, "auth.view_user", "auth.add_user")).toBe(false);
  });

  it("treats a missing permissions array as empty", () => {
    expect(can({ is_superuser: false }, "orders.view_order")).toBe(false);
  });
});
