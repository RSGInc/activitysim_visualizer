from __future__ import annotations

import logging
from pathlib import Path
import sys

import panel as pn
import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from activitysim_viz_logging import configure_logging, get_logger, shutdown_logging
from dashboard.app import build_dashboard
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from processor.summarize.cache import create_summary_run
from test_export_html import _full_summary_run, _write_config


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
) -> None:
    config = _write_config(tmp_path, dashboard_pages=["trip_summaries"])
    log_path = configure_logging(config)
    missing_summary_run = create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": {},
            "unweighted": {},
        },
        source_run_dir="C:/runs/base",
    )

    build_dashboard([], config, summary_runs=[missing_summary_run])
    _flush_logger_handlers()

    expected = "requires summary 'trip_purpose_distribution'"
    assert expected in log_path.read_text(encoding="utf-8")
    shutdown_logging()


class _PreparedWarningProbePage(DashboardPage):
    def build_page(self):
        return self.new_section(pn.pane.Markdown("Probe"))

    def _refresh(self) -> None:
        self.require_prepared_runs()


_PreparedWarningProbePage.definition = DashboardPageDefinition(
    page_id="prepared_warning_probe",
    title="Prepared Warning Probe",
    page_cls=_PreparedWarningProbePage,
    prepared_data_mode="required",
    required_prepared_tables=("trips",),
)


def test_prepared_data_placeholder_warning_is_written_to_log_file(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    log_path = configure_logging(config)
    page = _PreparedWarningProbePage(
        build_dashboard([], config, summary_runs=[_full_summary_run()])._dashboard_state,
        config,
    )

    page.refresh(force=True)
    _flush_logger_handlers()

    assert "requires prepared run data" in log_path.read_text(encoding="utf-8")
    shutdown_logging()
