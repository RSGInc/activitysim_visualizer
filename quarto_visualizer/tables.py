"""UI-neutral table and frame helpers for the Quarto migration."""
from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from quarto_visualizer.summary_bundle import RunFrameList


def normalize_display_frame(df: pl.DataFrame) -> pl.DataFrame:
    """Cast categoricals to strings for stable display and plotting."""
    cat_cols = [c for c in df.columns if df[c].dtype == pl.Categorical]
    if cat_cols:
        return df.with_columns([pl.col(c).cast(pl.Utf8) for c in cat_cols])
    return df


def concat_run_frames(frames: RunFrameList, *, run_col: str = "run") -> pl.DataFrame:
    """Concatenate run-labeled frames into one display table."""
    rows: list[pl.DataFrame] = []
    for label, df in frames:
        if df is None:
            continue
        display_df = normalize_display_frame(df)
        rows.append(display_df.with_columns(pl.lit(label).alias(run_col)).select([run_col, *display_df.columns]))
    return pl.concat(rows, how="diagonal") if rows else pl.DataFrame()


def filter_run_frames(
    frames: RunFrameList,
    column: str,
    value: str,
    *,
    all_value: str | None = None,
) -> RunFrameList:
    """Filter each run frame to rows where ``column == value`` unless the all-value is selected."""
    result: list[tuple[str, pl.DataFrame]] = []
    for label, df in frames:
        if df is None or len(df) == 0:
            result.append((label, pl.DataFrame()))
            continue
        display_df = normalize_display_frame(df)
        if column in display_df.columns and (all_value is None or value != all_value):
            display_df = display_df.filter(pl.col(column).cast(pl.Utf8) == str(value))
        result.append((label, display_df))
    return tuple(result)


def unique_values(frames: RunFrameList, column: str) -> tuple[str, ...]:
    """Return sorted unique string values from a run-frame collection."""
    values: set[str] = set()
    for _, df in frames:
        if df is not None and len(df) > 0 and column in df.columns:
            values.update(str(v) for v in normalize_display_frame(df)[column].drop_nulls().cast(pl.Utf8).unique().to_list())
    return tuple(sorted(values))


def standardize_run_frames(
    frames: RunFrameList,
    key_col: str,
    value_col: str,
    *,
    sort_keys: bool = False,
) -> RunFrameList:
    """Fill missing keys across runs with zeros for a single x/y series."""
    if not frames:
        return tuple()

    ordered_keys: list[object] = []
    seen: set[str] = set()
    for _, df in frames:
        if df is None or len(df) == 0 or key_col not in df.columns:
            continue
        for value in normalize_display_frame(df)[key_col].to_list():
            marker = str(value)
            if marker not in seen:
                seen.add(marker)
                ordered_keys.append(value)

    if sort_keys:
        ordered_keys = sorted(ordered_keys)

    base = pl.DataFrame({key_col: ordered_keys})
    rows: list[tuple[str, pl.DataFrame]] = []
    for label, df in frames:
        if df is None or len(df) == 0 or key_col not in df.columns or value_col not in df.columns:
            rows.append((label, base.with_columns(pl.lit(0.0).alias(value_col))))
            continue
        display_df = normalize_display_frame(df)
        merged = base.join(display_df.select([key_col, value_col]), on=key_col, how="left").fill_null(0)
        rows.append((label, merged))
    return tuple(rows)


def percent_difference_table(
    frames: RunFrameList,
    *,
    metrics: Sequence[str] | None = None,
    labels: dict[str, str] | None = None,
) -> pl.DataFrame:
    """Build a percent-difference table against the first run for one-row summary frames."""
    if not frames:
        return pl.DataFrame()

    base_label, base_df = frames[0]
    if base_df is None or len(base_df) == 0:
        return pl.DataFrame()

    if metrics is None:
        metrics = [
            col for col in base_df.columns
            if base_df[col].dtype.is_numeric()
        ]

    rows: list[dict[str, object]] = []
    for metric in metrics:
        display_name = labels.get(metric, metric) if labels else metric
        base_val = float(base_df[metric][0]) if metric in base_df.columns else 0.0
        row: dict[str, object] = {"Metric": display_name, base_label: "0.00%"}
        for run_label, df in frames[1:]:
            val = float(df[metric][0]) if df is not None and len(df) > 0 and metric in df.columns else 0.0
            pct = ((val - base_val) / base_val * 100.0) if base_val != 0 else 0.0
            row[run_label] = f"{pct:.2f}%"
        rows.append(row)
    return pl.DataFrame(rows) if rows else pl.DataFrame()
