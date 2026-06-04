"""WooClient — the single wrapper for all WooCommerce REST API traffic.

Every call to a WooCommerce site MUST go through this class (project rule).
This is a scaffold skeleton: the request methods are not implemented yet and
raise ``NotImplementedError`` until the sites/sync features are built.

Design notes (see tech-stack §4.4 and docs/backend/ARCHITECTURE.md):
- Per-call timeouts and ``raise_for_status()`` once implemented.
- Throttle + batch endpoints when syncing many sites.
- ``consumer_secret`` is decrypted (Fernet) by the future ``sites`` layer and
  passed in as plaintext here, so this skeleton has no model dependency.
"""


class WooClient:
    def __init__(self, base_url: str, consumer_key: str, consumer_secret: str) -> None:
        self.base = base_url.rstrip("/") + "/wp-json/wc/v3"
        self._auth = (consumer_key, consumer_secret)

    def list_orders(
        self,
        after: str | None = None,
        status: str = "processing",
        per_page: int = 100,
    ) -> list[dict]:
        raise NotImplementedError

    def batch_products(
        self,
        create: list[dict] | None = None,
        update: list[dict] | None = None,
        delete: list[int] | None = None,
    ) -> dict:
        raise NotImplementedError

    def system_status(self) -> dict:
        raise NotImplementedError
