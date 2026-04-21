import polars as pl
from runtime.config import Config
from runtime.models import RunData
from runtime.run_data import resolve_source_column


def _tour_purpose_column(tours: pl.DataFrame, config: Config) -> str | None:
    """Return the config-resolved tour-purpose column for prepared summaries."""
    return resolve_source_column(
        tours,
        config.col_tour_purpose,
        require_non_numeric=True,
    )


def geo_flows(rd: RunData, config: Config) -> pl.DataFrame:
    """Home-to-work geography flow matrix.

    Returns wide DataFrame: row=HGEO, col=WGEO value, plus Total row/col.
    Returns empty DataFrame if geography is not enabled.
    """
    if (
        not config.geography_enabled
        or "HGEO" not in rd.per.columns
        or "WGEO" not in rd.per.columns
    ):
        return pl.DataFrame()

    workers = (
        rd.per.filter(
            pl.col("is_worker").cast(pl.Utf8).str.to_lowercase().is_in(["true", "1"])
        )
        if "is_worker" in rd.per.columns
        else rd.per
    )

    pivot = (
        workers.filter(pl.col("HGEO").is_not_null() & pl.col("WGEO").is_not_null())
        .group_by(["HGEO", "WGEO"])
        .agg(pl.col("finalweight").sum().alias("n"))
        .pivot(on="WGEO", index="HGEO", values="n", aggregate_function="sum")
    )

    if len(pivot) == 0:
        return pl.DataFrame()

    geo_cols = [c for c in pivot.columns if c != "HGEO"]
    pivot = pivot.fill_null(0)
    pivot = pivot.with_columns(pl.sum_horizontal(geo_cols).alias("Total"))

    # Totals row
    total_vals: dict = {"HGEO": "Total"}
    for col in geo_cols + ["Total"]:
        if col in pivot.columns:
            total_vals[col] = pivot[col].sum()
    pivot = pl.concat([pivot, pl.DataFrame([total_vals])])
    return pivot


def _combined_nm_tours(
    rd: RunData,
    config: Config,
    purpose: str | None = None,
) -> pl.DataFrame:
    tours = rd.tours
    if "tour_category" not in tours.columns:
        return pl.DataFrame({"SKIMDIST": [], "finalweight": []})
    purpose_col = _tour_purpose_column(tours, config)

    indiv = tours.filter(pl.col("tour_category").is_in(["non-mandatory", "atwork"]))
    joint = tours.filter(pl.col("tour_category") == "joint")
    if len(joint) > 0:
        joint = joint.with_columns(
            (pl.col("finalweight") * pl.col("NUMBER_HH").fill_null(1)).alias(
                "finalweight"
            )
        )

    if purpose and purpose != "All NM":
        if purpose_col is None:
            return pl.DataFrame({"SKIMDIST": [], "finalweight": []})
        indiv = indiv.filter(pl.col(purpose_col).cast(pl.Utf8) == purpose)
        joint = joint.filter(pl.col(purpose_col).cast(pl.Utf8) == purpose)

    parts: list[pl.DataFrame] = []
    for df in (indiv, joint):
        if len(df) > 0 and "SKIMDIST" in df.columns and "finalweight" in df.columns:
            parts.append(df.select(["SKIMDIST", "finalweight"]))

    if not parts:
        return pl.DataFrame({"SKIMDIST": [], "finalweight": []})
    return pl.concat(parts)


def distance_distribution(rd: RunData, config: Config) -> pl.DataFrame:
    """NM destination distance distribution by purpose.

    Columns: purpose, distbin, freq
    """
    tours = rd.tours
    purpose_col = _tour_purpose_column(tours, config)
    if "tour_category" in tours.columns and purpose_col is not None:
        purposes = sorted(
            tours.filter(
                pl.col("tour_category").is_in(["non-mandatory", "atwork", "joint"])
            )[purpose_col]
            .drop_nulls()
            .cast(pl.Utf8)
            .unique()
            .to_list()
        )
    else:
        purposes = []

    labels = ["All NM"] + purposes
    bins = list(range(41))
    rows: list[dict[str, object]] = []
    for purpose in labels:
        combined = _combined_nm_tours(rd, config, purpose)
        if len(combined) > 0 and "SKIMDIST" in combined.columns:
            combined = combined.with_columns(
                pl.col("SKIMDIST").cast(pl.Float64).fill_null(0.0).clip(0, 999.0)
            ).with_columns(
                pl.col("SKIMDIST").cast(pl.Int32).clip(0, 40).alias("distbin")
            )
            counts = combined.group_by("distbin").agg(
                pl.col("finalweight").sum().alias("freq")
            )
            freq_map = {
                int(row["distbin"]): float(row["freq"])
                for row in counts.iter_rows(named=True)
            }
        else:
            freq_map = {}

        for distbin in bins:
            rows.append(
                {
                    "purpose": purpose,
                    "distbin": distbin,
                    "freq": freq_map.get(distbin, 0.0),
                }
            )

    return pl.DataFrame(
        rows,
        schema={
            "purpose": pl.Utf8,
            "distbin": pl.Int32,
            "freq": pl.Float64,
        },
    )


