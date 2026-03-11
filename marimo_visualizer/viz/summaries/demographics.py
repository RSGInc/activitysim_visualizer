"""Household and person demographic summaries."""

from __future__ import annotations

import polars as pl

from ..models import Config, RunData


def auto_ownership(rd: RunData) -> pl.DataFrame:
    """Return HH vehicle ownership distribution with weighted counts and percents."""
    df = rd.hh.group_by("HHVEH").agg(pl.col("finalweight").sum().alias("freq"))
    total = df["freq"].sum()
    df = df.with_columns((pl.col("freq") / total * 100).alias("pct"))
    return df.sort("HHVEH")


def person_type(rd: RunData, config: Config) -> pl.DataFrame:
    """Return person type distribution with display labels."""
    ptype_col = config.col_ptype
    if ptype_col not in rd.per.columns:
        return pl.DataFrame({"ptype": [], "ptype_name": [], "freq": [], "pct": []})
    df = rd.per.group_by(ptype_col).agg(pl.col("finalweight").sum().alias("freq"))
    total = df["freq"].sum()
    df = df.with_columns((pl.col("freq") / total * 100).alias("pct"))
    df = df.rename({ptype_col: "ptype"}).with_columns(
        pl.col("ptype").cast(pl.Utf8).map_elements(lambda value: config.ptype_label(value), return_dtype=pl.Utf8).alias("ptype_name")
    )
    return df.sort("ptype")


def hh_size(rd: RunData) -> pl.DataFrame:
    """Return household size distribution with weighted counts and percents."""
    df = rd.hh.group_by("HHSIZE").agg(pl.col("finalweight").sum().alias("freq"))
    total = df["freq"].sum()
    df = df.with_columns((pl.col("freq") / total * 100).alias("pct"))
    return df.sort("HHSIZE")
