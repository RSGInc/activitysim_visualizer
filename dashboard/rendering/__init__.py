"""Context-bound dashboard rendering services."""

from dashboard.rendering.context import RenderContext
from dashboard.rendering.plotter import FigureBuilder, Plotter
from dashboard.rendering.layout import (
    control_row,
    control_row_spacer,
    data_unavailable_card,
    run_legend_entries,
    run_legend_panes,
    selector_row,
)
from dashboard.rendering.tables import (
    column_titles,
    data_table,
    drop_index_columns,
    format_numeric,
    format_numeric_frame,
    standardize_keys,
    to_pandas,
)

__all__ = [
    "FigureBuilder", "Plotter", "RenderContext", "column_titles",
    "control_row", "control_row_spacer", "data_table", "data_unavailable_card",
    "drop_index_columns", "format_numeric", "format_numeric_frame",
    "run_legend_entries", "run_legend_panes", "selector_row", "standardize_keys",
    "to_pandas",
]
