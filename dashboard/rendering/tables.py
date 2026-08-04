"""Panel table rendering and display-only numeric formatting."""

from __future__ import annotations

import html
import math

import numpy as np
import panel as pn
import polars as pl

from dashboard.data_access import RunTableData, RunTables
from dashboard.rendering.labels import attach_full_tab_titles, display_label_map

TableData = RunTables | RunTableData


def to_pandas(frame: pl.DataFrame):
    categorical = [name for name in frame.columns if frame[name].dtype == pl.Categorical]
    if categorical:
        frame = frame.with_columns(pl.col(name).cast(pl.Utf8) for name in categorical)
    return frame.to_pandas()


def format_numeric(value, *, precision: int | None = 2):
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return value
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not math.isfinite(number):
            return None
        if number.is_integer():
            return str(int(number))
        if precision is None:
            return str(number)
        if precision <= 0:
            return str(int(round(number)))
        decimals = precision - 1 - math.floor(math.log10(abs(number)))
        rounded = round(number, decimals)
        if float(rounded).is_integer():
            return str(int(rounded))
        return f"{rounded:.{max(decimals, 0)}f}".rstrip("0").rstrip(".")
    return value


def format_numeric_frame(
    frame: pl.DataFrame,
    *,
    numeric_precision: int | None = 2,
    numeric_precision_by_column: dict[str, int] | None = None,
) -> pl.DataFrame:
    if numeric_precision is None and not numeric_precision_by_column:
        return frame
    expressions = []
    for column, dtype in frame.schema.items():
        if not getattr(dtype, "is_numeric", lambda: False)():
            continue
        precision = (
            numeric_precision_by_column[column]
            if numeric_precision_by_column and column in numeric_precision_by_column
            else numeric_precision
        )
        expressions.append(
            pl.col(column).map_elements(
                lambda value, digits=precision: format_numeric(value, precision=digits),
                return_dtype=pl.Utf8,
            ).alias(column)
        )
    return frame.with_columns(expressions) if expressions else frame


def drop_index_columns(frame: pl.DataFrame) -> pl.DataFrame:
    columns = [
        column for column in frame.columns
        if column == "index" or column.startswith("__index_level_")
    ]
    return frame.drop(columns) if columns else frame


_WORD_OVERRIDES = {
    "aadt": "AADT", "am": "AM", "av": "AV", "avg": "Average",
    "brt": "BRT", "cvm": "CVM", "da": "DA", "dest": "Destination",
    "hh": "Household", "hov": "HOV", "hov2": "HOV2", "hov3": "HOV3",
    "id": "ID", "ids": "IDs", "lrt": "LRT", "maz": "MAZ", "md": "MD",
    "mgra": "MGRA", "n": "Number", "nonmandatory": "Non-Mandatory",
    "num": "Number", "orig": "Origin", "pm": "PM", "pmt": "PMT",
    "pct": "Percent", "rmse": "RMSE", "sov": "SOV", "tap": "TAP",
    "taz": "TAZ", "tnc": "TNC", "tod": "Time of Day", "vmt": "VMT",
    "vol": "Volume",
}
_NAME_OVERRIDES = {
    "% Diff": "% Diff", "FACTYPE": "Facility Type",
    "From_Node": "From Node", "To_Node": "To Node",
}


def humanize_column(column: object) -> str:
    name = str(column)
    if name in _NAME_OVERRIDES:
        return _NAME_OVERRIDES[name]
    if " " in name and "_" not in name:
        return name
    words = []
    for token in (token for token in name.replace("-", "_").split("_") if token):
        lower = token.lower()
        if lower in _WORD_OVERRIDES:
            words.append(_WORD_OVERRIDES[lower])
        elif lower in {"and", "of"}:
            words.append(lower)
        elif token.isupper() and len(token) > 1:
            words.append(token)
        else:
            words.append(token[:1].upper() + token[1:].lower())
    return " ".join(words).replace("Non Mandatory", "Non-Mandatory") or name


def column_titles(columns: list[object] | tuple[object, ...]) -> dict[str, str]:
    titles, counts = {}, {}
    for column in columns:
        title = humanize_column(column)
        counts[title] = counts.get(title, 0) + 1
        titles[str(column)] = f"{title} ({counts[title]})" if counts[title] > 1 else title
    return titles


def column_title_metadata(
    columns: list[object] | tuple[object, ...],
) -> tuple[dict[str, str], dict[str, str]]:
    """Return compact column titles and full tooltips for truncated titles."""
    full_titles = column_titles(columns)
    display_titles = display_label_map(full_titles.values())
    titles = {
        column: display_titles[full_title]
        for column, full_title in full_titles.items()
    }
    tooltips = {
        column: full_title
        for column, full_title in full_titles.items()
        if titles[column] != full_title
    }
    return titles, tooltips


def data_table(
    data: TableData,
    title: str = "",
    height: int = 300,
    numeric_precision: int | None = 2,
    numeric_precision_by_column: dict[str, int] | None = None,
    column_sorters: dict[str, str] | None = None,
) -> pn.viewable.Viewable:
    data = list(data)
    tabs = pn.Tabs()
    full_labels = [str(label) for label, frame in data if not frame.is_empty()]
    display_labels = display_label_map(full_labels)
    for label, frame in data:
        if frame.is_empty():
            continue
        full_label = str(label)
        display = format_numeric_frame(
            drop_index_columns(frame),
            numeric_precision=numeric_precision,
            numeric_precision_by_column=numeric_precision_by_column,
        )
        configuration = {}
        if column_sorters:
            configuration["columns"] = [
                {"field": str(column), "sorter": sorter}
                for column, sorter in column_sorters.items()
                if str(column) in display.columns
            ]
        titles, header_tooltips = column_title_metadata(display.columns)
        table = pn.widgets.Tabulator(
            to_pandas(display), height=height, sizing_mode="stretch_width",
            theme="simple", titles=titles, header_tooltips=header_tooltips,
            show_index=False, configuration=configuration,
        )
        tab_content: pn.viewable.Viewable = table
        if display_labels[full_label] != full_label:
            tab_content = pn.Column(
                pn.pane.HTML(
                    f'<div class="run-table-full-label"><b>Run:</b> '
                    f"{html.escape(full_label)}</div>"
                ),
                table,
            )
        tabs.append((display_labels[full_label], tab_content))
    attach_full_tab_titles(tabs, full_labels)
    return pn.Column(pn.pane.Markdown(f"### {title}"), tabs) if title else tabs


def standardize_keys(data: TableData, key: str, value: str) -> list[tuple[str, pl.DataFrame]]:
    keys = {item for _, frame in data for item in frame[key].to_list()}
    output = []
    for label, frame in data:
        base = pl.DataFrame({key: list(keys)})
        output.append((label, base.join(frame.select(key, value), on=key, how="left").fill_null(0).sort(key)))
    return output
