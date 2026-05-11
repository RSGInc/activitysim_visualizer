"""Tour summaries."""

import polars as pl
from runtime.config import Config
from processor.models import RunData
from processor.summarize.contracts import empty_summary_frame, summary_contract
from processor.summarize.summaries.tour_purpose_helpers import (
    purpose_column,
)


@summary_contract(
    schema={"tour_category": pl.Utf8, "tour_count": pl.Float64},
    required_columns={"tours": ("tour_category", "finalweight")},
)
def tour_category(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"tour_category", "finalweight"}
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(tour_category)

    return (
        rd.tours.filter(pl.col("tour_category").is_not_null())
        .group_by("tour_category")
        .agg(tour_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("tour_category").cast(pl.Utf8),
            pl.col("tour_count").cast(pl.Float64),
        )
        .select("tour_category", "tour_count")
        .sort("tour_category")
    )


@summary_contract(
    schema={"tour_purpose": pl.Utf8, "tour_count": pl.Float64},
    required_columns={"tours": ("tour_purpose", "finalweight")},
)
def tour_purpose(rd: RunData, config: Config) -> pl.DataFrame:
    required = {"tour_purpose", "finalweight"}
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(tour_purpose)
    purpose_col = purpose_column(rd.tours)
    if not purpose_col:
        return empty_summary_frame(tour_purpose)

    return (
        rd.tours.filter(pl.col(purpose_col).is_not_null())
        .group_by(purpose_col)
        .agg(tour_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"),
            pl.col("tour_count").cast(pl.Float64),
        )
        .select("tour_purpose", "tour_count")
        .sort("tour_purpose")
    )


def _prepared_allocated_vehicles_from_tours(rd: RunData) -> pl.DataFrame:
    """
    Reshapes allocated vehicle columns on tours into a long table with:
      - occupancy
      - allocated_vehicle_type
      - body_type
      - fuel_type
      - age
      - finalweight

    Assumes allocated vehicle strings use the same pattern as vehicle_type:
      {body}_{age}_{fuel}
    e.g. Car_11_Gas
    """
    required = {
        "vehicle_occup_1",
        "vehicle_occup_2",
        "vehicle_occup_3.5",
        "finalweight",
    }
    if not required.issubset(set(rd.tours.columns)):
        return pl.DataFrame()

    long_df = pl.concat(
        [
            rd.tours.select(
                pl.lit("1").alias("occupancy"),
                pl.col("vehicle_occup_1").alias("allocated_vehicle_type"),
                pl.col("finalweight"),
            ),
            rd.tours.select(
                pl.lit("2").alias("occupancy"),
                pl.col("vehicle_occup_2").alias("allocated_vehicle_type"),
                pl.col("finalweight"),
            ),
            rd.tours.select(
                pl.lit("3+").alias("occupancy"),
                pl.col("vehicle_occup_3.5").alias("allocated_vehicle_type"),
                pl.col("finalweight"),
            ),
        ],
        how="vertical",
    )

    return (
        long_df.filter(pl.col("allocated_vehicle_type").is_not_null())
        .with_columns(
            parts=pl.col("allocated_vehicle_type").cast(pl.Utf8).str.split("_"),
        )
        .with_columns(
            body_type=pl.col("parts").list.get(0).cast(pl.Utf8),
            age_raw=pl.col("parts").list.get(1).cast(pl.Int64, strict=False),
            fuel_type=pl.col("parts").list.get(2).cast(pl.Utf8),
        )
        .filter(
            pl.col("body_type").is_not_null()
            & pl.col("fuel_type").is_not_null()
            & pl.col("age_raw").is_not_null()
        )
        .with_columns(
            pl.when(pl.col("age_raw") >= 20)
            .then(pl.lit("20+"))
            .otherwise(pl.col("age_raw").cast(pl.Utf8))
            .alias("age")
        )
        .drop(["parts", "age_raw"])
    )


