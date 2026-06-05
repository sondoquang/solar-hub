import { http, HttpResponse } from "msw";

export const handlers = [
  http.get("*/health/", () =>
    HttpResponse.json({ status: "ok", db: true, redis: true })
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
          consumer_key: "ck_a",
          status: "up",
          last_checked_at: "2026-06-04T10:00:00Z",
          created_at: "2026-06-01T00:00:00Z",
          updated_at: "2026-06-04T10:00:00Z",
        },
      ],
    })
  ),
];
