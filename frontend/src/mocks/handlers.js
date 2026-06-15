import { http, HttpResponse } from "msw";

export const handlers = [
  http.get("*/health/", () =>
    HttpResponse.json({ status: "ok", db: true, redis: true })
  ),
  // Must precede the broad "*/sites/" handler — that glob also matches
  // "/products/categories/{id}/sites/" and would shadow this one.
  http.get("*/products/categories/:id/sites/", () =>
    HttpResponse.json([
      {
        site_id: 1,
        site_name: "solarcity.com.vn",
        site_url: "https://solarcity.com.vn",
        site_status: "up",
        platform: "woocommerce",
        is_primary: true,
        linked: true,
        woo_category_id: 872,
        woo_name: "Ắc quy",
        last_synced_at: "2026-06-12T10:15:00Z",
      },
      {
        site_id: 2,
        site_name: "demowp.com",
        site_url: "https://demowp.com",
        site_status: "down",
        platform: "woocommerce",
        is_primary: false,
        linked: false,
        woo_category_id: null,
        woo_name: "",
        last_synced_at: null,
      },
    ])
  ),
  http.get("*/products/categories/mappings/", () =>
    HttpResponse.json({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 7,
          woo_category_id: 220,
          woo_name: " Pin  mặt trời ",
          category_id: 3,
          category_name: "Pin mặt trời",
          category_parent_id: 1,
          category_parent_name: "Sản phẩm",
          last_synced_at: "2026-06-11T09:00:00Z",
        },
      ],
    })
  ),
  http.get("*/sites/", () =>
    HttpResponse.json({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 1,
          name: "Shop A",
          base_url: "https://a.example.com",
          platform: "woocommerce",
          consumer_key: "ck_a",
          status: "up",
          last_checked_at: "2026-06-04T10:00:00Z",
          created_at: "2026-06-01T00:00:00Z",
          updated_at: "2026-06-04T10:00:00Z",
        },
      ],
    })
  ),
  http.get("*/products/categories/overview/", () =>
    HttpResponse.json({
      hub_used: 1245,
      hub_total: 1328,
      linked: 1102,
      unlinked: 143,
      linked_pct: 88.5,
      site_count: 6,
      root_count: 210,
      child_count: 1035,
      deleted_count: 53,
    })
  ),
  http.get("*/products/categories/matrix/", () =>
    HttpResponse.json({
      count: 1,
      next: null,
      previous: null,
      sites: [
        { id: 1, name: "solarcity.com.vn", base_url: "https://solarcity.com.vn", platform: "woocommerce" },
        { id: 2, name: "demowp.com", base_url: "https://demowp.com", platform: "woocommerce" },
      ],
      results: [
        {
          id: 7,
          name: "Ắc quy Phoenix",
          parent_name: "Ắc quy",
          linked_site_count: 1,
          cells: { 1: { woo_id: 124, woo_name: "Ắc Quy Phoenix" } },
        },
      ],
    })
  ),
  http.post("*/products/categories/clear_all/", () =>
    HttpResponse.json({
      categories_cleared: 1180,
      categories_kept: 148,
      mappings_cleared: 4200,
      history_cleared: 156,
    })
  ),
  http.get("*/products/categories/", () =>
    HttpResponse.json({
      count: 2,
      next: null,
      previous: null,
      results: [
        { id: 1, name: "Ắc quy", slug: "ac-quy", parent: null, mapping_count: 6 },
        { id: 7, name: "Ắc quy Phoenix", slug: "ac-quy-phoenix", parent: 1, mapping_count: 4 },
      ],
    })
  ),
  http.get("*/sync/category-runs/stats/", () =>
    HttpResponse.json({
      total: 156,
      success: 132,
      partial: 16,
      error: 8,
      last_run: {
        run_id: "11111111-1111-1111-1111-111111111111",
        started_at: "2026-06-12T10:15:00Z",
        site_count: 1,
        site_label: "solarcity.com.vn",
        status: "success",
      },
    })
  ),
  http.get("*/sync/category-runs/", () =>
    HttpResponse.json({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          run_id: "11111111-1111-1111-1111-111111111111",
          started_at: "2026-06-12T10:15:12Z",
          site_count: 1,
          total_pulled: 872,
          total_mapped: 557,
          error_count: 0,
          status: "success",
          duration_seconds: 272,
          triggered_by: "admin",
          site_label: "solarcity.com.vn",
        },
      ],
    })
  ),
  // Manual sync triggers return a run_id + expected so the progress banner can
  // poll completion (orders / products). run-progress reports it done at once.
  http.post("*/orders/poll_now/", () =>
    HttpResponse.json({
      task_id: "task-mock",
      status: "processing",
      run_id: "22222222-2222-2222-2222-222222222222",
      expected: 1,
    })
  ),
  http.post("*/products/sync_now/", () =>
    HttpResponse.json({
      task_id: "task-mock",
      run_id: "33333333-3333-3333-3333-333333333333",
      expected: 1,
    })
  ),
  http.get("*/sync/run-progress/:runId/", ({ params }) =>
    HttpResponse.json({
      run_id: params.runId,
      operation: "poll_orders",
      done: 1,
      error_count: 0,
    })
  ),
];
