"""Profile and distribution-style tour summaries."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import summary
from processor.summarize.summaries.summary_helpers import (
    ALL_TOUR_PURPOSES,
    _all_purpose_rollup,
    _rounded_distance_bin_expr,
    _summary_purpose_column,
    weighted_group_sum,
)
from runtime.config import Config


def _tour_weights_for_summary(tours: pl.DataFrame) -> pl.DataFrame:
    """Apply current joint-tour weighting semantics for tour-level summaries."""
    return tours.with_columns(
        pl.when(pl.col("tour_category").cast(pl.Utf8).str.to_lowercase() == "joint")
        .then(pl.col("finalweight") * pl.col("NUMBER_HH").cast(pl.Float64))
        .otherwise(pl.col("finalweight"))
        .alias("_tour_weight"),
    )


@summary(
    id="tour_mode_by_tour_purpose_and_auto_sufficiency",
    schema={
        "tour_mode": pl.Utf8,
        "tour_purpose": pl.Utf8,
        "tour_count_zero_auto": pl.Float64,
        "tour_count_auto_deficient": pl.Float64,
        "tour_count_auto_sufficient": pl.Float64,
        "tour_count_all_households": pl.Float64,
    },
    required_columns={
        "tours": ("tour_mode", "tour_purpose", "finalweight", "AUTOSUFF")
    },
)
def tour_mode(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"tour_mode", "tour_purpose", "finalweight", "AUTOSUFF"}
    if (
        not required.issubset(set(rd.tours.columns))
        or "tour_category" not in rd.tours.columns
    ):
        return tour_mode.empty()

    purpose_col = _summary_purpose_column(rd.tours)
    if not purpose_col:
        return tour_mode.empty()

    base = (
        rd.tours.filter(
            pl.col(purpose_col).is_not_null()
            & pl.col("tour_mode").is_not_null()
            & pl.col("AUTOSUFF").is_not_null()
        )
        .with_columns(pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"))
        .pipe(_tour_weights_for_summary)
    )
    if base.is_empty():
        return tour_mode.empty()

    aggregated = (
        base.group_by(["tour_mode", "tour_purpose", "AUTOSUFF"])
        .agg(tour_count=pl.col("_tour_weight").sum())
        .rename({"AUTOSUFF": "autosuff"})
    )
    pivot = aggregated.pivot(
        on="autosuff",
        index=["tour_mode", "tour_purpose"],
        values="tour_count",
        aggregate_function="sum",
    ).fill_null(0)

    rename_map = {}
    if "0" in pivot.columns:
        rename_map["0"] = "tour_count_zero_auto"
    if "1" in pivot.columns:
        rename_map["1"] = "tour_count_auto_deficient"
    if "2" in pivot.columns:
        rename_map["2"] = "tour_count_auto_sufficient"
    pivot = pivot.rename(rename_map)

    for col in [
        "tour_count_zero_auto",
        "tour_count_auto_deficient",
        "tour_count_auto_sufficient",
    ]:
        if col not in pivot.columns:
            pivot = pivot.with_columns(pl.lit(0.0).alias(col))

    cols = [
        "tour_mode",
        "tour_purpose",
        "tour_count_zero_auto",
        "tour_count_auto_deficient",
        "tour_count_auto_sufficient",
        "tour_count_all_households",
    ]
    pivot = pivot.with_columns(
        (
            pl.col("tour_count_zero_auto")
            + pl.col("tour_count_auto_deficient")
            + pl.col("tour_count_auto_sufficient")
        ).alias("tour_count_all_households")
    ).select(cols)

    total = (
        pivot.group_by("tour_mode")
        .agg(
            [
                pl.col("tour_count_zero_auto").sum(),
                pl.col("tour_count_auto_deficient").sum(),
                pl.col("tour_count_auto_sufficient").sum(),
                pl.col("tour_count_all_households").sum(),
            ]
        )
        .with_columns(pl.lit(ALL_TOUR_PURPOSES).alias("tour_purpose"))
        .select(cols)
    )

    return pl.concat([pivot, total], how="vertical")


@summary(
    id="tour_stop_frequency_by_tour_purpose",
    schema={
        "tour_purpose": pl.Utf8,
        "outbound_stop_count": pl.Int32,
        "inbound_stop_count": pl.Int32,
        "total_stop_count": pl.Int32,
        "tour_count": pl.Float64,
    },
    required_columns={
        "tours": (
            "tour_purpose",
            "tour_category",
            "num_ob_stops",
            "num_ib_stops",
            "num_tot_stops",
            "finalweight",
        )
    },
)
def stop_freq(rd: RunData, config: Config) -> pl.DataFrame:
    if "tour_purpose" not in rd.tours.columns:
        return stop_freq.empty()
    purpose_col = _summary_purpose_column(rd.tours)
    if not purpose_col:
        return stop_freq.empty()

    return (
        rd.tours.filter(pl.col("tour_category").is_not_null())
        .with_columns(
            [
                pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"),
                pl.col("num_ob_stops").clip(0, 3).alias("outbound_stop_count"),
                pl.col("num_ib_stops").clip(0, 3).alias("inbound_stop_count"),
                pl.col("num_tot_stops").clip(0, 6).alias("total_stop_count"),
            ]
        )
        .group_by(
            [
                "tour_purpose",
                "outbound_stop_count",
                "inbound_stop_count",
                "total_stop_count",
            ]
        )
        .agg(tour_count=pl.col("finalweight").sum())
        .select(
            "tour_purpose",
            "outbound_stop_count",
            "inbound_stop_count",
            "total_stop_count",
            "tour_count",
        )
        .sort(
            [
                "tour_purpose",
                "outbound_stop_count",
                "inbound_stop_count",
                "total_stop_count",
            ]
        )
    )


@summary(
    id="atwork_subtour_frequency_distribution",
    schema={
        "atwork_subtour_frequency_category": pl.Utf8,
        "atwork_subtour_count": pl.Float64,
    },
    required_columns={
        "tours": (
            "tour_purpose",
            "tour_category",
            "atwork_subtour_frequency",
            "finalweight",
        )
    },
)
def at_work_sub_tour_freq(rd: RunData, config: Config) -> pl.DataFrame:
    required = {
        "tour_purpose",
        "tour_category",
        "atwork_subtour_frequency",
        "finalweight",
    }
    if not required.issubset(set(rd.tours.columns)):
        return at_work_sub_tour_freq.empty()

    return (
        rd.tours.filter(
            (pl.col("tour_purpose").cast(pl.Utf8).str.to_lowercase() == "work")
            & (pl.col("tour_category").cast(pl.Utf8).str.to_lowercase() == "mandatory")
            & pl.col("atwork_subtour_frequency").is_not_null()
        )
        .group_by("atwork_subtour_frequency")
        .agg(atwork_subtour_count=pl.col("finalweight").sum())
        .rename({"atwork_subtour_frequency": "atwork_subtour_frequency_category"})
        .with_columns(
            pl.col("atwork_subtour_frequency_category").cast(pl.Utf8),
            pl.col("atwork_subtour_count").cast(pl.Float64),
        )
        .select("atwork_subtour_frequency_category", "atwork_subtour_count")
        .sort("atwork_subtour_frequency_category")
    )


@summary(
    id="tour_time_of_day_by_tour_purpose",
    schema={
        "time_bin": pl.Int32,
        "tour_purpose": pl.Utf8,
        "departure_tour_count": pl.Float64,
        "arrival_tour_count": pl.Float64,
        "duration_tour_count": pl.Float64,
    },
    required_columns={"tours": ("tour_category", "tour_purpose", "finalweight")},
)
def tour_tod(rd: RunData, config: Config) -> pl.DataFrame:
    if (
        "tour_category" not in rd.tours.columns
        or "tour_purpose" not in rd.tours.columns
    ):
        return tour_tod.empty()
    purpose_col = _summary_purpose_column(rd.tours)
    if not purpose_col:
        return tour_tod.empty()

    base = (
        rd.tours.filter(pl.col(purpose_col).is_not_null())
        .with_columns(pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"))
        .pipe(_tour_weights_for_summary)
    )
    purposes = base["tour_purpose"].drop_nulls().unique().sort().to_list()

    max_period = 48
    if "start_hour" in rd.tours.columns:
        try:
            max_period = int(rd.tours["start_hour"].max())
        except Exception:
            max_period = 48
    bins = list(range(1, 25 if max_period <= 24 else 49))

    def _hist(df: pl.DataFrame, col: str, filt) -> pl.DataFrame:
        if col not in df.columns:
            return pl.DataFrame({"time_bin": bins, "n": [0.0] * len(bins)})
        sub = (
            df.filter(filt)
            .select([col, "_tour_weight"])
            .with_columns(pl.col(col).cast(pl.Int32).alias("time_bin"))
            .filter(pl.col("time_bin").is_between(1, bins[-1]))
        )
        counts = sub.group_by("time_bin").agg(pl.col("_tour_weight").sum().alias("n"))
        return (
            pl.DataFrame({"time_bin": bins})
            .join(counts, on="time_bin", how="left")
            .fill_null(0)
        )

    all_rows: list[dict[str, object]] = []
    for purpose_name in purposes:
        filt = pl.col("tour_purpose") == purpose_name
        dep = _hist(base, "start_hour", filt)
        arr = _hist(base, "end_hour", filt)
        dur = _hist(base, "tourdur", filt)
        for i, time_bin in enumerate(bins):
            all_rows.append(
                {
                    "time_bin": time_bin,
                    "tour_purpose": purpose_name,
                    "departure_tour_count": float(dep["n"][i]) if i < len(dep) else 0.0,
                    "arrival_tour_count": float(arr["n"][i]) if i < len(arr) else 0.0,
                    "duration_tour_count": float(dur["n"][i]) if i < len(dur) else 0.0,
                }
            )

    if not all_rows:
        return tour_tod.empty()
    df_long = pl.DataFrame(all_rows, infer_schema_length=None)
    total = (
        df_long.group_by("time_bin")
        .agg(
            [
                pl.col("departure_tour_count").sum(),
                pl.col("arrival_tour_count").sum(),
                pl.col("duration_tour_count").sum(),
            ]
        )
        .with_columns(pl.lit(ALL_TOUR_PURPOSES).alias("tour_purpose"))
        .select(
            "time_bin",
            "tour_purpose",
            "departure_tour_count",
            "arrival_tour_count",
            "duration_tour_count",
        )
    )
    return (
        pl.concat([df_long, total], how="vertical")
        .with_columns(
            pl.col("time_bin").cast(pl.Int32),
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("departure_tour_count").cast(pl.Float64),
            pl.col("arrival_tour_count").cast(pl.Float64),
            pl.col("duration_tour_count").cast(pl.Float64),
        )
        .sort(["time_bin", "tour_purpose"])
    )


@summary(
    id="tour_distance_by_tour_purpose",
    schema={
        "distance_bin": pl.Utf8,
        "tour_purpose": pl.Utf8,
        "tour_count": pl.Float64,
    },
    required_columns={
        "tours": (
            "tour_purpose",
            "tour_category",
            "number_of_participants",
            "SKIMDIST",
            "finalweight",
        )
    },
)
def tour_distance(rd: RunData, config: Config) -> pl.DataFrame:
    required = {
        "tour_purpose",
        "tour_category",
        "number_of_participants",
        "SKIMDIST",
        "finalweight",
    }
    if not required.issubset(set(rd.tours.columns)):
        return tour_distance.empty()
    purpose_col = _summary_purpose_column(rd.tours)
    if not purpose_col:
        return tour_distance.empty()

    base = (
        rd.tours.filter(
            pl.col(purpose_col).is_not_null() & pl.col("SKIMDIST").is_not_null()
        )
        .with_columns(
            pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"),
            pl.col("SKIMDIST")
            .cast(pl.Float64)
            .round(0)
            .alias("distance_miles_rounded"),
        )
        .with_columns(
            pl.when(pl.col("tour_category").cast(pl.Utf8).str.to_lowercase() == "joint")
            .then(
                pl.col("finalweight")
                * pl.coalesce(
                    [pl.col("number_of_participants").cast(pl.Float64), pl.lit(1.0)]
                )
            )
            .otherwise(pl.col("finalweight"))
            .alias("adjusted_weight"),
            _rounded_distance_bin_expr("distance_miles_rounded"),
        )
    )

    by_purpose = weighted_group_sum(
        base,
        ["distance_bin", "tour_purpose"],
        weight_col="adjusted_weight",
        output_col="tour_count",
    )
    all_purposes = _all_purpose_rollup(
        by_purpose,
        group_cols=["distance_bin"],
        value_col="tour_count",
    )
    return (
        pl.concat([by_purpose, all_purposes], how="vertical")
        .with_columns(
            pl.col("distance_bin").cast(pl.Utf8),
            pl.col("tour_purpose").cast(pl.Utf8),
            pl.col("tour_count").cast(pl.Float64),
            pl.when(pl.col("distance_bin") == "40+")
            .then(999)
            .otherwise(pl.col("distance_bin").cast(pl.Int64, strict=False))
            .alias("_sort_distance"),
        )
        .select("distance_bin", "tour_purpose", "tour_count", "_sort_distance")
        .sort(["_sort_distance", "tour_purpose"])
        .select("distance_bin", "tour_purpose", "tour_count")
    )
