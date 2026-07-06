import { describe, expect, it } from "vitest";

import { buildDuplicateDefaults } from "./Products.jsx";

// A product row as the list endpoint returns it (full MasterProductSerializer).
const product = {
  id: 42,
  sku: "SP-100",
  name: "Pin mặt trời 450W",
  match_name: "Pin mặt trời 450W",
  type: "variable",
  description: "<p>Mô tả dài</p>",
  short_description: "Mô tả ngắn",
  regular_price: "1500000.00",
  sale_price: "1400000.00",
  status: "publish",
  stock_status: "instock",
  weight: "12.500",
  images: ["https://hub/media/a.png", "https://hub/media/b.png"],
  categories: ["Pin mặt trời"],
  external_url: "",
  button_text: "",
  grouped_skus: [],
  attributes: [{ name: "Công suất", options: ["450W"], variation: true, visible: true }],
  variations: [{ sku: "SP-100-1", regular_price: "1500000.00", attributes: { "Công suất": "450W" } }],
  mappings: [{ site: 1, site_name: "site-1", woo_product_id: 7, last_synced_at: "2026-01-01" }],
  mapping_count: 1,
  source_site: 3,
  source_site_name: "Trang chính",
  imported_at: "2026-05-01T00:00:00Z",
  created_at: "2026-05-01T00:00:00Z",
  updated_at: "2026-06-01T00:00:00Z",
};

describe("buildDuplicateDefaults", () => {
  it("strips every identity/audit field so the copy is a brand-new product", () => {
    const dup = buildDuplicateDefaults(product);
    for (const key of [
      "id",
      "mappings",
      "mapping_count",
      "match_name",
      "source_site",
      "source_site_name",
      "imported_at",
      "created_at",
      "updated_at",
    ]) {
      expect(dup).not.toHaveProperty(key);
    }
  });

  it("suggests a unique SKU (-COPY) and a distinguishable name ((Copy))", () => {
    const dup = buildDuplicateDefaults(product);
    expect(dup.sku).toBe("SP-100-COPY");
    expect(dup.name).toBe("Pin mặt trời 450W (Copy)");
  });

  it("keeps all content fields intact for pre-fill", () => {
    const dup = buildDuplicateDefaults(product);
    expect(dup.type).toBe("variable");
    expect(dup.description).toBe("<p>Mô tả dài</p>");
    expect(dup.regular_price).toBe("1500000.00");
    expect(dup.images).toEqual(["https://hub/media/a.png", "https://hub/media/b.png"]);
    expect(dup.categories).toEqual(["Pin mặt trời"]);
    expect(dup.attributes).toEqual(product.attributes);
    expect(dup.variations).toEqual(product.variations);
  });

  it("leaves SKU/name blank when the source has none", () => {
    const dup = buildDuplicateDefaults({ type: "simple" });
    expect(dup.sku).toBe("");
    expect(dup.name).toBe("");
  });
});