@summary_contract(
    schema={"age": pl.Utf8, "occupancy": pl.Utf8, "vehicle_count": pl.Float64},
    required_columns={
        "tours": (
            "vehicle_occup_1",
            "vehicle_occup_2",
            "vehicle_occup_3.5",
            "finalweight",
        )
    },
)
def allocated_vehicle_age(rd: RunData, config: Config) -> pl.DataFrame:
    vehicles = _prepared_allocated_vehicles_from_tours(rd)
    if vehicles.is_empty():
        return empty_summary_frame(allocated_vehicle_age)

    return (
        vehicles.group_by(["age", "occupancy"])
        .agg(vehicle_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("age").cast(pl.Utf8),
            pl.col("occupancy").cast(pl.Utf8),
            pl.col("vehicle_count").cast(pl.Float64),
            pl.when(pl.col("age") == "20+")
            .then(999)
            .otherwise(pl.col("age").cast(pl.Int64, strict=False))
            .alias("_sort_age"),
        )
        .sort(["_sort_age", "occupancy"])
        .select("age", "occupancy", "vehicle_count")
    )


@summary_contract(
    schema={"fuel_type": pl.Utf8, "occupancy": pl.Utf8, "vehicle_count": pl.Float64},
    required_columns={
        "tours": (
            "vehicle_occup_1",
            "vehicle_occup_2",
            "vehicle_occup_3.5",
            "finalweight",
        )
    },
)
def allocated_vehicle_fuel(rd: RunData, config: Config) -> pl.DataFrame:
    vehicles = _prepared_allocated_vehicles_from_tours(rd)
    if vehicles.is_empty():
        return empty_summary_frame(allocated_vehicle_fuel)

    return (
        vehicles.group_by(["fuel_type", "occupancy"])
        .agg(vehicle_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("fuel_type").cast(pl.Utf8),
            pl.col("occupancy").cast(pl.Utf8),
            pl.col("vehicle_count").cast(pl.Float64),
        )
        .select("fuel_type", "occupancy", "vehicle_count")
        .sort(["fuel_type", "occupancy"])
    )


@summary_contract(
    schema={"body_type": pl.Utf8, "occupancy": pl.Utf8, "vehicle_count": pl.Float64},
    required_columns={
        "tours": (
            "vehicle_occup_1",
            "vehicle_occup_2",
            "vehicle_occup_3.5",
            "finalweight",
        )
    },
)
def allocated_vehicle_body(rd: RunData, config: Config) -> pl.DataFrame:
    vehicles = _prepared_allocated_vehicles_from_tours(rd)
    if vehicles.is_empty():
        return empty_summary_frame(allocated_vehicle_body)

    return (
        vehicles.group_by(["body_type", "occupancy"])
        .agg(vehicle_count=pl.col("finalweight").sum())
        .with_columns(
            pl.col("body_type").cast(pl.Utf8),
            pl.col("occupancy").cast(pl.Utf8),
            pl.col("vehicle_count").cast(pl.Float64),
        )
        .select("body_type", "occupancy", "vehicle_count")
        .sort(["body_type", "occupancy"])
    )


