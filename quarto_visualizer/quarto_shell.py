"""Helpers for the Quarto shell and the early charted migration phases."""
from __future__ import annotations

from collections.abc import Sequence
from html import escape

import polars as pl
from shiny import ui

from quarto_visualizer.plots import run_color
from quarto_visualizer.summary_bundle import RunFrameList, SummaryBundle
from quarto_visualizer.tables import (
    concat_run_frames,
    filter_run_frames,
    normalize_display_frame,
    percent_difference_table,
    unique_values,
)

TOTAL_METRIC_LABELS = {
    "population": "Population",
    "households": "Households",
    "employment": "Employment",
    "tours": "Tours",
    "trips": "Trips",
    "stops": "Stops",
    "pmt": "PMT",
    "vmt": "VMT",
    "vehicle_trips": "Vehicle Trips",
}

OVERVIEW_KPI_METRICS = (
    ("population", "Population"),
    ("households", "Households"),
    ("vmt", "VMT"),
    ("tours", "Tours"),
    ("trips", "Trips"),
    ("stops", "Stops"),
)


def long_term_geo_choices(bundle: SummaryBundle) -> tuple[str, ...]:
    if bundle.long_term.tlfd:
        _, tlfd_map = bundle.long_term.tlfd[0]
        work_df = tlfd_map.get("work")
        if work_df is not None and len(work_df) > 0:
            choices = [c for c in work_df.columns if c not in ("distbin", "Total")]
            return tuple(["Total", *choices]) if choices else ("Total",)
    return ("Total",)


def tour_summary_ptype_choices(bundle: SummaryBundle) -> tuple[str, ...]:
    values = unique_values(bundle.tour_summary.dap, "ptype")
    return values if values else ("Total",)


def tour_summary_ptype_values(bundle: SummaryBundle) -> tuple[str, ...]:
    if bundle.tour_summary.dap:
        _, df = bundle.tour_summary.dap[0]
        if df is not None and len(df) > 0 and "ptype" in df.columns:
            values = sorted(
                str(v)
                for v in normalize_display_frame(df)["ptype"].drop_nulls().cast(pl.Utf8).unique().to_list()
            )
            return tuple(values) if values else ("Total",)
    return ("Total",)


def destination_purpose_choices(bundle: SummaryBundle) -> tuple[str, ...]:
    return bundle.destination.purposes or ("All NM",)


def tour_tod_purpose_choices(bundle: SummaryBundle) -> tuple[str, ...]:
    for _, df in bundle.tour_tod.profiles:
        if df is not None and len(df) > 0 and "purpose" in df.columns:
            values = sorted(
                str(v)
                for v in normalize_display_frame(df)["purpose"].drop_nulls().cast(pl.Utf8).unique().to_list()
            )
            ordered = ["Total", *[v for v in values if v != "Total"]]
            return tuple(ordered) if ordered else ("work",)
    return ("work",)


def tour_mode_purpose_choices(bundle: SummaryBundle) -> tuple[str, ...]:
    values = unique_values(bundle.tour_mode.detail, "purpose")
    if not values:
        return ("Total",)
    return tuple(["Total", *[v for v in values if v != "Total"]])


def stop_frequency_purpose_choices(bundle: SummaryBundle) -> tuple[str, ...]:
    for _, df in bundle.stop_freq.stop_frequency:
        if df is not None and len(df) > 0 and "primary_purpose" in df.columns:
            values = sorted(
                str(v)
                for v in normalize_display_frame(df)["primary_purpose"].drop_nulls().cast(pl.Utf8).unique().to_list()
            )
            return tuple(["Total", *values]) if values else ("Total",)
    return ("Total",)


def stop_timing_purpose_choices(bundle: SummaryBundle) -> tuple[str, ...]:
    for _, df in bundle.stop_timing.profiles:
        if df is not None and len(df) > 0 and "primary_purpose" in df.columns:
            values = tuple(
                v
                for v in sorted(
                    str(v)
                    for v in normalize_display_frame(df)["primary_purpose"].drop_nulls().cast(pl.Utf8).unique().to_list()
                )
                if v != "Total"
            )
            return values if values else ("work",)
    return ("work",)


