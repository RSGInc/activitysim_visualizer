"""Core data and utility modules for the marimo ActivitySim visualizer."""

from .charts import apply_standard_layout, bar_chart, density_chart, kpi_card_html, line_chart, run_color
from .config import load_config
from .io import load_runs, read_run
from .models import Config, PreparedRuns, RunData, RunSpec
from .pages import build_page_controls, render_page
from .prepare import compute_weights, load_and_prepare_runs, prepare_run, strip_weights
from .tables import (
    kpi_format_mapping,
    make_run_tables,
    make_table,
    percent_difference_format_mapping,
    percent_difference_table,
    prepare_table_df,
)
from .writer import build_run_summaries, write_all, write_prepared_run_summaries

__all__ = [
    "apply_standard_layout",
    "bar_chart",
    "build_page_controls",
    "build_run_summaries",
    "Config",
    "PreparedRuns",
    "RunData",
    "RunSpec",
    "compute_weights",
    "density_chart",
    "kpi_card_html",
    "line_chart",
    "load_and_prepare_runs",
    "load_config",
    "load_runs",
    "kpi_format_mapping",
    "make_run_tables",
    "make_table",
    "percent_difference_format_mapping",
    "percent_difference_table",
    "prepare_run",
    "prepare_table_df",
    "read_run",
    "render_page",
    "run_color",
    "strip_weights",
    "write_all",
    "write_prepared_run_summaries",
]
