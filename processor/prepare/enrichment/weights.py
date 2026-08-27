"""Weight assignment helpers for prepared tables."""

from __future__ import annotations

from typing import Optional

from runtime.logging import get_logger
import polars as pl

from processor.prepare.enrichment.columns import _has_columns
from processor.prepare.enrichment.types import _PrepareState
from runtime.config import Config

LOGGER = get_logger("processor.prepare")


def _compute_household_weights(
    hh: pl.DataFrame,
    config: Config,
    *,
    hh_weight_col: str | None,
    explicit_weight_supplied: bool,
) -> pl.DataFrame:
    sample_rate_col = config.col_sample_rate or (
        "sample_rate" if "sample_rate" in hh.columns else None
    )
    if sample_rate_col == "sample_rate" and config.col_sample_rate is None:
        LOGGER.info("[compute_weights] Auto-detected sample_rate column in households.")

    if hh_weight_col and hh_weight_col in hh.columns:
        LOGGER.info(
            "[compute_weights] Using household weight column: %s", hh_weight_col
        )
        return hh.with_columns(
            pl.col(hh_weight_col).cast(pl.Float64).alias("finalweight")
        )

    if (
        (not explicit_weight_supplied)
        and sample_rate_col
        and sample_rate_col in hh.columns
    ):
        LOGGER.info(
            "[compute_weights] Using sample-rate expansion from column: %s",
            sample_rate_col,
        )
        return hh.with_columns(
            (pl.lit(1.0) / pl.col(sample_rate_col).cast(pl.Float64)).alias(
                "finalweight"
            )
        )

    if explicit_weight_supplied and sample_rate_col and sample_rate_col in hh.columns:
        LOGGER.info(
            "[compute_weights] Explicit run weight columns supplied; skipping sample_rate expansion."
        )
    else:
        LOGGER.info(
            "[compute_weights] No weight column found; defaulting finalweight=1."
        )
    return hh.with_columns(pl.lit(1.0).alias("finalweight"))


def _compute_person_weights(
    per: pl.DataFrame,
    hh: pl.DataFrame,
    *,
    person_weight_col: str | None,
) -> pl.DataFrame:
    if person_weight_col and person_weight_col in per.columns:
        LOGGER.info(
            "[compute_weights] Using person weight column: %s", person_weight_col
        )
        return per.with_columns(
            pl.col(person_weight_col).cast(pl.Float64).alias("finalweight")
        )

    if _has_columns(per, "household_id") and _has_columns(
        hh, "household_id", "finalweight"
    ):
        return (
            per.join(
                hh.select(["household_id", pl.col("finalweight").alias("_hw")]),
                on="household_id",
                how="left",
            )
            .with_columns(pl.col("_hw").fill_null(1.0).alias("finalweight"))
            .drop("_hw")
        )

    return per.with_columns(pl.lit(1.0).alias("finalweight"))


def _compute_trip_weights(
    trips: pl.DataFrame,
    per: pl.DataFrame,
    hh: pl.DataFrame,
    *,
    trip_weight_col: str | None,
) -> pl.DataFrame:
    if trip_weight_col and trip_weight_col in trips.columns:
        LOGGER.info("[compute_weights] Using trip weight column: %s", trip_weight_col)
        return trips.with_columns(
            pl.col(trip_weight_col).cast(pl.Float64).alias("finalweight")
        )

    if _has_columns(trips, "person_id") and _has_columns(
        per, "person_id", "finalweight"
    ):
        return (
            trips.join(
                per.select(["person_id", pl.col("finalweight").alias("_pw")]),
                on="person_id",
                how="left",
            )
            .with_columns(pl.col("_pw").fill_null(1.0).alias("finalweight"))
            .drop("_pw")
        )

    if _has_columns(trips, "household_id") and _has_columns(
        hh, "household_id", "finalweight"
    ):
        return (
            trips.join(
                hh.select(["household_id", pl.col("finalweight").alias("_hw")]),
                on="household_id",
                how="left",
            )
            .with_columns(pl.col("_hw").fill_null(1.0).alias("finalweight"))
            .drop("_hw")
        )

    return trips.with_columns(pl.lit(1.0).alias("finalweight"))