def average_distance(rd: RunData, config: Config) -> pl.DataFrame:
    """Average NM tour distance by purpose.

    Columns: purpose, avg_distance
    """
    result_schema = {
        "purpose": pl.Utf8,
        "avg_distance": pl.Float64,
    }

    tours = rd.tours
    purpose_col = _tour_purpose_column(tours, config)
    if "tour_category" in tours.columns and purpose_col is not None:
        purposes = sorted(
            tours.filter(
                pl.col("tour_category").is_in(["non-mandatory", "atwork", "joint"])
            )[purpose_col]
            .drop_nulls()
            .cast(pl.Utf8)
            .unique()
            .to_list()
        )
    else:
        purposes = []

    rows: list[dict[str, object]] = []
    for purpose in purposes:
        combined = _combined_nm_tours(rd, config, purpose)
        if len(combined) == 0:
            avg_distance = None
        else:
            valid = combined.filter(
                pl.col("SKIMDIST").is_not_null() & pl.col("finalweight").is_not_null()
            )
            if len(valid) == 0:
                avg_distance = None
            else:
                weights = valid["finalweight"].to_numpy()
                distances = valid["SKIMDIST"].to_numpy()
                total_weight = float(weights.sum())
                avg_distance = (
                    float((distances * weights).sum() / total_weight)
                    if total_weight > 0
                    else None
                )
        rows.append({"purpose": purpose, "avg_distance": avg_distance})

    return pl.DataFrame(rows, schema=result_schema)


def nm_tour_rates(rd: RunData, config: Config) -> pl.DataFrame:
    """NM tour rates per person by person type and purpose.

    Columns: ptype, tour_purp, tour_rate.
    """
    result_schema = {
        "ptype": pl.Utf8,
        "tour_purp": pl.Utf8,
        "tour_rate": pl.Float64,
    }
    ptype_col = "person_type" if "person_type" in rd.per.columns else None
    purpose_col = _tour_purpose_column(rd.tours, config)
    if (
        "tour_category" not in rd.tours.columns
        or purpose_col is None
        or ptype_col is None
        or ptype_col not in rd.tours.columns
    ):
        return pl.DataFrame(schema=result_schema)

    nm_tours = rd.tours.filter(pl.col("tour_category") == "non-mandatory")
    purposes = (
        nm_tours[purpose_col].drop_nulls().cast(pl.Utf8).unique().sort().to_list()
    )

    per_counts = rd.per.group_by(ptype_col).agg(
        pl.col("finalweight").sum().alias("n_per")
    )
    total_per = rd.per["finalweight"].sum()
    ptypes = rd.per[ptype_col].drop_nulls().unique().to_list()

    nm_grouped = nm_tours.group_by([ptype_col, purpose_col]).agg(
        pl.col("finalweight").sum().alias("n_tours")
    )

    result = []
    for ptype in ptypes:
        n_per_row = per_counts.filter(pl.col(ptype_col) == ptype)["n_per"]
        n_per = float(n_per_row[0]) if len(n_per_row) > 0 else 0
        for purp in purposes:
            n_row = nm_grouped.filter(
                (pl.col(ptype_col) == ptype)
                & (pl.col(purpose_col).cast(pl.Utf8) == purp)
            )["n_tours"]
            n = float(n_row[0]) if len(n_row) > 0 else 0
            result.append(
                {
                    "ptype": str(ptype),
                    "tour_purp": purp,
                    "tour_rate": (n / n_per) if n_per > 0 else 0,
                }
            )

    for purp in purposes:
        n_row = nm_grouped.filter(pl.col(purpose_col).cast(pl.Utf8) == purp)["n_tours"]
        n = float(n_row.sum()) if len(n_row) > 0 else 0
        result.append(
            {
                "ptype": "All",
                "tour_purp": purp,
                "tour_rate": (
                    (n / float(total_per)) if total_per and total_per > 0 else 0
                ),
            }
        )

    return pl.DataFrame(result, schema=result_schema)