def trip_mode_purpose_choices(bundle: SummaryBundle) -> tuple[str, ...]:
    for _, df in bundle.trip_mode.profiles:
        if df is not None and len(df) > 0:
            display_df = normalize_display_frame(df)
            if "primary_purpose" in display_df.columns:
                values = sorted(
                    str(v)
                    for v in display_df["primary_purpose"].drop_nulls().cast(pl.Utf8).unique().to_list()
                )
                return tuple(["Total", *[v for v in values if v != "Total"]]) if values else ("work",)
            return ("work",)
    return ("work",)


def trip_mode_tour_mode_choices(bundle: SummaryBundle) -> tuple[str, ...]:
    for _, df in bundle.trip_mode.profiles:
        if df is not None and len(df) > 0:
            display_df = normalize_display_frame(df)
            if "tour_mode" in display_df.columns:
                values = sorted(
                    str(v)
                    for v in display_df["tour_mode"].drop_nulls().cast(pl.Utf8).unique().to_list()
                )
                return tuple(["All", *values]) if values else ("All",)
            return ("All",)
    return ("All",)


def overview_totals_table(bundle: SummaryBundle) -> pl.DataFrame:
    return concat_run_frames(bundle.overview.totals)


def overview_kpi_values(bundle: SummaryBundle, metric: str) -> tuple[tuple[str, float], ...]:
    values: list[tuple[str, float]] = []
    for run_label, df in bundle.overview.totals:
        value = 0.0
        if df is not None and len(df) > 0 and metric in df.columns:
            value = float(df[metric][0])
        values.append((run_label, value))
    return tuple(values)


def overview_kpi_cards(bundle: SummaryBundle, run_colors: Sequence[str] | None = None):
    cards = [
        _overview_kpi_card(label, overview_kpi_values(bundle, metric), run_colors=run_colors)
        for metric, label in OVERVIEW_KPI_METRICS
    ]
    return ui.div(
        *cards,
        style=(
            "display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));"
            "gap:16px;margin:0 0 12px 0;"
        ),
    )


def overview_percent_diff_table(bundle: SummaryBundle) -> pl.DataFrame:
    return percent_difference_table(
        bundle.overview.totals,
        metrics=tuple(TOTAL_METRIC_LABELS.keys()),
        labels=TOTAL_METRIC_LABELS,
    )


def overview_person_type_frames(bundle: SummaryBundle) -> RunFrameList:
    return bundle.overview.person_type


def overview_hh_size_frames(bundle: SummaryBundle) -> RunFrameList:
    return bundle.overview.hh_size


def _overview_kpi_card(
    title: str,
    values: Sequence[tuple[str, float]],
    *,
    run_colors: Sequence[str] | None = None,
):
    max_value = max((value for _, value in values), default=0.0) or 1.0
    items = []
    for idx, (run_label, value) in enumerate(values):
        color = run_color(idx, run_colors)
        mini_width = max(0, min(100, int(round((float(value) / max_value) * 100))))
        items.append(
            ui.HTML(
                "<div style='padding:10px 12px;border-left:4px solid {color};margin:6px 0;"
                "border-radius:6px;background:rgba(127,127,127,0.06)'>"
                "<div style='font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.04em'>"
                "{run_label}</div>"
                "<div style='font-size:22px;font-weight:700;color:{color};line-height:1.1'>{value}</div>"
                "<div style='height:5px;border-radius:3px;background:rgba(0,0,0,0.08);margin-top:6px;'>"
                "<div style='width:{mini_width}%;height:5px;border-radius:3px;background:{color};'></div>"
                "</div></div>".format(
                    color=escape(color),
                    run_label=escape(str(run_label)),
                    value=f"{value:,.0f}",
                    mini_width=mini_width,
                )
            )
        )
    return ui.div(
        ui.h4(title, style="margin:0 0 8px 0;font-size:1rem;font-weight:600;"),
        *items,
        style=(
            "border:1px solid rgba(0,0,0,0.08);border-radius:10px;padding:14px;"
            "background:#fff;box-shadow:0 1px 2px rgba(0,0,0,0.04);"
        ),
    )


def long_term_auto_frames(bundle: SummaryBundle) -> RunFrameList:
    return bundle.long_term.auto_ownership


def long_term_tlfd_frames(bundle: SummaryBundle, geography: str, series: str) -> RunFrameList:
    rows: list[tuple[str, pl.DataFrame]] = []
    col = geography if geography != "Total" else "Total"
    for label, tlfd_map in bundle.long_term.tlfd:
        df = tlfd_map.get(series, pl.DataFrame())
        if len(df) == 0:
            rows.append((label, pl.DataFrame()))
            continue
        if col not in df.columns:
            rows.append((label, pl.DataFrame()))
            continue
        rows.append((label, df.select(["distbin", col]).rename({col: "freq"})))
    return tuple(rows)