def _compute_day_weights(
    day: pl.DataFrame,
    per: pl.DataFrame,
    hh: pl.DataFrame,
    *,
    day_weight_col: str | None,
) -> pl.DataFrame:
    result = day
    if _has_columns(day, "person_id") and _has_columns(per, "person_id", "finalweight"):
        result = result.join(
            per.select(["person_id", pl.col("finalweight").alias("_pw")]),
            on="person_id",
            how="left",
        )

    if _has_columns(day, "household_id") and _has_columns(hh, "household_id", "finalweight"):
        result = result.join(
            hh.select(["household_id", pl.col("finalweight").alias("_hw")]),
            on="household_id",
            how="left",
        )

    if day_weight_col and day_weight_col in day.columns:
        result = result.with_columns(
            pl.coalesce(
                [
                    pl.col(day_weight_col).cast(pl.Float64),
                    pl.col("_pw") if "_pw" in result.columns else pl.lit(None),
                    pl.col("_hw") if "_hw" in result.columns else pl.lit(None),
                    pl.lit(1.0),
                ]
            ).alias("finalweight")
        )
    elif "_pw" in result.columns or "_hw" in result.columns:
        result = result.with_columns(
            pl.coalesce(
                [
                    pl.col("_pw") if "_pw" in result.columns else pl.lit(None),
                    pl.col("_hw") if "_hw" in result.columns else pl.lit(None),
                    pl.lit(1.0),
                ]
            ).alias("finalweight")
        )
    else:
        result = result.with_columns(pl.lit(1.0).alias("finalweight"))

    drop_columns = [column for column in ("_pw", "_hw") if column in result.columns]
    if drop_columns:
        result = result.drop(drop_columns)
    return result


def _compute_tour_weights(
    tours: pl.DataFrame,
    trips: pl.DataFrame,
    per: pl.DataFrame,
    hh: pl.DataFrame,
    *,
    trip_weight_col: str | None,
) -> pl.DataFrame:
    if (
        trip_weight_col
        and trip_weight_col in trips.columns
        and "tour_id" in trips.columns
    ):
        tour_avg = trips.group_by("tour_id").agg(
            pl.col("finalweight").mean().alias("_tw")
        )
        return (
            tours.join(tour_avg, on="tour_id", how="left")
            .with_columns(pl.col("_tw").fill_null(1.0).alias("finalweight"))
            .drop("_tw")
        )

    if _has_columns(tours, "person_id") and _has_columns(
        per, "person_id", "finalweight"
    ):
        return (
            tours.join(
                per.select(["person_id", pl.col("finalweight").alias("_pw")]),
                on="person_id",
                how="left",
            )
            .with_columns(pl.col("_pw").fill_null(1.0).alias("finalweight"))
            .drop("_pw")
        )

    if _has_columns(tours, "household_id") and _has_columns(
        hh, "household_id", "finalweight"
    ):
        return (
            tours.join(
                hh.select(["household_id", pl.col("finalweight").alias("_hw")]),
                on="household_id",
                how="left",
            )
            .with_columns(pl.col("_hw").fill_null(1.0).alias("finalweight"))
            .drop("_hw")
        )

    return tours.with_columns(pl.lit(1.0).alias("finalweight"))


def _compute_vehicle_weights(
    vehicles: pl.DataFrame,
    hh: pl.DataFrame,
) -> pl.DataFrame:
    if _has_columns(vehicles, "household_id") and _has_columns(
        hh, "household_id", "finalweight"
    ):
        return (
            vehicles.join(
                hh.select(["household_id", pl.col("finalweight").alias("_hw")]),
                on="household_id",
                how="left",
            )
            .with_columns(pl.col("_hw").fill_null(1.0).alias("finalweight"))
            .drop("_hw")
        )

    return vehicles.with_columns(pl.lit(1.0).alias("finalweight"))


def compute_weights(
    hh: pl.DataFrame,
    per: pl.DataFrame,
    day: pl.DataFrame,
    tours: pl.DataFrame,
    trips: pl.DataFrame,
    vehicles: pl.DataFrame,
    config: Config,
    hh_weight_col: Optional[str] = None,
    person_weight_col: Optional[str] = None,
    trip_weight_col: Optional[str] = None,
    day_weight_col: Optional[str] = "day_weight",
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Compute and attach ``finalweight`` to prepared tables."""
    explicit_weight_supplied = any([hh_weight_col, person_weight_col, trip_weight_col])
    hh = _compute_household_weights(
        hh,
        config,
        hh_weight_col=hh_weight_col,
        explicit_weight_supplied=explicit_weight_supplied,
    )
    per = _compute_person_weights(
        per,
        hh,
        person_weight_col=person_weight_col,
    )
    trips = _compute_trip_weights(
        trips,
        per,
        hh,
        trip_weight_col=trip_weight_col,
    )
    day = _compute_day_weights(
        day,
        per,
        hh,
        day_weight_col=day_weight_col,
    )
    tours = _compute_tour_weights(
        tours,
        trips,
        per,
        hh,
        trip_weight_col=trip_weight_col,
    )
    vehicles = _compute_vehicle_weights(vehicles, hh)
    return hh, per, day, tours, trips, vehicles


def _apply_weights(state: _PrepareState, config: Config) -> _PrepareState:
    state.hh, state.per, state.day, state.tours, state.trips, state.vehicles = compute_weights(
        state.hh,
        state.per,
        state.day,
        state.tours,
        state.trips,
        state.vehicles,
        config,
        hh_weight_col=state.hh_weight_col,
        person_weight_col=state.person_weight_col,
        trip_weight_col=state.trip_weight_col,
        day_weight_col=state.day_weight_col,
    )
    LOGGER.info("[prepare_data] Weights ready for '%s'", state.label)
    return state


__all__ = ["compute_weights"]
