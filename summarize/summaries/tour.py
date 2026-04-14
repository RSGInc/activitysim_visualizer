"""Tour summaries."""

import polars as pl
from runtime.config import Config
from runtime.models import RunData


def tour_category(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def tour_purpose(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def allocated_vehicle_age(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def allocated_vehicle_fuel(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def allocated_vehicle_body(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def tour_mode(rd: RunData, config: Config) -> pl.DataFrame:
    """Tour mode by auto sufficiency level and total, by tour purpose/category.

    Returns DataFrame:
    tour_mode, tour_purpose,
    tour_count_zero_auto, tour_count_auto_deficient,
    tour_count_auto_sufficient, tour_count_all_households.
    """
    if "tour_mode" not in rd.tours.columns:
        return pl.DataFrame(
            {
                "tour_mode": [],
                "tour_purpose": [],
                "tour_count_zero_auto": [],
                "tour_count_auto_deficient": [],
                "tour_count_auto_sufficient": [],
                "tour_count_all_households": [],
            }
        )

    indiv = (
        rd.tours.filter(
            pl.col("tour_category").is_in(["mandatory", "non-mandatory", "atwork"])
        )
        if "tour_category" in rd.tours.columns
        else rd.tours
    )

    joint = (
        rd.tours.filter(pl.col("tour_category") == "joint").with_columns(
            (pl.col("finalweight") * pl.col("NUMBER_HH")).alias("wgt")
        )
        if "tour_category" in rd.tours.columns
        else rd.tours.head(0)
    )

    purpose_groups = []
    purpose_col = None
    for cand in ("primary_purpose", "tour_type", "purpose"):
        if cand in rd.tours.columns and not rd.tours[cand].dtype.is_numeric():
            purpose_col = cand
            break

    if purpose_col:
        purposes = (
            indiv[purpose_col].drop_nulls().cast(pl.Utf8).unique().sort().to_list()
        )
        for p in purposes:
            purpose_groups.append((p, indiv, pl.col(purpose_col).cast(pl.Utf8) == p))

        if len(joint) > 0:
            j_purposes = (
                joint[purpose_col].drop_nulls().cast(pl.Utf8).unique().sort().to_list()
            )
            for p in j_purposes:
                purpose_groups.append(
                    (f"joint_{p}", joint, pl.col(purpose_col).cast(pl.Utf8) == p)
                )
    else:
        purpose_groups.append(("all_tour_purposes", rd.tours, pl.lit(True)))

    all_modes = rd.tours["tour_mode"].drop_nulls().unique().to_list()
    all_modes = config.ordered_modes(all_modes)

    result_rows = []
    for purpose_name, df, purpose_filter in purpose_groups:
        wgt_col = "wgt" if "wgt" in df.columns else "finalweight"

        for as_val in range(3):
            as_filter = (
                (pl.col("AUTOSUFF") == as_val)
                if "AUTOSUFF" in df.columns
                else pl.lit(True)
            )

            sub = df.filter(purpose_filter & as_filter)
            counts = sub.group_by("tour_mode").agg(pl.col(wgt_col).sum().alias("n"))

            for mode in all_modes:
                n_row = counts.filter(pl.col("tour_mode") == mode)["n"]
                n = float(n_row[0]) if len(n_row) > 0 else 0.0
                result_rows.append(
                    {
                        "tour_mode": mode,
                        "tour_purpose": purpose_name,
                        "autosuff": as_val,
                        "tour_count": n,
                    }
                )

    if not result_rows:
        return pl.DataFrame(
            {
                "tour_mode": [],
                "tour_purpose": [],
                "tour_count_zero_auto": [],
                "tour_count_auto_deficient": [],
                "tour_count_auto_sufficient": [],
                "tour_count_all_households": [],
            }
        )

    df_result = pl.DataFrame(result_rows)

    pivot = df_result.pivot(
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


def stop_freq(rd: RunData, config: Config) -> pl.DataFrame:
    """Stop frequency by tour purpose (outbound, inbound, total).
    Returns DataFrame:
    tour_purpose, outbound_stop_count (0-3+), inbound_stop_count (0-3+), total_stop_count (0-6+), tour_count.
    """
    # Find a valid non-numeric purpose column if available
    purpose_col = None
    for cand in ("primary_purpose", "tour_type", "purpose"):
        if cand in rd.tours.columns and not rd.tours[cand].dtype.is_numeric():
            purpose_col = cand
            break

    if purpose_col is None:
        return pl.DataFrame(
            {
                "tour_purpose": [],
                "outbound_stop_count": [],
                "inbound_stop_count": [],
                "total_stop_count": [],
                "tour_count": [],
            }
        )

    return (
        rd.tours.filter(pl.col("tour_category").is_not_null())
        .with_columns(
            [
                pl.col("num_ob_stops").clip(0, 3).alias("outbound_stop_count"),
                pl.col("num_ib_stops").clip(0, 3).alias("inbound_stop_count"),
                pl.col("num_tot_stops").clip(0, 6).alias("total_stop_count"),
            ]
        )
        .group_by(
            [
                purpose_col,
                "outbound_stop_count",
                "inbound_stop_count",
                "total_stop_count",
            ]
        )
        .agg(tour_count=pl.col("finalweight").sum())
        .rename({purpose_col: "tour_purpose"})
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


def at_work_sub_tour_freq(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def tour_tod(rd: RunData, config: Config) -> pl.DataFrame:
    """Departure, arrival, and duration profiles in 48 half-hour bins.

    Returns DataFrame: time_bin (1-48), tour_purpose, departure_tour_count,
    arrival_tour_count, duration_tour_count.
    """
    if "tour_category" not in rd.tours.columns:
        return pl.DataFrame(
            {
                "time_bin": [],
                "tour_purpose": [],
                "departure_tour_count": [],
                "arrival_tour_count": [],
                "duration_tour_count": [],
            }
        )

    indiv = rd.tours.filter(
        pl.col("tour_category").is_in(["mandatory", "non-mandatory", "atwork"])
    )

    joint = rd.tours.filter(pl.col("tour_category") == "joint").with_columns(
        (pl.col("finalweight") * pl.col("NUMBER_HH")).alias("wgt")
    )

    purpose_col = None
    for cand in ("primary_purpose", "tour_type", "purpose"):
        if cand in rd.tours.columns and not rd.tours[cand].dtype.is_numeric():
            purpose_col = cand
            break

    purpose_groups = []
    if purpose_col:
        purps = indiv[purpose_col].drop_nulls().unique().sort().to_list()
        for p in purps:
            purpose_groups.append((p, indiv, pl.col(purpose_col) == p))

        if len(joint) > 0:
            j_purps = joint[purpose_col].drop_nulls().unique().sort().to_list()
            for p in j_purps:
                purpose_groups.append((f"joint_{p}", joint, pl.col(purpose_col) == p))
    else:
        purpose_groups.append(("all_tour_purposes", rd.tours, pl.lit(True)))

    max_period = 48
    if "start_hour" in rd.tours.columns:
        try:
            max_period = int(rd.tours["start_hour"].max())
        except Exception:
            max_period = 48

    bins = list(range(1, 25 if max_period <= 24 else 49))

    def _hist(df: pl.DataFrame, col: str, wgt_col: str, filt) -> pl.DataFrame:
        if col not in df.columns:
            return pl.DataFrame({"time_bin": bins, "n": [0.0] * len(bins)})

        sub = (
            df.filter(filt)
            .select([col, wgt_col])
            .with_columns(pl.col(col).cast(pl.Int32).alias("time_bin"))
            .filter(pl.col("time_bin").is_between(1, bins[-1]))
        )

        counts = sub.group_by("time_bin").agg(pl.col(wgt_col).sum().alias("n"))
        base = pl.DataFrame({"time_bin": bins})
        return base.join(counts, on="time_bin", how="left").fill_null(0)

    all_rows = []
    for purpose_name, df, filt in purpose_groups:
        wgt = "wgt" if "wgt" in df.columns else "finalweight"

        dep = _hist(df, "start_hour", wgt, filt)
        arr = _hist(df, "end_hour", wgt, filt)
        dur = _hist(df, "tourdur", wgt, filt)

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
        return pl.DataFrame(
            {
                "time_bin": [],
                "tour_purpose": [],
                "departure_tour_count": [],
                "arrival_tour_count": [],
                "duration_tour_count": [],
            }
        )

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


def tour_distance(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def avg_mand_tour_distance(rd: RunData, config: Config) -> pl.DataFrame:
    """Average mandatory tour distances.

    Returns DataFrame: mandatory_tour_purpose, geography, average_tour_distance.
    """
    ptype_col = config.col_ptype

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

    if ptype_col in rd.per.columns:
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

        return pl.DataFrame(rows)

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


def int_vs_ext_non_mand_tour_freq(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()


def ext_non_mand_tour_loc(rd: RunData, config: Config) -> pl.DataFrame:
    raise NotImplementedError()
