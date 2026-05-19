"""Escort distance and stop-distribution summaries."""

from __future__ import annotations

import polars as pl

from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract
from processor.summarize.summaries.daily_travel_escort_shared import (
    _adult_side_escorted_tours,
    _adult_side_explicit_escorted_tours,
    _both_explicit_escort_labels_present,
    _explicit_escort_label_present,
    _sorted_distance_bins,
)
from processor.summarize.summaries.summary_helpers import (
    _rounded_distance_bin_expr,
    _summary_purpose_column,
    _trip_direction_expr,
)
from runtime.config import Config


@summary_contract(
    schema={"distance_bin": pl.Utf8, "direction": pl.Utf8, "tour_count": pl.Float64},
    required_columns={
        "tours": ("SKIMDIST", "school_esc_outbound", "school_esc_inbound", "finalweight")
    },
)
def adult_escorted_tour_distance_distribution_by_direction(
    rd: RunData, config: Config
) -> pl.DataFrame:
    required = {"SKIMDIST", "school_esc_outbound", "school_esc_inbound", "finalweight"}
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(
            adult_escorted_tour_distance_distribution_by_direction
        )

    escorted = _adult_side_escorted_tours(rd)
    if escorted.is_empty():
        return empty_summary_frame(
            adult_escorted_tour_distance_distribution_by_direction
        )

    base = escorted.filter(pl.col("SKIMDIST").is_not_null()).with_columns(
        _rounded_distance_bin_expr("SKIMDIST")
    )
    if base.is_empty():
        return empty_summary_frame(
            adult_escorted_tour_distance_distribution_by_direction
        )

    result = pl.concat(
        [
            base.filter(_explicit_escort_label_present("school_esc_outbound"))
            .group_by("distance_bin")
            .agg(tour_count=pl.col("finalweight").sum())
            .with_columns(pl.lit("outbound").alias("direction")),
            base.filter(_explicit_escort_label_present("school_esc_inbound"))
            .group_by("distance_bin")
            .agg(tour_count=pl.col("finalweight").sum())
            .with_columns(pl.lit("inbound").alias("direction")),
            base.filter(_both_explicit_escort_labels_present())
            .group_by("distance_bin")
            .agg(tour_count=pl.col("finalweight").sum())
            .with_columns(pl.lit("both").alias("direction")),
        ],
        how="vertical",
    )
    return _sorted_distance_bins(result, direction_col="direction", value_col="tour_count")


@summary_contract(
    schema={"distance_bin": pl.Utf8, "direction": pl.Utf8, "trip_count": pl.Float64},
    required_columns={
        "tours": ("tour_id", "school_esc_outbound", "school_esc_inbound"),
        "trips": ("tour_id", "od_dist", "finalweight"),
    },
)
def adult_escorted_trip_distance_distribution_by_direction(
    rd: RunData, config: Config
) -> pl.DataFrame:
    if "tour_id" not in rd.tours.columns or "tour_id" not in rd.trips.columns:
        return empty_summary_frame(
            adult_escorted_trip_distance_distribution_by_direction
        )

    direction_expr = _trip_direction_expr(rd.trips)
    if direction_expr is None:
        return empty_summary_frame(
            adult_escorted_trip_distance_distribution_by_direction
        )

    escorted_tours = _adult_side_explicit_escorted_tours(rd)
    if escorted_tours.is_empty():
        return empty_summary_frame(
            adult_escorted_trip_distance_distribution_by_direction
        )

    escorted_trip_ids = escorted_tours.select(
        "tour_id", "school_esc_outbound", "school_esc_inbound"
    ).unique()
    trips = rd.trips.join(escorted_trip_ids, on="tour_id", how="inner")
    if (
        trips.is_empty()
        or "od_dist" not in trips.columns
        or "finalweight" not in trips.columns
    ):
        return empty_summary_frame(
            adult_escorted_trip_distance_distribution_by_direction
        )

    base = trips.filter(pl.col("od_dist").is_not_null()).with_columns(
        direction_expr,
        _rounded_distance_bin_expr("od_dist"),
    )
    if base.is_empty():
        return empty_summary_frame(
            adult_escorted_trip_distance_distribution_by_direction
        )

    result = pl.concat(
        [
            base.filter(
                (pl.col("direction") == "outbound")
                & _explicit_escort_label_present("school_esc_outbound")
            )
            .group_by("distance_bin")
            .agg(trip_count=pl.col("finalweight").sum())
            .with_columns(pl.lit("outbound").alias("direction"))
            .select("distance_bin", "direction", "trip_count"),
            base.filter(
                (pl.col("direction") == "inbound")
                & _explicit_escort_label_present("school_esc_inbound")
            )
            .group_by("distance_bin")
            .agg(trip_count=pl.col("finalweight").sum())
            .with_columns(pl.lit("inbound").alias("direction"))
            .select("distance_bin", "direction", "trip_count"),
            base.filter(_both_explicit_escort_labels_present())
            .group_by("distance_bin")
            .agg(trip_count=pl.col("finalweight").sum())
            .with_columns(pl.lit("both").alias("direction"))
            .select("distance_bin", "direction", "trip_count"),
        ],
        how="vertical",
    )
    return _sorted_distance_bins(result, direction_col="direction", value_col="trip_count")