@summary_contract(
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
    """Tour mode by auto sufficiency level and total, by tour purpose/category.

    Returns DataFrame:
    tour_mode, tour_purpose,
    tour_count_zero_auto, tour_count_auto_deficient,
    tour_count_auto_sufficient, tour_count_all_households.
    """
    required = {"tour_mode", "tour_purpose", "finalweight", "AUTOSUFF"}
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(tour_mode)
    purpose_col = purpose_column(rd.tours)
    if not purpose_col:
        return empty_summary_frame(tour_mode)

    if "tour_category" not in rd.tours.columns:
        return empty_summary_frame(tour_mode)

    base = (
        rd.tours.filter(
            pl.col(purpose_col).is_not_null()
            & pl.col("tour_mode").is_not_null()
            & pl.col("AUTOSUFF").is_not_null()
        )
        .with_columns(
            pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"),
            pl.when(pl.col("tour_category").cast(pl.Utf8).str.to_lowercase() == "joint")
            .then(pl.col("finalweight") * pl.col("NUMBER_HH").cast(pl.Float64))
            .otherwise(pl.col("finalweight"))
            .alias("_tour_weight"),
        )
    )

    if base.is_empty():
        return empty_summary_frame(tour_mode)

    all_modes = rd.tours["tour_mode"].drop_nulls().unique().to_list()
    all_modes = config.ordered_modes(all_modes)

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

    pivot = pivot.with_columns(
        (
            pl.col("tour_count_zero_auto")
            + pl.col("tour_count_auto_deficient")
            + pl.col("tour_count_auto_sufficient")
        ).alias("tour_count_all_households")
    )

    cols = [
        "tour_mode",
        "tour_purpose",
        "tour_count_zero_auto",
        "tour_count_auto_deficient",
        "tour_count_auto_sufficient",
        "tour_count_all_households",
    ]

    pivot = pivot.select(cols)

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
        .with_columns(pl.lit("all_tour_purposes").alias("tour_purpose"))
        .select(cols)
    )

    return pl.concat([pivot, total], how="vertical")


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
            "tour_category",
            "num_ob_stops",
            "num_ib_stops",
            "num_tot_stops",
            "finalweight",
        )
    },
)
def stop_freq(rd: RunData, config: Config) -> pl.DataFrame:
    """Stop frequency by tour purpose (outbound, inbound, total).
    Returns DataFrame:
    tour_purpose, outbound_stop_count (0-3+), inbound_stop_count (0-3+), total_stop_count (0-6+), tour_count.
    """
    if "tour_purpose" not in rd.tours.columns:
        return empty_summary_frame(stop_freq)
    purpose_col = purpose_column(rd.tours)
    if not purpose_col:
        return empty_summary_frame(stop_freq)

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


