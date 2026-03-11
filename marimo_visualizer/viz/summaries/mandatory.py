"""Mandatory travel summaries: TLFD, tour lengths, WFH, telecommute, and geography flows."""

from __future__ import annotations

import polars as pl

from ..models import Config, RunData


def tlfd(rd: RunData, config: Config) -> dict[str, pl.DataFrame]:
    """Trip length frequency distributions for work, university, and school trips."""
    dist_bins = list(range(1, 52))

    def _bin_dist(df: pl.DataFrame, dist_col: str) -> pl.DataFrame:
        return (
            df.with_columns(pl.col(dist_col).fill_null(0.0).clip(0, 9999))
            .with_columns((pl.col(dist_col).cast(pl.Int32) + 1).clip(1, 51).alias("distbin"))
        )

    def _make_tlfd(persons: pl.DataFrame, dist_col: str) -> pl.DataFrame:
        if dist_col not in persons.columns:
            return pl.DataFrame({"distbin": dist_bins, "Total": [0.0] * 51})
        df = _bin_dist(persons, dist_col)
        result = pl.DataFrame({"distbin": dist_bins})

        if config.geography_enabled and "HGEO" in df.columns:
            groups = df["HGEO"].drop_nulls().unique().to_list()
            groups.sort()
            for group in groups:
                agg = (
                    df.filter(pl.col("HGEO") == group)
                    .group_by("distbin")
                    .agg(pl.col("finalweight").sum().alias(str(group)))
                )
                result = result.join(agg, on="distbin", how="left")
            result = result.with_columns([pl.col(str(group)).fill_null(0) for group in groups])
            result = result.with_columns(pl.sum_horizontal([str(group) for group in groups]).alias("Total"))
        else:
            agg = df.group_by("distbin").agg(pl.col("finalweight").sum().alias("Total"))
            result = result.join(agg, on="distbin", how="left")
            result = result.with_columns(pl.col("Total").fill_null(0))

        return result.sort("distbin")

    ptype_col = config.col_ptype
    workers = (
        rd.per.filter(
            (pl.col("workplace_zone_id") > 0)
            & (pl.col("is_worker").cast(pl.Utf8).str.to_lowercase().is_in(["true", "1"]))
        )
        if "is_worker" in rd.per.columns
        else rd.per.head(0)
    )

    if ptype_col in rd.per.columns:
        univ = (
            rd.per.filter(
                (pl.col("school_zone_id") > 0)
                & (pl.col("is_student").cast(pl.Utf8).str.to_lowercase().is_in(["true", "1"]))
                & (pl.col(ptype_col).cast(pl.Utf8) == "3")
            )
            if "is_student" in rd.per.columns
            else rd.per.head(0)
        )
        schl = (
            rd.per.filter(
                (pl.col("school_zone_id") > 0)
                & (pl.col("is_student").cast(pl.Utf8).str.to_lowercase().is_in(["true", "1"]))
                & (pl.col(ptype_col).cast(pl.Utf8).cast(pl.Int32, strict=False) >= 6)
            )
            if "is_student" in rd.per.columns
            else rd.per.head(0)
        )
    else:
        univ = rd.per.head(0)
        schl = rd.per.head(0)

    return {
        "work": _make_tlfd(workers, "distance_to_work"),
        "univ": _make_tlfd(univ, "distance_to_school"),
        "schl": _make_tlfd(schl, "distance_to_school"),
    }