@summary_contract(
    schema={"segment": pl.Utf8, "stop_count": pl.Int32, "tour_count": pl.Float64},
    required_columns={
        "tours": ("tour_id", "school_esc_outbound", "school_esc_inbound"),
        "trips": (
            "tour_id",
            "escort_event_role",
            "escort_stops_before_event",
            "escort_stops_after_event",
            "finalweight",
        ),
    },
)
def adult_escort_event_stop_distribution(rd: RunData, config: Config) -> pl.DataFrame:
    if "tour_id" not in rd.tours.columns or "tour_id" not in rd.trips.columns:
        return empty_summary_frame(adult_escort_event_stop_distribution)

    escorted = _adult_side_explicit_escorted_tours(rd)
    if escorted.is_empty():
        return empty_summary_frame(adult_escort_event_stop_distribution)

    required_trip_cols = {
        "tour_id",
        "escort_event_role",
        "escort_stops_before_event",
        "escort_stops_after_event",
        "finalweight",
    }
    if not required_trip_cols.issubset(set(rd.trips.columns)):
        return empty_summary_frame(adult_escort_event_stop_distribution)

    escorted_trip_ids = escorted.select(
        "tour_id", "school_esc_outbound", "school_esc_inbound"
    ).unique()
    trips = rd.trips.join(escorted_trip_ids, on="tour_id", how="inner")
    if trips.is_empty():
        return empty_summary_frame(adult_escort_event_stop_distribution)

    events = (
        trips.filter(pl.col("escort_event_role").is_not_null())
        .with_columns(
            pl.col("escort_event_role").cast(pl.Utf8).str.to_lowercase(),
            pl.col("escort_stops_before_event").cast(pl.Int32),
            pl.col("escort_stops_after_event").cast(pl.Int32),
            pl.col("finalweight").cast(pl.Float64),
        )
        .filter(pl.col("escort_event_role").is_in(["dropoff", "pickup"]))
        .filter(
            (
                (pl.col("escort_event_role") == "dropoff")
                & _explicit_escort_label_present("school_esc_outbound")
            )
            | (
                (pl.col("escort_event_role") == "pickup")
                & _explicit_escort_label_present("school_esc_inbound")
            )
        )
    )
    if events.is_empty():
        return empty_summary_frame(adult_escort_event_stop_distribution)

    empty_segment_schema = {
        "segment": pl.Utf8,
        "stop_count": pl.Int32,
        "tour_count": pl.Float64,
    }

    def _segment_counts(segment: str, stop_col: str, role: str) -> pl.DataFrame:
        filtered = events.filter(pl.col("escort_event_role") == role)
        if filtered.is_empty():
            return pl.DataFrame(schema=empty_segment_schema)
        return (
            filtered.group_by(stop_col)
            .agg(tour_count=pl.col("finalweight").sum())
            .rename({stop_col: "stop_count"})
            .with_columns(pl.lit(segment).alias("segment"))
            .select("segment", "stop_count", "tour_count")
        )

    result = pl.concat(
        [
            _segment_counts(
                "outbound_before_dropoff", "escort_stops_before_event", "dropoff"
            ),
            _segment_counts(
                "outbound_after_dropoff", "escort_stops_after_event", "dropoff"
            ),
            _segment_counts(
                "inbound_before_pickup", "escort_stops_before_event", "pickup"
            ),
            _segment_counts(
                "inbound_after_pickup", "escort_stops_after_event", "pickup"
            ),
        ],
        how="vertical",
    )
    if result.is_empty():
        return empty_summary_frame(adult_escort_event_stop_distribution)

    return (
        result.with_columns(
            pl.col("segment").cast(pl.Utf8),
            pl.col("stop_count").cast(pl.Int32),
            pl.col("tour_count").cast(pl.Float64),
        )
        .sort(["segment", "stop_count"])
        .select("segment", "stop_count", "tour_count")
    )


@summary_contract(
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
            "school_esc_outbound",
            "school_esc_inbound",
            "num_ob_stops",
            "num_ib_stops",
            "num_tot_stops",
            "finalweight",
        )
    },
)
def adult_escort_trip_stop_frequency(rd: RunData, config: Config) -> pl.DataFrame:
    required = {
        "school_esc_outbound",
        "school_esc_inbound",
        "num_ob_stops",
        "num_ib_stops",
        "num_tot_stops",
        "finalweight",
    }
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(adult_escort_trip_stop_frequency)

    escorted = _adult_side_escorted_tours(rd)
    if escorted.is_empty():
        return empty_summary_frame(adult_escort_trip_stop_frequency)

    purpose_col = _summary_purpose_column(escorted)
    if not purpose_col:
        return empty_summary_frame(adult_escort_trip_stop_frequency)

    return (
        escorted.filter(pl.col(purpose_col).is_not_null())
        .with_columns(
            [
                pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"),
                pl.col("num_ob_stops").clip(0, 3).cast(pl.Int32).alias("outbound_stop_count"),
                pl.col("num_ib_stops").clip(0, 3).cast(pl.Int32).alias("inbound_stop_count"),
                pl.col("num_tot_stops").clip(0, 6).cast(pl.Int32).alias("total_stop_count"),
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
        .with_columns(pl.col("tour_count").cast(pl.Float64))
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