@summary_contract(
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
    required = {"tour_purpose", "tour_category", "atwork_subtour_frequency", "finalweight"}
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(at_work_sub_tour_freq)

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


# TODO: fix in specs to match original.
def atwork_subtour_frequency_distribution(rd: RunData, config: Config) -> pl.DataFrame:
    """Backward-compatible alias used by summary spec registration."""
    return at_work_sub_tour_freq(rd, config)


@summary_contract(
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
    """Departure, arrival, and duration profiles in 48 half-hour bins.

    Returns DataFrame: time_bin (1-48), tour_purpose, departure_tour_count,
    arrival_tour_count, duration_tour_count.
    """
    if "tour_category" not in rd.tours.columns:
        return empty_summary_frame(tour_tod)
    purpose_col = purpose_column(rd.tours)
    if not purpose_col:
        return empty_summary_frame(tour_tod)
    if "tour_purpose" not in rd.tours.columns:
        return empty_summary_frame(tour_tod)

    base = (
        rd.tours.filter(pl.col(purpose_col).is_not_null())
        .with_columns(
            pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"),
            pl.when(pl.col("tour_category").cast(pl.Utf8).str.to_lowercase() == "joint")
            .then(pl.col("finalweight") * pl.col("NUMBER_HH").cast(pl.Float64))
            .otherwise(pl.col("finalweight"))
            .alias("_tour_weight"),
        )
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
        base = pl.DataFrame({"time_bin": bins})
        return base.join(counts, on="time_bin", how="left").fill_null(0)

    all_rows = []
    for purpose_name in purposes:
        filt = pl.col("tour_purpose") == purpose_name
        dep = _hist(base, "start_hour", filt)
        arr = _hist(base, "end_hour", filt)
        dur = _hist(base, "tourdur", filt)

        for i, tb in enumerate(bins):
            all_rows.append(
                {
                    "time_bin": tb,
                    "tour_purpose": purpose_name,
                    "departure_tour_count": float(dep["n"][i]) if i < len(dep) else 0.0,
                    "arrival_tour_count": float(arr["n"][i]) if i < len(arr) else 0.0,
                    "duration_tour_count": float(dur["n"][i]) if i < len(dur) else 0.0,
                }
            )

    if not all_rows:
        return empty_summary_frame(tour_tod)

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
        .with_columns(pl.lit("all_tour_purposes").alias("tour_purpose"))
        .select(
            "time_bin",
            "tour_purpose",
            "departure_tour_count",
            "arrival_tour_count",
            "duration_tour_count",
        )
    )

    return pl.concat([df_long, total], how="vertical").sort(
        ["time_bin", "tour_purpose"]
    )


@summary_contract(
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
        return empty_summary_frame(tour_distance)
    purpose_col = purpose_column(rd.tours)
    if not purpose_col:
        return empty_summary_frame(tour_distance)

    base = (
        rd.tours.filter(pl.col(purpose_col).is_not_null() & pl.col("SKIMDIST").is_not_null())
        .with_columns(
            pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"),
            pl.when(pl.col("tour_category").cast(pl.Utf8).str.to_lowercase() == "joint")
            .then(
                pl.col("finalweight")
                * pl.coalesce(
                    [pl.col("number_of_participants").cast(pl.Float64), pl.lit(1.0)]
                )
            )
            .otherwise(pl.col("finalweight"))
            .alias("adjusted_weight"),
            pl.col("SKIMDIST")
            .cast(pl.Float64)
            .round(0)
            .alias("distance_miles_rounded"),
        )
        .with_columns(
            pl.when(pl.col("distance_miles_rounded") >= 40)
            .then(pl.lit("40+"))
            .otherwise(
                pl.col("distance_miles_rounded")
                .cast(pl.Int64, strict=False)
                .cast(pl.Utf8)
            )
            .alias("distance_bin")
        )
    )

    by_purpose = base.group_by(["distance_bin", "tour_purpose"]).agg(
        tour_count=pl.col("adjusted_weight").sum()
    )

    all_purposes = (
        base.with_columns(pl.lit("all_tour_purposes").alias("tour_purpose"))
        .group_by(["distance_bin", "tour_purpose"])
        .agg(tour_count=pl.col("adjusted_weight").sum())
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


# TODO: Check if should use SKIMDIST instead of distance_to_school / distance_to_work
@summary_contract(
    schema={
        "mandatory_tour_purpose": pl.Utf8,
        "geography": pl.Utf8,
        "average_tour_distance": pl.Float64,
    },
    required_columns={"per": ("finalweight",)},
)
def avg_mand_tour_distance(rd: RunData, config: Config) -> pl.DataFrame:
    """Average mandatory tour distances.

    Returns DataFrame: mandatory_tour_purpose, geography, average_tour_distance.
    """
    ptype_col = "person_type" if "person_type" in rd.per.columns else None

    workers = (
        rd.per.filter(
            (pl.col("workplace_zone_id") > 0)
            & (
                pl.col("is_worker")
                .cast(pl.Utf8)
                .str.to_lowercase()
                .is_in(["true", "1"])
            )
        )
        if "is_worker" in rd.per.columns
        else rd.per.head(0)
    )

    if ptype_col is not None:
        univ_s = (
            rd.per.filter(
                (pl.col("school_zone_id") > 0)
                & (
                    pl.col("is_student")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .is_in(["true", "1"])
                )
                & (pl.col(ptype_col).cast(pl.Utf8) == "3")
            )
            if "is_student" in rd.per.columns
            else rd.per.head(0)
        )

        schl_s = (
            rd.per.filter(
                (pl.col("school_zone_id") > 0)
                & (
                    pl.col("is_student")
                    .cast(pl.Utf8)
                    .str.to_lowercase()
                    .is_in(["true", "1"])
                )
                & (pl.col(ptype_col).cast(pl.Utf8).cast(pl.Int32, strict=False) >= 6)
            )
            if "is_student" in rd.per.columns
            else rd.per.head(0)
        )
    else:
        univ_s = rd.per.head(0)
        schl_s = rd.per.head(0)

    def _avg_by_geo(
        persons: pl.DataFrame,
        purpose_name: str,
        dist_col: str,
        geo_col: str = "HGEO",
    ) -> pl.DataFrame:
        if dist_col not in persons.columns or len(persons) == 0:
            return pl.DataFrame(
                {
                    "mandatory_tour_purpose": [purpose_name],
                    "geography": ["all_geographies"],
                    "average_tour_distance": [None],
                }
            )

        rows = []

        if config.geography_enabled and geo_col in persons.columns:
            groups = sorted(persons[geo_col].drop_nulls().unique().to_list())
            for grp in groups:
                sub = persons.filter(pl.col(geo_col) == grp)
                rows.append(
                    {
                        "mandatory_tour_purpose": purpose_name,
                        "geography": str(grp),
                        "average_tour_distance": sub[dist_col].mean(),
                    }
                )

        rows.append(
            {
                "mandatory_tour_purpose": purpose_name,
                "geography": "all_geographies",
                "average_tour_distance": persons[dist_col].mean(),
            }
        )

        return pl.DataFrame(
            rows,
            schema={
                "mandatory_tour_purpose": pl.Utf8,
                "geography": pl.Utf8,
                "average_tour_distance": pl.Float64,
            },
        )

    result = pl.concat(
        [
            _avg_by_geo(workers, "work", "distance_to_work"),
            _avg_by_geo(univ_s, "university", "distance_to_school"),
            _avg_by_geo(schl_s, "school", "distance_to_school"),
        ],
        how="vertical",
    )

    return result.select(
        "mandatory_tour_purpose",
        "geography",
        "average_tour_distance",
    ).sort(["mandatory_tour_purpose", "geography"])


@summary_contract(
    schema={
        "nonmandatory_tour_purpose": pl.Utf8,
        "geography": pl.Utf8,
        "average_tour_distance": pl.Float64,
    },
    required_columns={
        "tours": ("tour_category", "tour_purpose", "SKIMDIST", "finalweight")
    },
)
def avg_non_mand_tour_distance(rd: RunData, config: Config) -> pl.DataFrame:
    """Average non-mandatory tour distance by purpose and geography.

    Returns DataFrame:
        nonmandatory_tour_purpose, geography, average_tour_distance
    """
    required = {"tour_category", "tour_purpose", "SKIMDIST", "finalweight"}
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(avg_non_mand_tour_distance)

    tours = rd.tours.filter(
        (pl.col("tour_category").cast(pl.Utf8).str.to_lowercase() == "non_mandatory")
        & pl.col("tour_purpose").is_not_null()
        & pl.col("SKIMDIST").is_not_null()
        & pl.col("finalweight").is_not_null()
    )
    purpose_col = purpose_column(rd.tours)
    if not purpose_col:
        return empty_summary_frame(avg_non_mand_tour_distance)
    tours = tours.with_columns(pl.col(purpose_col).cast(pl.Utf8).alias("tour_purpose"))

    if tours.is_empty():
        return empty_summary_frame(avg_non_mand_tour_distance)

    def _weighted_avg_by_geo(
        df: pl.DataFrame,
        purpose_name: str,
        geo_col: str = "HGEO",
    ) -> pl.DataFrame:
        rows = []

        if config.geography_enabled and geo_col in df.columns:
            groups = sorted(df[geo_col].drop_nulls().unique().to_list())
            for grp in groups:
                sub = df.filter(pl.col(geo_col) == grp)
                weight_sum = sub["finalweight"].sum()

                avg_dist = (
                    None
                    if weight_sum in (None, 0)
                    else (sub["SKIMDIST"] * sub["finalweight"]).sum() / weight_sum
                )

                rows.append(
                    {
                        "nonmandatory_tour_purpose": purpose_name,
                        "geography": str(grp),
                        "average_tour_distance": avg_dist,
                    }
                )

        total_weight = df["finalweight"].sum()
        total_avg = (
            None
            if total_weight in (None, 0)
            else (df["SKIMDIST"] * df["finalweight"]).sum() / total_weight
        )

        rows.append(
            {
                "nonmandatory_tour_purpose": purpose_name,
                "geography": "all_geographies",
                "average_tour_distance": total_avg,
            }
        )

        return pl.DataFrame(
            rows,
            schema={
                "nonmandatory_tour_purpose": pl.Utf8,
                "geography": pl.Utf8,
                "average_tour_distance": pl.Float64,
            },
        )

    purposes = (
        tours.select("tour_purpose")
        .unique()
        .drop_nulls()
        .sort("tour_purpose")
        .get_column("tour_purpose")
        .to_list()
    )

    result = pl.concat(
        [
            _weighted_avg_by_geo(
                tours.filter(pl.col("tour_purpose") == purpose),
                str(purpose),
            )
            for purpose in purposes
        ],
        how="vertical",
    )

    return (
        result.with_columns(
            pl.col("nonmandatory_tour_purpose").cast(pl.Utf8),
            pl.col("geography").cast(pl.Utf8),
            pl.col("average_tour_distance").cast(pl.Float64),
        )
        .select(
            "nonmandatory_tour_purpose",
            "geography",
            "average_tour_distance",
        )
        .sort(["nonmandatory_tour_purpose", "geography"])
    )


@summary_contract(
    schema={
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "internal_nonmandatory_tour_count": pl.Float64,
        "external_nonmandatory_tour_count": pl.Float64,
    },
    required_columns={
        "per": ("person_id", "home_zone_id"),
        "tours": ("person_id", "tour_category", "is_external_tour", "finalweight"),
    },
)
def int_vs_ext_non_mand_tour_freq(rd: RunData, config: Config) -> pl.DataFrame:
    person_required = {"person_id", "home_zone_id"}
    tour_required = {"person_id", "tour_category", "is_external_tour", "finalweight"}

    if not person_required.issubset(set(rd.per.columns)) or not tour_required.issubset(
        set(rd.tours.columns)
    ):
        return empty_summary_frame(int_vs_ext_non_mand_tour_freq)

    def aggregate_counts(
        df: pl.DataFrame,
        geography_type: str,
        geography_id_col: str,
    ) -> pl.DataFrame:
        return (
            df.group_by(geography_id_col)
            .agg(
                internal_nonmandatory_tour_count=pl.when(~pl.col("is_external_tour"))
                .then(pl.col("finalweight"))
                .otherwise(0.0)
                .sum(),
                external_nonmandatory_tour_count=pl.when(pl.col("is_external_tour"))
                .then(pl.col("finalweight"))
                .otherwise(0.0)
                .sum(),
            )
            .rename({geography_id_col: "geography_id"})
            .with_columns(
                pl.lit(geography_type).alias("geography_type"),
                pl.col("geography_id").cast(pl.Utf8),
                pl.col("internal_nonmandatory_tour_count").cast(pl.Float64),
                pl.col("external_nonmandatory_tour_count").cast(pl.Float64),
            )
            .select(
                "geography_type",
                "geography_id",
                "internal_nonmandatory_tour_count",
                "external_nonmandatory_tour_count",
            )
        )

    base = (
        rd.tours.filter(
            (
                pl.col("tour_category").cast(pl.Utf8).str.to_lowercase()
                == "non_mandatory"
            )
            & pl.col("person_id").is_not_null()
            & pl.col("is_external_tour").is_not_null()
        )
        .join(
            rd.per.select("person_id", "home_zone_id"),
            on="person_id",
            how="inner",
        )
        .filter(pl.col("home_zone_id").is_not_null())
        .select("home_zone_id", "is_external_tour", "finalweight")
    )

    if base.is_empty():
        return empty_summary_frame(int_vs_ext_non_mand_tour_freq)

    outputs = [
        aggregate_counts(
            base,
            geography_type="maz",
            geography_id_col="home_zone_id",
        )
    ]

    # TODO: Adapt for home-geography helper pattern.
    # The primer says geography-aware summaries may also aggregate to configured
    # geographies when a MAZ-to-geography lookup is available. :contentReference[oaicite:2]{index=2}
    #
    # Example expected pattern:
    # if config.geography_enabled:
    #     for geography_type, lookup_df in config.home_maz_geography_lookups():
    #         # lookup_df maps home_zone_id / MAZ -> geography_id
    #         geo_df = (
    #             base.join(
    #                 lookup_df,
    #                 left_on="home_zone_id",
    #                 right_on="MAZ",
    #                 how="inner",
    #             )
    #             .pipe(aggregate_counts, geography_type, "geography_id")
    #         )
    #         outputs.append(geo_df)

    return (
        pl.concat(outputs, how="vertical")
        .with_columns(
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("internal_nonmandatory_tour_count").cast(pl.Float64),
            pl.col("external_nonmandatory_tour_count").cast(pl.Float64),
        )
        .select(
            "geography_type",
            "geography_id",
            "internal_nonmandatory_tour_count",
            "external_nonmandatory_tour_count",
        )
        .sort(["geography_type", "geography_id"])
    )


@summary_contract(
    schema={
        "geography_type": pl.Utf8,
        "geography_id": pl.Utf8,
        "external_nonmandatory_tour_count": pl.Float64,
    },
    required_columns={
        "tours": ("tour_category", "is_external_tour", "destination", "finalweight")
    },
)
def ext_non_mand_tour_loc(rd: RunData, config: Config) -> pl.DataFrame:
    required = {
        "tour_category",
        "is_external_tour",
        "destination",
        "finalweight",
    }
    if not required.issubset(set(rd.tours.columns)):
        return empty_summary_frame(ext_non_mand_tour_loc)

    def aggregate_counts(
        df: pl.DataFrame,
        geography_type: str,
        geography_id_col: str,
    ) -> pl.DataFrame:
        return (
            df.group_by(geography_id_col)
            .agg(external_nonmandatory_tour_count=pl.col("finalweight").sum())
            .rename({geography_id_col: "geography_id"})
            .with_columns(
                pl.lit(geography_type).alias("geography_type"),
                pl.col("geography_id").cast(pl.Utf8),
                pl.col("external_nonmandatory_tour_count").cast(pl.Float64),
            )
            .select(
                "geography_type",
                "geography_id",
                "external_nonmandatory_tour_count",
            )
        )

    base = rd.tours.filter(
        (pl.col("tour_category").cast(pl.Utf8).str.to_lowercase() == "non_mandatory")
        & (pl.col("is_external_tour") == True)
        & pl.col("destination").is_not_null()
    ).select("destination", "finalweight")

    if base.is_empty():
        return empty_summary_frame(ext_non_mand_tour_loc)

    outputs = [
        aggregate_counts(
            base,
            geography_type="maz",
            geography_id_col="destination",
        )
    ]

    # TODO Adapt this block to existing destination-geography helper pattern.
    # Expected idea:
    # if config.geography_enabled:
    #     for geography_type, lookup_df in config.destination_maz_geography_lookups():
    #         # lookup_df maps MAZ -> geography_id
    #         geo_df = (
    #             base.join(
    #                 lookup_df,
    #                 left_on="destination",
    #                 right_on="MAZ",
    #                 how="inner",
    #             )
    #             .pipe(aggregate_counts, geography_type, "geography_id")
    #         )
    #         outputs.append(geo_df)

    return (
        pl.concat(outputs, how="vertical")
        .with_columns(
            pl.col("geography_type").cast(pl.Utf8),
            pl.col("geography_id").cast(pl.Utf8),
            pl.col("external_nonmandatory_tour_count").cast(pl.Float64),
        )
        .select(
            "geography_type",
            "geography_id",
            "external_nonmandatory_tour_count",
        )
        .sort(["geography_type", "geography_id"])
    )