def system_totals(rd: RunData, config: Config | None = None) -> pl.DataFrame:
    """
    System-wide KPIs. Returns single-row DataFrame with columns:
    population, households, employment, tours, trips, stops,
    pmt, vmt, vehicle_trips.
    """
    result_schema = {
        "population": pl.Float64,
        "households": pl.Float64,
        "employment": pl.Float64,
        "tours": pl.Float64,
        "trips": pl.Float64,
        "stops": pl.Float64,
        "pmt": pl.Float64,
        "vmt": pl.Float64,
        "vehicle_trips": pl.Float64,
    }
    pop = rd.per["finalweight"].sum()
    hh = rd.hh["finalweight"].sum()
    emp_col = next(
        (
            c
            for c in ["EMPLOY_TOT", "TOTEMP", "total_employment", "employment"]
            if c in rd.land_use.columns
        ),
        None,
    )
    emp = rd.land_use[emp_col].sum() if emp_col else 0

    tours = rd.tours["finalweight"].sum()
    trips_total = rd.trips["finalweight"].sum()
    stops = rd.trips.filter(pl.col("stops") == 1)["finalweight"].sum()

    # PMT = sum of od_dist * finalweight for all trips
    pmt = rd.trips.with_columns(
        (pl.col("od_dist") * pl.col("finalweight")).alias("pmt_w")
    )["pmt_w"].sum()

    # Identify auto trips via trip_mode string:
    # Use config.mode_groups["Auto"] if defined, else check for common auto mode substrings.
    trips_df = rd.trips
    if "trip_mode" in trips_df.columns:
        auto_modes: list[str] | None = None
        if config is not None and config.mode_groups and "Auto" in config.mode_groups:
            auto_modes = config.mode_groups["Auto"]

        if auto_modes is not None:
            auto_filter = pl.col("trip_mode").cast(pl.Utf8).is_in(auto_modes)
        else:
            # Fallback: modes that look like auto (drive alone / shared ride)
            auto_filter = (
                pl.col("trip_mode")
                .cast(pl.Utf8)
                .str.to_uppercase()
                .str.contains("DRIVE|SHARED|SOV|HOV|AUTO")
            )
        auto_trips = trips_df.filter(auto_filter)
    else:
        auto_trips = trips_df.head(0)

    vmt = auto_trips.with_columns(
        (
            pl.col("od_dist")
            * pl.col("finalweight")
            / pl.col("num_participants").fill_null(1)
        ).alias("vmt_w")
    )["vmt_w"].sum()

    vehicle_trips = auto_trips["finalweight"].sum()

    return pl.DataFrame(
        [
            {
                "population": float(pop) if pop is not None else 0.0,
                "households": float(hh) if hh is not None else 0.0,
                "employment": float(emp) if emp is not None else 0.0,
                "tours": float(tours) if tours is not None else 0.0,
                "trips": float(trips_total) if trips_total is not None else 0.0,
                "stops": float(stops) if stops is not None else 0.0,
                "pmt": float(pmt) if pmt is not None else 0.0,
                "vmt": float(vmt) if vmt is not None else 0.0,
                "vehicle_trips": (
                    float(vehicle_trips) if vehicle_trips is not None else 0.0
                ),
            }
        ],
        schema=result_schema,
    )