def mand_tour_lengths(rd: RunData, config: Config) -> pl.DataFrame:
    """Average mandatory tour lengths by geography and total."""
    ptype_col = config.col_ptype

    workers = (
        rd.per.filter(
            (pl.col("workplace_zone_id") > 0)
            & (pl.col("is_worker").cast(pl.Utf8).str.to_lowercase().is_in(["true", "1"]))
        )
        if "is_worker" in rd.per.columns
        else rd.per.head(0)
    )

    if ptype_col in rd.per.columns:
        univ_students = (
            rd.per.filter(
                (pl.col("school_zone_id") > 0)
                & (pl.col("is_student").cast(pl.Utf8).str.to_lowercase().is_in(["true", "1"]))
                & (pl.col(ptype_col).cast(pl.Utf8) == "3")
            )
            if "is_student" in rd.per.columns
            else rd.per.head(0)
        )
        school_students = (
            rd.per.filter(
                (pl.col("school_zone_id") > 0)
                & (pl.col("is_student").cast(pl.Utf8).str.to_lowercase().is_in(["true", "1"]))
                & (pl.col(ptype_col).cast(pl.Utf8).cast(pl.Int32, strict=False) >= 6)
            )
            if "is_student" in rd.per.columns
            else rd.per.head(0)
        )
    else:
        univ_students = rd.per.head(0)
        school_students = rd.per.head(0)

    def _avg_by_geo(persons: pl.DataFrame, dist_col: str, geo_col: str = "HGEO") -> pl.DataFrame:
        if dist_col not in persons.columns or len(persons) == 0:
            return pl.DataFrame({"Geography": ["Total"], "avg": [None]})
        rows: list[dict[str, object]] = []
        if config.geography_enabled and geo_col in persons.columns:
            groups = sorted(persons[geo_col].drop_nulls().unique().to_list())
            for group in groups:
                subset = persons.filter(pl.col(geo_col) == group)
                rows.append({"Geography": str(group), "avg": subset[dist_col].mean()})
        rows.append({"Geography": "Total", "avg": persons[dist_col].mean()})
        return pl.DataFrame(rows)

    work_df = _avg_by_geo(workers, "distance_to_work").rename({"avg": "Work"})
    univ_df = _avg_by_geo(univ_students, "distance_to_school").rename({"avg": "Univ"})
    school_df = _avg_by_geo(school_students, "distance_to_school").rename({"avg": "Schl"})

    result = work_df.join(univ_df, on="Geography", how="outer_coalesce").join(school_df, on="Geography", how="outer_coalesce")
    non_total = result.filter(pl.col("Geography") != "Total")
    total_row = result.filter(pl.col("Geography") == "Total")
    return pl.concat([non_total, total_row])


def wfh(rd: RunData, config: Config) -> pl.DataFrame:
    """Work-from-home summary by geography and total."""
    if "is_worker" not in rd.per.columns:
        return pl.DataFrame({"Geography": ["Total"], "Workers": [0.0], "WFH": [0.0]})

    workers = rd.per.filter(pl.col("is_worker").cast(pl.Utf8).str.to_lowercase().is_in(["true", "1"]))
    wfh_col = "work_from_home"
    rows: list[dict[str, object]] = []

    if config.geography_enabled and "HGEO" in workers.columns:
        groups = sorted(workers["HGEO"].drop_nulls().unique().to_list())
        for group in groups:
            subset = workers.filter(pl.col("HGEO") == group)
            n_workers = subset["finalweight"].sum()
            n_wfh = (
                subset.filter(pl.col(wfh_col).cast(pl.Utf8).str.to_lowercase().is_in(["true", "1"]))["finalweight"].sum()
                if wfh_col in subset.columns
                else 0.0
            )
            rows.append({"Geography": str(group), "Workers": n_workers, "WFH": n_wfh})

    total_workers = workers["finalweight"].sum()
    total_wfh = (
        workers.filter(pl.col(wfh_col).cast(pl.Utf8).str.to_lowercase().is_in(["true", "1"]))["finalweight"].sum()
        if wfh_col in workers.columns
        else 0.0
    )
    rows.append({"Geography": "Total", "Workers": total_workers, "WFH": total_wfh})
    return pl.DataFrame(rows)


def telecommute(rd: RunData) -> pl.DataFrame:
    """Telecommute frequency distribution."""
    if "telecommute_frequency" not in rd.per.columns:
        return pl.DataFrame({"telecommute_frequency": [], "freq": []})
    df = (
        rd.per.filter(pl.col("telecommute_frequency").is_not_null() & (pl.col("telecommute_frequency") != ""))
        .group_by("telecommute_frequency")
        .agg(pl.col("finalweight").sum().alias("freq"))
    )
    return df.sort("telecommute_frequency")


def geo_flows(rd: RunData, config: Config) -> pl.DataFrame:
    """Home-to-work geography flow matrix."""
    if not config.geography_enabled or "HGEO" not in rd.per.columns or "WGEO" not in rd.per.columns:
        return pl.DataFrame()

    workers = (
        rd.per.filter(pl.col("is_worker").cast(pl.Utf8).str.to_lowercase().is_in(["true", "1"]))
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

    geo_cols = [col for col in pivot.columns if col != "HGEO"]
    pivot = pivot.fill_null(0)
    pivot = pivot.with_columns(pl.sum_horizontal(geo_cols).alias("Total"))

    total_vals: dict[str, object] = {"HGEO": "Total"}
    for col in geo_cols + ["Total"]:
        if col in pivot.columns:
            total_vals[col] = pivot[col].sum()
    return pl.concat([pivot, pl.DataFrame([total_vals])])
