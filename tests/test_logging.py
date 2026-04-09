from __future__ import annotations

import logging
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from activitysim_viz_logging import configure_logging, get_logger, shutdown_logging
from dashboard.page_registry import resolve_page_definitions
from test_export_html import _write_config


def _flush_logger_handlers(logger_name: str = "activitysim_viz") -> None:
    logger = logging.getLogger(logger_name)
    for handler in logger.handlers:
        handler.flush()


def test_configure_logging_writes_to_console_and_log_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _write_config(tmp_path)
    log_path = configure_logging(config)

    get_logger("main").info("console-and-file-check")
    _flush_logger_handlers()
    captured = capsys.readouterr()

    assert "console-and-file-check" in captured.out
    assert log_path.exists()
    assert "console-and-file-check" in log_path.read_text(encoding="utf-8")
    shutdown_logging()


def test_warning_paths_are_written_to_log_file(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = _write_config(tmp_path, dashboard_pages=None)
    log_path = configure_logging(config)
    caplog.set_level(logging.WARNING, logger="activitysim_viz")

    resolve_page_definitions(config)
    _flush_logger_handlers()

    expected = (
        "Warning: config does not define 'dashboard_pages'. "
        "Using legacy behavior and including the default dashboard pages."
    )
    assert expected in caplog.text
    assert expected in log_path.read_text(encoding="utf-8")
    shutdown_logging()