def long_term_telecommute_frames(bundle: SummaryBundle) -> RunFrameList:
    return bundle.long_term.telecommute


def long_term_wfh_frames(bundle: SummaryBundle) -> RunFrameList:
    rows: list[tuple[str, pl.DataFrame]] = []
    for label, df in bundle.long_term.wfh:
        if df is None or len(df) == 0:
            rows.append((label, pl.DataFrame()))
            continue
        if "Geography" not in df.columns or "WFH" not in df.columns:
            rows.append((label, pl.DataFrame()))
            continue
        rows.append((label, df.select(["Geography", "WFH"])))
    return tuple(rows)


def long_term_geo_flow_frames(bundle: SummaryBundle) -> RunFrameList:
    return tuple((label, normalize_display_frame(df)) for label, df in bundle.long_term.geo_flows)


def long_term_mandatory_length_frames(bundle: SummaryBundle) -> RunFrameList:
    return tuple((label, normalize_display_frame(df)) for label, df in bundle.long_term.mandatory_tour_lengths)


def run_frame_tabs(
    frames: RunFrameList,
    *,
    title: str | None = None,
    empty_message: str = "No data available.",
    float_decimals: int = 2,
):
    panels = []
    for label, df in frames:
        panels.append(
            ui.nav_panel(
                str(label),
                ui.HTML(_frame_table_html(df, float_decimals=float_decimals))
                if df is not None and len(df) > 0
                else ui.markdown(empty_message),
            )
        )

    content = ui.navset_tab(*panels) if panels else ui.markdown(empty_message)
    if title:
        return ui.div(ui.markdown(f"### {title}"), content)
    return content


def tour_summary_dap_frames(bundle: SummaryBundle, ptype: str) -> RunFrameList:
    base = pl.DataFrame({"DAP": ["M", "N", "H"]})
    result: list[tuple[str, pl.DataFrame]] = []
    for label, df in bundle.tour_summary.dap:
        if df is None or len(df) == 0:
            result.append((label, base.with_columns(pl.lit(0.0).alias("freq"))))
            continue
        sub = (
            normalize_display_frame(df)
            .filter(pl.col("ptype").cast(pl.Utf8) == str(ptype))
            .select([pl.col("DAP").cast(pl.Utf8).alias("DAP"), "freq"])
        )
        result.append((label, base.join(sub, on="DAP", how="left").with_columns(pl.col("freq").fill_null(0.0))))
    return tuple(result)


def tour_summary_mtf_frames(bundle: SummaryBundle, ptype: str) -> RunFrameList:
    base = pl.DataFrame(
        {
            "MTF": [1, 2, 3, 4, 5],
            "MTF_label": ["work1", "work2", "school1", "school2", "work and school"],
        }
    )
    result: list[tuple[str, pl.DataFrame]] = []
    for label, df in bundle.tour_summary.mandatory_tour_frequency:
        if df is None or len(df) == 0:
            result.append((label, base.select(["MTF_label"]).with_columns(pl.lit(0.0).alias("freq"))))
            continue
        sub = (
            normalize_display_frame(df)
            .filter(pl.col("ptype").cast(pl.Utf8) == str(ptype))
            .with_columns(pl.col("MTF").cast(pl.Int64, strict=False).alias("MTF"))
            .select(["MTF", "freq"])
        )
        result.append(
            (
                label,
                base.join(sub, on="MTF", how="left")
                .with_columns(pl.col("freq").fill_null(0.0))
                .select(["MTF_label", "freq"]),
            )
        )
    return tuple(result)


def tour_summary_indiv_nm_frames(bundle: SummaryBundle, ptype: str) -> RunFrameList:
    base = pl.DataFrame({"nmtours": ["0", "1", "2", "3pl"]})
    result: list[tuple[str, pl.DataFrame]] = []
    for label, df in bundle.tour_summary.individual_nm:
        if df is None or len(df) == 0:
            result.append((label, base.with_columns(pl.lit(0.0).alias("freq"))))
            continue
        sub = (
            normalize_display_frame(df)
            .filter(pl.col("ptype").cast(pl.Utf8) == str(ptype))
            .with_columns(pl.col("nmtours").cast(pl.Utf8).alias("nmtours"))
            .select(["nmtours", "freq"])
        )
        result.append((label, base.join(sub, on="nmtours", how="left").with_columns(pl.col("freq").fill_null(0.0))))
    return tuple(result)


