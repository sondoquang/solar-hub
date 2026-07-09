"""Sanity checks on the project LOGGING dictConfig (config/settings.py).

No DB needed — asserts the config shape + that the rotating-file handlers can
actually be instantiated (the log dir exists).
"""

import logging.config
import os

from django.conf import settings


def test_file_handlers_are_rotating():
    handlers = settings.LOGGING["handlers"]
    assert set(handlers) >= {"console", "file", "error_file"}
    assert handlers["file"]["class"] == "logging.handlers.RotatingFileHandler"
    assert handlers["error_file"]["class"] == "logging.handlers.RotatingFileHandler"
    # error_file only keeps warnings+ so failures are easy to find.
    assert handlers["error_file"]["level"] == "WARNING"


def test_verbose_formatter_includes_function_name():
    fmt = settings.LOGGING["formatters"]["verbose"]["format"]
    assert "%(funcName)s" in fmt
    assert "%(name)s" in fmt


def test_apps_logger_writes_to_console_and_file():
    apps_logger = settings.LOGGING["loggers"]["apps"]
    assert set(apps_logger["handlers"]) >= {"console", "file", "error_file"}
    assert apps_logger["propagate"] is False


def test_log_dir_exists():
    assert os.path.isdir(settings.LOG_DIR)


def test_config_is_installable():
    # Building the handlers must not raise (validates filenames/dir/levels).
    logging.config.dictConfig(settings.LOGGING)
