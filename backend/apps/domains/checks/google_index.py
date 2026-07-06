"""Google index check via the Custom Search JSON API (``site:`` query).

Config-gated: without GOOGLE_CSE_API_KEY / GOOGLE_CSE_CX the check returns
"skipped" (UI: "Bỏ qua — chưa cấu hình"). Scraping google.com is not an option
(ToS). The free quota is 100 queries/day, so the service layer gives this check
its own long cadence (DOMAIN_GINDEX_INTERVAL_SECONDS).
"""

from . import http_pool

ENDPOINT = "https://www.googleapis.com/customsearch/v1"


def check_google_index(
    domain: str, *, api_key: str, cse_id: str, timeout: float = 10.0
) -> dict:
    if not api_key or not cse_id:
        return {"status": "skipped"}
    try:
        resp = http_pool._POOL.get(
            ENDPOINT,
            params={"key": api_key, "cx": cse_id, "q": f"site:{domain}", "num": 1},
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__}
    try:
        total = int(payload.get("searchInformation", {}).get("totalResults") or 0)
    except (TypeError, ValueError):
        total = 0
    return {"status": "ok", "indexed": total > 0, "total_results": total}