def joint_tour_frequency_frames(bundle: SummaryBundle) -> RunFrameList:
    return bundle.joint_tours.joint_tour_frequency


def joint_tour_composition_frames(bundle: SummaryBundle) -> RunFrameList:
    base = pl.DataFrame({"tour_composition": ["adults", "mixed", "children"]})
    result: list[tuple[str, pl.DataFrame]] = []
    for label, df in bundle.joint_tours.composition:
        if df is None or len(df) == 0:
            result.append((label, base.with_columns(pl.lit(0.0).alias("freq"))))
            continue
        sub = (
            normalize_display_frame(df)
            .with_columns(pl.col("tour_composition").cast(pl.Utf8).str.to_lowercase().alias("tour_composition"))
            .select(["tour_composition", "freq"])
        )
        result.append((label, base.join(sub, on="tour_composition", how="left").with_columns(pl.col("freq").fill_null(0.0))))
    return tuple(result)


def joint_tour_party_size_frames(bundle: SummaryBundle) -> RunFrameList:
    base = pl.DataFrame({"NUMBER_HH": ["2", "3", "4", "5"]})
    result: list[tuple[str, pl.DataFrame]] = []
    for label, df in bundle.joint_tours.party_size:
        if df is None or len(df) == 0:
            result.append((label, base.with_columns(pl.lit(0.0).alias("freq"))))
            continue
        sub = (
            normalize_display_frame(df)
            .with_columns(
                pl.col("NUMBER_HH")
                .map_elements(_normalize_hhsize_text, return_dtype=pl.Utf8)
                .alias("NUMBER_HH")
            )
            .select(["NUMBER_HH", "freq"])
        )
        result.append((label, base.join(sub, on="NUMBER_HH", how="left").with_columns(pl.col("freq").fill_null(0.0))))
    return tuple(result)


def joint_tours_hhsize_frames(bundle: SummaryBundle, hhsize: str) -> RunFrameList:
    result: list[tuple[str, pl.DataFrame]] = []
    base = pl.DataFrame({"jointTours": ["0", "1", "2+"]})
    for label, df in bundle.joint_tours.household_size:
        if df is None or len(df) == 0:
            result.append((label, base.with_columns(pl.lit(0.0).alias("freq"))))
            continue
        if hhsize == "Total":
            agg = (
                base.join(df.group_by("jointTours").agg(pl.col("freq").sum().alias("freq")), on="jointTours", how="left")
                .with_columns(pl.col("freq").fill_null(0.0))
            )
            total = float(agg["freq"].sum()) if len(agg) > 0 else 0.0
            if total > 0:
                agg = agg.with_columns((pl.col("freq") / total * 100).alias("freq"))
        else:
            sub = (
                normalize_display_frame(df)
                .with_columns(
                    pl.col("hhsize").map_elements(_normalize_hhsize_text, return_dtype=pl.Utf8).alias("hhsize")
                )
                .filter(pl.col("hhsize") == hhsize)
            )
            agg = (
                base.join(sub.select(["jointTours", "freq"]), on="jointTours", how="left")
                .with_columns(pl.col("freq").fill_null(0.0))
            )
        result.append((label, agg))
    return tuple(result)


def destination_frames(bundle: SummaryBundle, purpose: str) -> RunFrameList:
    return bundle.destination.distance_by_purpose.get(purpose, tuple())


def destination_average_table(bundle: SummaryBundle) -> pl.DataFrame:
    return bundle.destination.average_distance_display


