"""Mandatory travel summaries: TLFD, tour lengths, WFH, telecommute, geography flows.

Geography summaries (TLFD breakdown, flows) are only computed when geography is enabled
(config.geography_enabled). The geographic grouping column is HGEO/WGEO, derived from
the land_use file column specified in config.geography_landuse_col.
"""

import polars as pl
from .reader import RunData, Config


# ---------------------------------------------------------------------------
# Average mandatory tour lengths
# ---------------------------------------------------------------------------


def mand_tour_lengths(rd: RunData, config: Config) -> pl.DataFrame:
    """Average mandatory tour lengths.

    Columns: Geography, Work, Univ, Schl.
    If geography disabled, returns a single Total row.
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
        persons: pl.DataFrame, dist_col: str, geo_col: str = "HGEO"
    ) -> pl.DataFrame:
        if dist_col not in persons.columns or len(persons) == 0:
            return pl.DataFrame({"Geography": ["Total"], "avg": [None]})
        rows = []
        if config.geography_enabled and geo_col in persons.columns:
            groups = sorted(persons[geo_col].drop_nulls().unique().to_list())
            for grp in groups:
                sub = persons.filter(pl.col(geo_col) == grp)
                rows.append({"Geography": str(grp), "avg": sub[dist_col].mean()})
        rows.append({"Geography": "Total", "avg": persons[dist_col].mean()})
        return pl.DataFrame(rows)

    w = _avg_by_geo(workers, "distance_to_work").rename({"avg": "Work"})
    u = _avg_by_geo(univ_s, "distance_to_school").rename({"avg": "Univ"})
    s = _avg_by_geo(schl_s, "distance_to_school").rename({"avg": "Schl"})

    result = w.join(u, on="Geography", how="outer_coalesce").join(
        s, on="Geography", how="outer_coalesce"
    )
    non_total = result.filter(pl.col("Geography") != "Total")
    total_row = result.filter(pl.col("Geography") == "Total")
    return pl.concat([non_total, total_row])


# ---------------------------------------------------------------------------
# Geography flows
# ---------------------------------------------------------------------------


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
