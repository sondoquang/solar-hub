"""Unit tests for the shared ``log_event`` / ``format_fields`` helper.

Pure logging behaviour — no DB, so no ``django_db`` marker. A private list
handler is attached to a throwaway logger so capture never depends on the
project's ``propagate=False`` app-logger config.
"""

import logging

from apps.core.logging_utils import format_fields, log_event


class _ListHandler(logging.Handler):
    """Collect emitted records into a list for assertions."""

    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


def _capture(logger_name: str, level: int = logging.INFO) -> _ListHandler:
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    handler = _ListHandler()
    logger.addHandler(handler)
    return handler


# --- format_fields -----------------------------------------------------------


def test_format_fields_basic():
    assert format_fields(a=1, b="x") == "a=1 b=x"


def test_format_fields_drops_none():
    # Optional context can be passed unconditionally; None is elided.
    assert format_fields(a=1, b=None, c=3) == "a=1 c=3"


def test_format_fields_preserves_kwarg_order():
    assert format_fields(z=1, a=2, m=3) == "z=1 a=2 m=3"


def test_format_fields_quotes_values_with_spaces_or_equals():
    assert format_fields(msg="hello world") == 'msg="hello world"'
    assert format_fields(kv="a=b") == 'kv="a=b"'
    assert format_fields(empty="") == 'empty=""'


def test_format_fields_empty_when_all_none():
    assert format_fields(a=None) == ""


# --- log_event ---------------------------------------------------------------


def test_log_event_renders_event_and_fields():
    handler = _capture("test.logevent.render")
    logger = logging.getLogger("test.logevent.render")
    try:
        log_event(logger, logging.INFO, "push_products start", site_id=3, run_id=None)
    finally:
        logger.removeHandler(handler)

    assert len(handler.records) == 1
    record = handler.records[0]
    # run_id=None dropped; site_id kept.
    assert record.getMessage() == "push_products start site_id=3"
    assert record.levelno == logging.INFO


def test_log_event_accepts_level_name():
    handler = _capture("test.logevent.levelname", level=logging.WARNING)
    logger = logging.getLogger("test.logevent.levelname")
    try:
        log_event(logger, "warning", "poll_site fail", site_id=1)
    finally:
        logger.removeHandler(handler)

    assert len(handler.records) == 1
    assert handler.records[0].levelno == logging.WARNING


def test_log_event_bare_event_without_fields():
    handler = _capture("test.logevent.bare")
    logger = logging.getLogger("test.logevent.bare")
    try:
        log_event(logger, logging.INFO, "task start")
    finally:
        logger.removeHandler(handler)

    assert handler.records[0].getMessage() == "task start"


def test_log_event_skips_when_level_filtered_out():
    handler = _capture("test.logevent.filtered", level=logging.WARNING)
    logger = logging.getLogger("test.logevent.filtered")
    try:
        log_event(logger, logging.INFO, "debugish", x=1)  # below WARNING → dropped
    finally:
        logger.removeHandler(handler)

    assert handler.records == []