def tour_tod_frames(bundle: SummaryBundle, purpose: str, series: str) -> RunFrameList:
    maxbin = _max_timebin(bundle.tour_tod.profiles)
    val_col = {"departure": "freq_dep", "arrival": "freq_arr", "duration": "freq_dur"}[series]
    result: list[tuple[str, pl.DataFrame]] = []
    for label, df in filter_run_frames(bundle.tour_tod.profiles, "purpose", purpose):
        if df is None or len(df) == 0:
            result.append((label, pl.DataFrame()))
            continue
        if series == "duration":
            result.append(
                (
                    label,
                    df.select(["timebin", val_col])
                    .rename({val_col: "freq"})
                    .with_columns(
                        pl.col("timebin").map_elements(
                            lambda tb: _duration_hours(int(tb), maxbin),
                            return_dtype=pl.Float64,
                        ).alias("duration_hours")
                    )
                    .select(["duration_hours", "freq"]),
                )
            )
        else:
            result.append(
                (
                    label,
                    df.select(["timebin", val_col])
                    .rename({val_col: "freq"})
                    .with_columns(
                        pl.col("timebin").map_elements(
                            lambda tb: _time_label(int(tb), maxbin),
                            return_dtype=pl.Utf8,
                        ).alias("clock_time")
                    )
                    .select(["clock_time", "freq"]),
                )
            )
    return tuple(result)


def tour_mode_detail_frames(bundle: SummaryBundle, purpose: str, series: str = "freq_all") -> RunFrameList:
    result: list[tuple[str, pl.DataFrame]] = []
    for label, df in filter_run_frames(bundle.tour_mode.detail, "purpose", purpose):
        if df is None or len(df) == 0 or series not in df.columns:
            result.append((label, pl.DataFrame()))
            continue
        result.append((label, df.select(["tour_mode", series]).rename({series: "freq"})))
    return tuple(result)


def tour_mode_grouped_frames(bundle: SummaryBundle, series: str = "freq_all") -> RunFrameList:
    result: list[tuple[str, pl.DataFrame]] = []
    for label, df in bundle.tour_mode.grouped:
        if df is None or len(df) == 0 or series not in df.columns:
            result.append((label, pl.DataFrame()))
            continue
        result.append((label, normalize_display_frame(df).select(["mode_group", series]).rename({series: "freq"})))
    return tuple(result)


def stop_frequency_frames(bundle: SummaryBundle, purpose: str, series: str) -> RunFrameList:
    result: list[tuple[str, pl.DataFrame]] = []
    for label, df in bundle.stop_freq.stop_frequency:
        if df is None or len(df) == 0:
            result.append((label, pl.DataFrame()))
            continue
        sub = df if purpose == "Total" else df.filter(pl.col("primary_purpose").cast(pl.Utf8) == purpose)
        if series == "stop_purpose":
            raise ValueError("Use stop_purpose_frames() for stop-purpose charts.")
        stop_col = {"outbound": "ob_stops", "inbound": "ib_stops", "total": "tot_stops"}[series]
        if len(sub) == 0:
            result.append((label, pl.DataFrame()))
            continue
        result.append(
            (
                label,
                sub.group_by(stop_col)
                .agg(pl.col("freq").sum())
                .sort(stop_col)
                .with_columns(pl.col(stop_col).cast(pl.Utf8).alias("stops"))
                .select(["stops", "freq"]),
            )
        )
    return tuple(result)


def stop_purpose_frames(bundle: SummaryBundle, purpose: str) -> RunFrameList:
    result: list[tuple[str, pl.DataFrame]] = []
    for label, df in bundle.stop_freq.stop_purpose:
        if df is None or len(df) == 0:
            result.append((label, pl.DataFrame()))
            continue
        if purpose == "Total":
            sub = df.group_by("purpose").agg(pl.col("freq").sum()).sort("purpose")
        else:
            sub = df.filter(pl.col("primary_purpose").cast(pl.Utf8) == purpose).select(["purpose", "freq"])
        result.append((label, sub))
    return tuple(result)


def stop_location_all_frames(bundle: SummaryBundle) -> RunFrameList:
    result: list[tuple[str, pl.DataFrame]] = []
    for label, df in bundle.stop_location.profiles:
        if df is None or len(df) == 0:
            result.append((label, pl.DataFrame()))
            continue
        result.append((label, df.group_by("distbin").agg(pl.col("freq").sum()).sort("distbin")))
    return tuple(result)


def stop_location_purpose_choices(bundle: SummaryBundle) -> tuple[str, ...]:
    for _, df in bundle.stop_location.profiles:
        if df is not None and len(df) > 0 and "primary_purpose" in df.columns:
            values = sorted(
                str(v)
                for v in normalize_display_frame(df)["primary_purpose"].drop_nulls().cast(pl.Utf8).unique().to_list()
            )
            return tuple(values)
    return tuple()


