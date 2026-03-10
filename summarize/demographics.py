"""Household and person demographic summaries."""
import polars as pl
from .reader import RunData, Config


def auto_ownership(rd: RunData) -> pl.DataFrame:
    """Returns DataFrame: HHVEH (0-4), freq, pct."""
    df = rd.hh.group_by("HHVEH").agg(pl.col("finalweight").sum().alias("freq"))
    total = df["freq"].sum()
    df = df.with_columns((pl.col("freq") / total * 100).alias("pct"))
    return df.sort("HHVEH")


def person_type(rd: RunData, config: Config) -> pl.DataFrame:
    """Returns DataFrame: ptype, ptype_name, freq, pct."""
    ptype_col = config.col_ptype
    if ptype_col not in rd.per.columns:
        return pl.DataFrame({"ptype": [], "ptype_name": [], "freq": [], "pct": []})
    df = (rd.per
          .group_by(ptype_col)
          .agg(pl.col("finalweight").sum().alias("freq")))
    total = df["freq"].sum()
    df = df.with_columns((pl.col("freq") / total * 100).alias("pct"))
    df = df.rename({ptype_col: "ptype"}).with_columns(
        pl.col("ptype").cast(pl.Utf8).map_elements(
            lambda v: config.ptype_label(v), return_dtype=pl.Utf8
        ).alias("ptype_name")
    )
    return df.sort("ptype")


def hh_size(rd: RunData) -> pl.DataFrame:
    """Returns DataFrame: HHSIZE (1-5+), freq, pct."""
    df = rd.hh.group_by("HHSIZE").agg(pl.col("finalweight").sum().alias("freq"))
    total = df["freq"].sum()
    df = df.with_columns((pl.col("freq") / total * 100).alias("pct"))
    return df.sort("HHSIZE")