def tour_mode_profile(rd: RunData, config: Config) -> pl.DataFrame:
    """Tour mode by auto sufficiency level (0, 1, 2) and total, by tour purpose/category.

    Returns DataFrame: tour_mode, purpose_group, freq_as0, freq_as1, freq_as2, freq_all.
    Purpose groups are derived from the config-resolved tour purpose column.
    """
    result_schema = {
        "tour_mode": pl.Utf8,
        "purpose": pl.Utf8,
        "freq_as0": pl.Float64,
        "freq_as1": pl.Float64,
        "freq_as2": pl.Float64,
        "freq_all": pl.Float64,
    }
    if "tour_mode" not in rd.tours.columns:
        return pl.DataFrame(schema=result_schema)

    indiv = (
        rd.tours.filter(
            pl.col("tour_category").is_in(["mandatory", "non-mandatory", "atwork"])
        )
        if "tour_category" in rd.tours.columns
        else rd.tours
    )
    joint = (
        (
            rd.tours.filter(pl.col("tour_category") == "joint").with_columns(
                (pl.col("finalweight") * pl.col("NUMBER_HH")).alias("wgt")
            )
        )
        if "tour_category" in rd.tours.columns
        else rd.tours.head(0)
    )

    # Build purpose group filter pairs: (label, df, filter_expr)
    purpose_groups = []
    purpose_col = _tour_purpose_column(rd.tours, config)
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
        purpose_groups.append(("all", rd.tours, pl.lit(True)))

    all_modes = rd.tours["tour_mode"].drop_nulls().unique().to_list()
    all_modes = config.ordered_modes(all_modes)

    result_rows = []
    for purp_name, df, purp_filter in purpose_groups:
        wgt_col = "wgt" if "wgt" in df.columns else "finalweight"
        for as_val in range(3):
            as_filter = (
                (pl.col("AUTOSUFF") == as_val)
                if "AUTOSUFF" in df.columns
                else pl.lit(True)
            )
            sub = df.filter(purp_filter & as_filter)
            counts = sub.group_by("tour_mode").agg(pl.col(wgt_col).sum().alias("n"))
            for mode in all_modes:
                n_row = counts.filter(pl.col("tour_mode") == mode)["n"]
                n = float(n_row[0]) if len(n_row) > 0 else 0.0
                result_rows.append(
                    {
                        "tour_mode": mode,
                        "purpose": purp_name,
                        "autosuff": as_val,
                        "freq": n,
                    }
                )

    if not result_rows:
        return pl.DataFrame()

    df_result = pl.DataFrame(
        result_rows,
        schema={
            "tour_mode": pl.Utf8,
            "purpose": pl.Utf8,
            "autosuff": pl.Int32,
            "freq": pl.Float64,
        },
    )
    pivot = df_result.pivot(
        on="autosuff",
        index=["tour_mode", "purpose"],
        values="freq",
        aggregate_function="sum",
    ).fill_null(0)

    for as_val in range(3):
        col = str(as_val)
        if col in pivot.columns:
            pivot = pivot.rename({col: f"freq_as{as_val}"})
    for col in ["freq_as0", "freq_as1", "freq_as2"]:
        if col not in pivot.columns:
            pivot = pivot.with_columns(pl.lit(0.0).alias(col))

    pivot = pivot.with_columns(
        (pl.col("freq_as0") + pl.col("freq_as1") + pl.col("freq_as2")).alias("freq_all")
    )

    cols = ["tour_mode", "purpose", "freq_as0", "freq_as1", "freq_as2", "freq_all"]
    pivot = pivot.select(cols)
    total = (
        pivot.group_by("tour_mode")
        .agg(
            [
                pl.col("freq_as0").sum(),
                pl.col("freq_as1").sum(),
                pl.col("freq_as2").sum(),
                pl.col("freq_all").sum(),
            ]
        )
        .with_columns(pl.lit("Total").alias("purpose"))
        .select(cols)
    )

    return pl.concat([pivot, total], how="vertical")


def grouped_tour_mode_profile(rd: RunData, config: Config) -> pl.DataFrame:
    """Tour mode grouped by config.mode_groups, by auto sufficiency and purpose.

    Returns DataFrame: mode_group, purpose, freq_as0, freq_as1, freq_as2, freq_all.
    Returns empty DataFrame if mode_groups not configured.
    """
    result_schema = {
        "mode_group": pl.Utf8,
        "purpose": pl.Utf8,
        "freq_as0": pl.Float64,
        "freq_as1": pl.Float64,
        "freq_as2": pl.Float64,
        "freq_all": pl.Float64,
    }

    if not config.mode_groups:
        return pl.DataFrame(schema=result_schema)

    detail = tour_mode_profile(rd, config)
    if len(detail) == 0:
        return pl.DataFrame(schema=result_schema)

    mode_to_group = {}
    for grp, modes in config.mode_groups.items():
        for m in modes:
            mode_to_group[m] = grp

    group_map = pl.DataFrame(
        {
            "tour_mode": list(mode_to_group.keys()),
            "mode_group": list(mode_to_group.values()),
        },
        schema={
            "tour_mode": pl.Utf8,
            "mode_group": pl.Utf8,
        },
    )

    result = (
        detail.join(group_map, on="tour_mode", how="left")
        .filter(pl.col("mode_group").is_not_null())
        .group_by(["mode_group", "purpose"])
        .agg(
            [
                pl.col("freq_as0").sum(),
                pl.col("freq_as1").sum(),
                pl.col("freq_as2").sum(),
                pl.col("freq_all").sum(),
            ]
        )
    )
    return result