def stop_location_purpose_frames(bundle: SummaryBundle, purpose: str) -> RunFrameList:
    result: list[tuple[str, pl.DataFrame]] = []
    for label, df in bundle.stop_location.profiles:
        if df is None or len(df) == 0:
            result.append((label, pl.DataFrame()))
            continue
        sub = (
            normalize_display_frame(df)
            .filter(pl.col("primary_purpose").cast(pl.Utf8) == str(purpose))
            .select(["distbin", "freq"])
        )
        result.append((label, sub))
    return tuple(result)


def stop_timing_frames(bundle: SummaryBundle, purpose: str, series: str = "trip") -> RunFrameList:
    maxbin = _max_timebin(bundle.stop_timing.profiles)
    val_col = {"trip": "freq_trip_dep", "stop": "freq_stop_dep"}[series]
    result: list[tuple[str, pl.DataFrame]] = []
    for label, df in filter_run_frames(bundle.stop_timing.profiles, "primary_purpose", purpose):
        if df is None or len(df) == 0 or val_col not in df.columns:
            result.append((label, pl.DataFrame()))
            continue
        result.append(
            (
                label,
                df.select(["timebin", val_col])
                .rename({val_col: "freq"})
                .with_columns(
                    pl.col("timebin").map_elements(
                        lambda tb: _time_label(int(tb), maxbin),
                        return_dtype=pl.Utf8,
                    ).alias("clock_time")
                )
                .select(["clock_time", "freq"]),
            )
        )
    return tuple(result)


def trip_mode_frames(bundle: SummaryBundle, purpose: str, tour_mode: str) -> RunFrameList:
    result: list[tuple[str, pl.DataFrame]] = []
    for label, df in bundle.trip_mode.profiles:
        if df is None or len(df) == 0:
            result.append((label, pl.DataFrame()))
            continue
        sub = df
        if purpose != "Total" and "primary_purpose" in sub.columns:
            sub = sub.filter(pl.col("primary_purpose").cast(pl.Utf8) == purpose)
        if tour_mode != "All" and "tour_mode" in sub.columns:
            sub = sub.filter(pl.col("tour_mode").cast(pl.Utf8) == tour_mode)
        if len(sub) == 0:
            result.append((label, pl.DataFrame()))
            continue
        result.append((label, sub.group_by("trip_mode").agg(pl.col("freq").sum()).sort("trip_mode")))
    return tuple(result)


def _max_timebin(frames: RunFrameList) -> int:
    for _, df in frames:
        if df is not None and len(df) > 0 and "timebin" in df.columns:
            return int(df["timebin"].max())
    return 48


def _time_label(timebin: int, maxbin: int) -> str:
    step = 30 if maxbin == 48 else 60
    total_minutes = ((int(timebin) - 1) * step + 3 * 60) % (24 * 60)
    hh = total_minutes // 60
    mm = total_minutes % 60
    return f"{hh:02d}:{mm:02d}"


def _duration_hours(timebin: int, maxbin: int) -> float:
    step = 0.5 if maxbin == 48 else 1.0
    return round(float(timebin) * step, 2)


def _normalize_hhsize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    try:
        numeric = float(text)
        if numeric.is_integer():
            return str(int(numeric))
    except ValueError:
        pass
    return text


def _frame_table_html(df: pl.DataFrame, *, float_decimals: int = 2) -> str:
    display_df = normalize_display_frame(df)
    header = "".join(
        f"<th style='text-align:left;padding:8px 10px;border-bottom:1px solid #d1d5db;"
        f"background:#f8fafc;font-weight:600'>{escape(str(col))}</th>"
        for col in display_df.columns
    )
    body_rows = []
    for row in display_df.iter_rows(named=True):
        cells = "".join(
            f"<td style='padding:8px 10px;border-bottom:1px solid #e5e7eb'>{_format_cell(value, float_decimals=float_decimals)}</td>"
            for value in row.values()
        )
        body_rows.append(f"<tr>{cells}</tr>")
    body = "".join(body_rows) or (
        f"<tr><td colspan='{len(display_df.columns) or 1}' style='padding:8px 10px'>No data available.</td></tr>"
    )
    return (
        "<div style='overflow:auto'>"
        "<table style='width:100%;border-collapse:collapse;font-size:13px'>"
        f"<thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _format_cell(value: object, *, float_decimals: int = 2) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if value.is_integer():
            return f"{value:,.0f}"
        return f"{value:,.{float_decimals}f}"
    return escape(str(value))
