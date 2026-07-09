"""Shared logging helper: consistent, grep-friendly ``event key=value`` lines.

Every module keeps its own ``logger = logging.getLogger(__name__)`` (so the
verbose formatter still shows the real module + function). This helper only
standardizes the *message* so log lines across the codebase parse the same way::

    log_event(logger, logging.INFO, "push_products", site_id=3, count=42)
    # → INFO ... apps.catalog.services.push_products:1201 push_products site_id=3 count=42

Rules (CLAUDE.md #4 — no PII):
    Pass only ids / counts / status / durations. NEVER pass customer name,
    phone, address or email — file logs live on a host volume.

Fields whose value is ``None`` are dropped, so callers can pass optional context
without branching. Insertion order is preserved (Python ``**kwargs`` are
ordered), so the same call site always emits fields in the same order.
"""

import logging

__all__ = ["log_event", "format_fields"]


def _render_value(value) -> str:
    """Render a single field value; quote it if it would break ``key=value``."""
    text = str(value)
    if text == "" or any(ch.isspace() for ch in text) or "=" in text:
        # Wrap so a value with spaces/= stays one token when grepping/splitting.
        return '"' + text.replace('"', '\\"') + '"'
    return text


def format_fields(**fields) -> str:
    """Turn ``k1=v1 k2=v2`` from kwargs, dropping ``None`` values."""
    return " ".join(
        f"{key}={_render_value(value)}"
        for key, value in fields.items()
        if value is not None
    )


def log_event(logger, level, event, *, exc_info=False, **fields) -> None:
    """Emit ``event k1=v1 k2=v2`` at ``level`` on ``logger``.

    Args:
        logger: a ``logging.Logger`` (usually ``logging.getLogger(__name__)``).
        level: ``logging.INFO`` / ``logging.WARNING`` / ... (int) or level name.
        event: short, stable identifier — conventionally ``<func> <phase>``,
            e.g. ``"push_products start"`` / ``"push_products ok"``.
        exc_info: pass ``True`` inside an ``except`` block to attach the traceback.
        **fields: safe context only (ids/counts/status/durations, no PII).
    """
    if isinstance(level, str):
        level = logging.getLevelName(level.upper())
    if not logger.isEnabledFor(level):
        return  # skip building the message when the level is filtered out
    suffix = format_fields(**fields)
    message = f"{event} {suffix}" if suffix else event
    # stacklevel=2 so %(funcName)s / %(lineno)d resolve to the CALLER of
    # log_event (the real function being logged), not this helper.
    logger.log(level, message, exc_info=exc_info, stacklevel=2)
