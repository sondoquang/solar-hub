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
  // Domain-info snapshots. The detail route ("*/domain-info/:siteId/") is
  // registered before the broad "*/sites/" glob for consistency with the file's
  // ordering convention (it does not actually overlap that glob).
  http.get("*/domain-info/:siteId/", ({ params }) =>
    HttpResponse.json({
      id: 1,
      site: Number(params.siteId),
      site_name: "Shop A",
      base_url: "https://a.example.com",
      host: "a.example.com",
      domain: "example.com",
      whois_status: "ok",
      whois_registrar: "GoDaddy.com, LLC",
      whois_created_at: "2020-01-02T00:00:00Z",
      whois_expires_at: "2027-01-02T00:00:00Z",
      whois_days_remaining: 180,
      whois_source: "rdap",
      whois_checked_at: "2026-07-01T00:00:00Z",
      dns_status: "ok",
      dns_records: { A: ["1.2.3.4"], MX: ["10 mail.example.com"], NS: ["ns1.example.com"] },
      dns_checked_at: "2026-07-01T00:00:00Z",
      ssl_status: "ok",
      ssl_issuer: "CN=R11,O=Let's Encrypt",
      ssl_subject: "CN=a.example.com",
      ssl_not_before: "2026-05-01T00:00:00Z",
      ssl_not_after: "2026-08-01T00:00:00Z",
      ssl_days_remaining: 20,
      ssl_checked_at: "2026-07-01T00:00:00Z",
      blacklist_status: "ok",
      blacklist_verdict: "clean",
      blacklist_results: [
        { list: "zen.spamhaus.org", target: "1.2.3.4", result: "clean", detail: "" },
      ],
      blacklist_checked_at: "2026-07-01T00:00:00Z",
      gindex_status: "skipped",
      gindex_indexed: null,
      gindex_total_results: null,
      gindex_checked_at: null,
      last_refreshed_at: "2026-07-01T00:00:00Z",
      last_error: "",
      is_pending: false,
    })
  ),
  http.post("*/domain-info/refresh-all/", () =>
    HttpResponse.json({ queued: true }, { status: 202 })
  ),
  http.post("*/domain-info/:siteId/refresh/", ({ params }) =>
    HttpResponse.json({ site: Number(params.siteId), is_pending: true }, { status: 202 })
  ),
  http.get("*/domain-info/", () =>
    HttpResponse.json({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 1,
          site: 1,
          site_name: "Shop A",
          domain: "example.com",
          whois_status: "ok",
          whois_expires_at: "2027-01-02T00:00:00Z",
          whois_days_remaining: 180,
          ssl_not_after: "2026-08-01T00:00:00Z",
          ssl_days_remaining: 20,
          blacklist_verdict: "clean",
          gindex_status: "skipped",
          gindex_indexed: null,
          last_refreshed_at: "2026-07-01T00:00:00Z",
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
  // Mail SMTP settings (singleton) + manual order email.
  http.get("*/mail-settings/", () =>
    HttpResponse.json({
      smtp_host: "smtp.gmail.com",
      smtp_port: 587,
      use_tls: true,
      use_ssl: false,
      username: "shop@gmail.com",
      from_email: "",
      from_name: "Solar Hub",
      recipients: ["boss@example.com"],
      digest_enabled: true,
      digest_times: ["09:00", "16:00"],
      has_password: true,
      last_digest_sent_at: "2026-06-24T09:00:00Z",
      updated_at: "2026-06-24T09:00:00Z",
    })
  ),
  http.patch("*/mail-settings/", async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json({
      smtp_host: "smtp.gmail.com",
      smtp_port: 587,
      use_tls: true,
      use_ssl: false,
      username: "shop@gmail.com",
      from_email: "",
      from_name: "Solar Hub",
      recipients: ["boss@example.com"],
      digest_enabled: true,
      digest_times: ["09:00", "16:00"],
      has_password: true,
      last_digest_sent_at: "2026-06-24T09:00:00Z",
      updated_at: "2026-06-24T10:00:00Z",
      ...body,
    });
  }),
  http.post("*/mail-settings/test/", () => HttpResponse.json({ ok: true })),
  http.post("*/orders/send_email/", async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json({
      sent: body.ids?.length ?? 0,
      recipient: body.recipient,
    });
  }),
  // --- RBAC: users / groups / permission catalog -------------------------
  // The specific "*/auth/users/:id/{action}/" routes MUST precede the broad
  // "*/auth/users/:id/" one, or the glob shadows them (file-wide convention).
  http.post("*/auth/users/:id/activate/", ({ params }) =>
    HttpResponse.json({ id: Number(params.id), is_active: true })
  ),
  http.post("*/auth/users/:id/set_password/", () =>
    new HttpResponse(null, { status: 204 })
  ),
  http.patch("*/auth/users/:id/", async ({ params, request }) => {
    const body = await request.json();
    return HttpResponse.json({
      id: Number(params.id),
      username: "nhanvien01",
      email: body.email ?? "nv@example.com",
      full_name: body.full_name || "Nguyễn Văn A",
      is_active: body.is_active ?? true,
      is_superuser: false,
      groups: [],
      last_login: null,
      date_joined: "2026-06-01T00:00:00Z",
    });
  }),
  http.delete("*/auth/users/:id/", () => new HttpResponse(null, { status: 204 })),
  http.post("*/auth/users/", async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json(
      {
        id: 99,
        username: body.username,
        email: body.email ?? "",
        full_name: body.full_name || body.username,
        is_active: true,
        is_superuser: false,
        groups: [],
        last_login: null,
        date_joined: "2026-07-01T00:00:00Z",
      },
      { status: 201 }
    );
  }),
  http.get("*/auth/users/", () =>
    HttpResponse.json({
      count: 2,
      next: null,
      previous: null,
      results: [
        {
          id: 1,
          username: "admin",
          email: "admin@example.com",
          full_name: "Quản trị",
          is_active: true,
          is_superuser: true,
          groups: [{ id: 1, name: "Quản trị viên" }],
          last_login: "2026-07-03T08:00:00Z",
          date_joined: "2026-01-01T00:00:00Z",
        },
        {
          id: 2,
          username: "marketing01",
          email: "mkt@example.com",
          full_name: "Trần Thị B",
          is_active: false,
          is_superuser: false,
          groups: [{ id: 3, name: "Marketing" }],
          last_login: null,
          date_joined: "2026-05-01T00:00:00Z",
        },
      ],
    })
  ),
  http.post("*/auth/groups/", async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json(
      {
        id: 42,
        name: body.name,
        permission_ids: body.permission_ids ?? [],
        permission_count: (body.permission_ids ?? []).length,
        user_count: 0,
      },
      { status: 201 }
    );
  }),
  http.patch("*/auth/groups/:id/", async ({ params, request }) => {
    const body = await request.json();
    return HttpResponse.json({
      id: Number(params.id),
      name: body.name ?? "Nhóm",
      permission_ids: body.permission_ids ?? [],
      permission_count: (body.permission_ids ?? []).length,
      user_count: 0,
    });
  }),
  http.delete("*/auth/groups/:id/", () => new HttpResponse(null, { status: 204 })),
  http.get("*/auth/groups/", () =>
    HttpResponse.json({
      count: 2,
      next: null,
      previous: null,
      results: [
        { id: 1, name: "Quản trị viên", permission_count: 83, user_count: 3 },
        { id: 3, name: "Marketing", permission_count: 7, user_count: 1 },
      ],
    })
  ),
  http.get("*/auth/permissions/", () =>
    HttpResponse.json([
      {
        module: "orders",
        label: "Đơn hàng",
        models: [
          {
            model: "order",
            label: "Đơn hàng",
            permissions: [
              { id: 10, codename: "view_order", perm: "orders.view_order", label: "Xem", is_custom: false },
              { id: 11, codename: "add_order", perm: "orders.add_order", label: "Thêm", is_custom: false },
              { id: 12, codename: "change_order", perm: "orders.change_order", label: "Sửa", is_custom: false },
              { id: 13, codename: "delete_order", perm: "orders.delete_order", label: "Xóa", is_custom: false },
              { id: 14, codename: "forward_order", perm: "orders.forward_order", label: "Có thể chuyển đơn sang marketing", is_custom: true },
            ],
          },
        ],
      },
      {
        module: "domains",
        label: "Tên miền",
        models: [
          {
            model: "domaininfo",
            label: "Thông tin tên miền",
            permissions: [
              { id: 20, codename: "view_domaininfo", perm: "domains.view_domaininfo", label: "Xem", is_custom: false },
              { id: 21, codename: "refresh_domaininfo", perm: "domains.refresh_domaininfo", label: "Có thể kiểm tra lại thông tin tên miền", is_custom: true },
            ],
          },
        ],
      },
    ])
  ),
];
