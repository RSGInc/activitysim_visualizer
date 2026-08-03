"""Pure transformations for the Tour Mode page."""

from __future__ import annotations

import polars as pl

from dashboard.data_access import RunTables
from dashboard.helpers.category_helpers import add_percent_of_total

from .contracts import *


def _auto_sufficiency_basis_terms(config) -> tuple[str, str]:
    """Return explanatory and short display nouns for the configured basis."""
    return {
        "licensed_drivers": ("licensed drivers", "Drivers"),
        "workers": ("workers", "Workers"),
        "adults": ("adults", "Adults"),
    }[config.prepare_auto_sufficiency.basis]


def auto_sufficiency_display_label(auto_sufficiency: str, config) -> str:
    """Return the dashboard-facing label for an auto-sufficiency slice."""
    _, label_noun = _auto_sufficiency_basis_terms(config)
    return {
        "All": "All",
        "Zero Auto": "Zero Auto",
        "Auto Deficient": f"Fewer Vehicles Than {label_noun}",
        "Auto Sufficient": f"At Least As Many Vehicles as {label_noun}",
    }[auto_sufficiency]


def auto_sufficiency_definitions_markdown(config) -> str:
    """Describe the configured household basis behind the auto sufficiency split."""
    basis_noun, _ = _auto_sufficiency_basis_terms(config)
    deficient_label = auto_sufficiency_display_label("Auto Deficient", config)
    sufficient_label = auto_sufficiency_display_label("Auto Sufficient", config)
    return f"""
    **Auto sufficiency definitions**

    - **Zero Auto**: household has no vehicles.
    - **{deficient_label}**: household has fewer vehicles than {basis_noun}.
    - **{sufficient_label}**: household has at least as many vehicles as {basis_noun}.
    """


def vehicle_attribute_data(
    data_list: list[tuple[str, pl.DataFrame]],
    occupancy: str,
    *,
    category: str,
) -> list[tuple[str, pl.DataFrame]]:
    """Filter one allocated-vehicle summary to the selected occupancy level."""

    def sort_filtered(df: pl.DataFrame) -> pl.DataFrame:
        if "age" in df.columns:
            return (
                df.with_columns(
                    pl.when(pl.col("age").cast(pl.Utf8) == "20+")
                    .then(999)
                    .otherwise(pl.col("age").cast(pl.Int64, strict=False))
                    .alias("_sort_age")
                )
                .sort("_sort_age")
                .drop("_sort_age")
            )
        return df.sort(category) if category in df.columns else df

    def shape(df: pl.DataFrame) -> pl.DataFrame:
        filtered = df
        if "occupancy" in filtered.columns:
            filtered = filtered.with_columns(pl.col("occupancy").cast(pl.Utf8))
            if occupancy == "All":
                filtered = filtered.group_by(category).agg(
                    vehicle_count=pl.col("vehicle_count").sum()
                )
            else:
                filtered = filtered.filter(pl.col("occupancy") == occupancy)
        return sort_filtered(filtered)

    return RunTables.from_runs(data_list).map(shape)


def tour_mode_chart_data(
    data_list: list[tuple[str, pl.DataFrame]],
    purpose: str,
    auto_sufficiency: str,
    hidden_mode_values: set[str] | None = None,
) -> list[tuple[str, pl.DataFrame]]:
    """Build one tour mode distribution for a selected purpose and sufficiency slice."""
    value_col = {
        "All": "tour_count_all_households",
        "Zero Auto": "tour_count_zero_auto",
        "Auto Deficient": "tour_count_auto_deficient",
        "Auto Sufficient": "tour_count_auto_sufficient",
    }[auto_sufficiency]

    def shape(df: pl.DataFrame) -> pl.DataFrame:
        filtered = df.with_columns(pl.col("tour_purpose").cast(pl.Utf8)).filter(
            pl.col("tour_purpose") == purpose
        )
        chart_df = filtered.select(
            pl.col("tour_mode"),
            pl.col(value_col).alias("tour_count"),
        ).sort("tour_mode")
        chart_df = add_percent_of_total(
            [("run", chart_df)],
            value_col="tour_count",
            percent_col="tour_count_percent",
        )[0][1]
        if hidden_mode_values:
            chart_df = chart_df.with_columns(pl.col("tour_mode").cast(pl.Utf8)).filter(
                ~pl.col("tour_mode").is_in(sorted(hidden_mode_values))
            )
        return chart_df

    return RunTables.from_runs(data_list).map(shape)
