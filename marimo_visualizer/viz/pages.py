"""Page renderers for the marimo ActivitySim visualizer."""

from __future__ import annotations

from typing import Any, Sequence

import polars as pl

from .charts import bar_chart, density_chart, kpi_card_html
from .filters import (
    geography_options,
    hh_size_options,
    person_type_label_map,
    person_type_options,
    purpose_options_from_tours,
    purpose_options_from_trips,
    trip_tour_mode_options,
)
from .models import Config, RunData
from .summaries import demographics, mandatory, stops, totals, tour_mode, tour_tod, tours, trips
from .tables import (
    kpi_format_mapping,
    make_run_tables,
    make_table,
    percent_difference_format_mapping,
    percent_difference_table,
)

Runs = Sequence[tuple[str, RunData]]


def render_page(
    page_name: str,
    runs: Runs,
    config: Config,
    as_percent: bool,
    run_colors: Sequence[str],
    mo: Any,
    controls: dict[str, Any] | None = None,
    control_values: dict[str, Any] | None = None,
):
    """Dispatch to the renderer for a dashboard page."""
    renderer = PAGE_RENDERERS.get(page_name, render_unknown_page)
    return renderer(
        runs=runs,
        config=config,
        as_percent=as_percent,
        run_colors=run_colors,
        mo=mo,
        controls=controls,
        control_values=control_values,
    )


def build_page_controls(page_name: str, runs: Runs, config: Config, mo: Any) -> dict[str, Any]:
    """Build widgets for the active page in a dedicated marimo cell."""
    builder = PAGE_CONTROL_BUILDERS.get(page_name)
    if builder is None:
        return mo.ui.dictionary({})
    return mo.ui.dictionary(builder(runs=runs, config=config, mo=mo), label=f"{page_name} controls")


def render_unknown_page(
    runs: Runs,
    config: Config,
    as_percent: bool,
    run_colors: Sequence[str],
    mo: Any,
    controls: dict[str, Any] | None = None,
    control_values: dict[str, Any] | None = None,
):
    del runs, config, as_percent, run_colors, controls, control_values
    return _empty_page(mo, "Unknown Page", "The requested page renderer is not defined.")


def _plot(mo: Any, fig: Any):
    return mo.ui.plotly(fig, config={"displaylogo": False, "responsive": True})


def _dropdown_widget(mo: Any, label: str, options: Sequence[str]) -> Any:
    option_list = list(options)
    default = option_list[0] if option_list else None
    return mo.ui.dropdown(option_list, value=default, label=label)


def _control_value(control_values: dict[str, Any] | None, key: str, default: str) -> str:
    if not control_values:
        return default
    value = control_values.get(key)
    return default if value in (None, "") else str(value)


def _control_widget(controls: dict[str, Any] | None, key: str) -> Any | None:
    if not controls:
        return None
    try:
        return controls[key]
    except Exception:
        return controls.get(key)


def _control_row(mo: Any, controls: list[Any]):
    return mo.hstack(controls, widths="equal")


def _maybe_control_row(mo: Any, controls: list[Any]) -> Any:
    widgets = [control for control in controls if control is not None]
    if not widgets:
        return mo.md("")
    return _control_row(mo, widgets)


def _empty_page(mo: Any, title: str, message: str):
    return mo.vstack([mo.md(f"## {title}"), mo.md(message)], gap=1.0)


def _has_any_rows(data_list: Sequence[tuple[str, pl.DataFrame]]) -> bool:
    return any(df is not None and len(df) > 0 for _, df in data_list)


def _summary_value_options(
    data_list: list[tuple[str, pl.DataFrame]],
    column: str,
    default: list[str],
    include_total: bool = False,
    include_all: bool = False,
) -> list[str]:
    values: set[str] = set()
    for _, df in data_list:
        if column in df.columns and len(df) > 0:
            values.update(str(value) for value in df[column].drop_nulls().to_list())
    if not values:
        return default
    ordered = sorted(values)
    if include_total and "Total" in ordered:
        ordered = ["Total"] + [value for value in ordered if value != "Total"]
    elif include_total:
        ordered = ["Total"] + ordered
    if include_all and "All" in ordered:
        ordered = ["All"] + [value for value in ordered if value != "All"]
    elif include_all:
        ordered = ["All"] + ordered
    return ordered


def _filter_value(df: pl.DataFrame, column: str, value: str) -> pl.DataFrame:
    if len(df) == 0 or column not in df.columns or value in {"Total", "All", "All NM"}:
        return df
    return df.filter(pl.col(column).cast(pl.Utf8) == str(value))


def _sort_modes(df: pl.DataFrame, column: str, config: Config) -> pl.DataFrame:
    if len(df) == 0 or column not in df.columns:
        return df
    normalized = df.with_columns(pl.col(column).cast(pl.Utf8).alias(column))
    ordered = config.ordered_modes([str(value) for value in normalized[column].to_list()])
    order_df = pl.DataFrame({column: ordered, "_order": list(range(len(ordered)))})
    return normalized.join(order_df, on=column, how="left").sort("_order").drop("_order")


def _max_timebin(data_list: list[tuple[str, pl.DataFrame]]) -> int:
    maxbin = 48
    for _, df in data_list:
        if len(df) > 0 and "timebin" in df.columns:
            try:
                maxbin = max(maxbin, int(df["timebin"].max()))
            except Exception:
                continue
    return 24 if maxbin <= 24 else 48


def _time_label(timebin: int, maxbin: int) -> str:
    step = 30 if maxbin == 48 else 60
    total_minutes = ((int(timebin) - 1) * step + 3 * 60) % (24 * 60)
    hour = total_minutes // 60
    minute = total_minutes % 60
    return f"{hour:02d}:{minute:02d}"


def _duration_hours(timebin: int, maxbin: int) -> float:
    step = 0.5 if maxbin == 48 else 1.0
    return round(float(timebin) * step, 2)


def render_overview(
    runs: Runs,
    config: Config,
    as_percent: bool,
    run_colors: Sequence[str],
    mo: Any,
    controls: dict[str, Any] | None = None,
    control_values: dict[str, Any] | None = None,
):
    del controls, control_values
    totals_list = [(label, totals.system_totals(rd, config)) for label, rd in runs]
    pertype_list = [(label, demographics.person_type(rd, config)) for label, rd in runs]
    hhsize_list = [(label, demographics.hh_size(rd)) for label, rd in runs]

    if not _has_any_rows(totals_list) and not _has_any_rows(pertype_list) and not _has_any_rows(hhsize_list):
        return _empty_page(mo, "Overview", "No overview summary data is available for the selected runs.")

    kpi_cards = [
        _kpi_card(mo, "Population", totals_list, "population", run_colors, icon="P"),
        _kpi_card(mo, "Households", totals_list, "households", run_colors, icon="HH"),
        _kpi_card(mo, "VMT", totals_list, "vmt", run_colors, icon="VMT"),
        _kpi_card(mo, "Tours", totals_list, "tours", run_colors, icon="T"),
        _kpi_card(mo, "Trips", totals_list, "trips", run_colors, icon="TR"),
        _kpi_card(mo, "Stops", totals_list, "stops", run_colors, icon="S"),
    ]

    pct_df = percent_difference_table(
        totals_list,
        metrics=[
            ("population", "Population"),
            ("households", "Households"),
            ("employment", "Employment"),
            ("tours", "Tours"),
            ("trips", "Trips"),
            ("stops", "Stops"),
            ("pmt", "PMT"),
            ("vmt", "VMT"),
            ("vehicle_trips", "Vehicle Trips"),
        ],
    )
    ptype_fig = bar_chart(
        [(label, df.with_columns(pl.col("ptype_name").cast(pl.Utf8))) for label, df in pertype_list],
        x_col="ptype_name",
        y_col="freq",
        title="Person Type Distribution",
        xaxis_title="Person Type",
        yaxis_title="Persons",
        as_percent=as_percent,
        run_colors=run_colors,
        pct_col="pct",
    )
    hhsize_fig = bar_chart(
        [(label, df.with_columns(pl.col("HHSIZE").cast(pl.Utf8))) for label, df in hhsize_list],
        x_col="HHSIZE",
        y_col="freq",
        title="Household Size Distribution",
        xaxis_title="HH Size",
        yaxis_title="Households",
        as_percent=as_percent,
        run_colors=run_colors,
        pct_col="pct",
    )

    return mo.vstack(
        [
            mo.md("## Overview"),
            mo.md(f"Base run for percent difference table: `{runs[0][0]}`"),
            mo.hstack(kpi_cards[:3], widths="equal"),
            mo.hstack(kpi_cards[3:], widths="equal"),
            mo.md("### Percent Difference vs Base Run"),
            make_table(
                mo,
                pct_df,
                empty_text="No percent-difference table is available.",
                column_order=["Metric", *[label for label, _ in totals_list]],
                format_mapping=percent_difference_format_mapping(pct_df),
            ),
            mo.md("### Demographic Distributions"),
            mo.hstack([_plot(mo, ptype_fig), _plot(mo, hhsize_fig)], widths="equal"),
        ],
        gap=1.0,
    )


def render_long_term(
    runs: Runs,
    config: Config,
    as_percent: bool,
    run_colors: Sequence[str],
    mo: Any,
    controls: dict[str, Any] | None = None,
    control_values: dict[str, Any] | None = None,
):
    auto_own_list = [
        (label, demographics.auto_ownership(rd).with_columns(pl.col("HHVEH").cast(pl.Utf8)))
        for label, rd in runs
    ]
    tlfd_list = [(label, mandatory.tlfd(rd, config)) for label, rd in runs]
    wfh_list = [(label, mandatory.wfh(rd, config)) for label, rd in runs]
    tc_list = [(label, mandatory.telecommute(rd)) for label, rd in runs]
    mand_len_list = [(label, mandatory.mand_tour_lengths(rd, config)) for label, rd in runs]
    flow_list = [(label, mandatory.geo_flows(rd, config)) for label, rd in runs]

    geo_opts = _tlfd_geography_options(tlfd_list) if config.geography_enabled else ["Total"]
    geo_sel = _control_widget(controls, "geography")
    selected_geo = _control_value(control_values, "geography", geo_opts[0])
    tlfd_col = "Total" if selected_geo == "All" else selected_geo

    auto_fig = bar_chart(
        auto_own_list,
        x_col="HHVEH",
        y_col="freq",
        title="Auto Ownership",
        xaxis_title="Vehicles",
        yaxis_title="Households",
        as_percent=as_percent,
        run_colors=run_colors,
        pct_col="pct",
    )
    tc_fig = bar_chart(
        tc_list,
        x_col="telecommute_frequency",
        y_col="freq",
        title="Telecommute Frequency",
        xaxis_title="Frequency",
        yaxis_title="Workers",
        as_percent=as_percent,
        run_colors=run_colors,
    )
    wfh_fig = bar_chart(
        [(label, df.select(["Geography", "WFH"])) for label, df in wfh_list if len(df) > 0],
        x_col="Geography",
        y_col="WFH",
        title="Work From Home by Geography",
        xaxis_title="Geography",
        yaxis_title="Workers",
        as_percent=as_percent,
        run_colors=run_colors,
    )
    work_fig = density_chart(
        [(label, _tlfd_frame(mapping.get("work"), tlfd_col)) for label, mapping in tlfd_list],
        x_col="distbin",
        y_col="freq",
        title=f"Work TLFD - {selected_geo}",
        xaxis_title="Distance (miles)",
        as_percent=as_percent,
        run_colors=run_colors,
        normalize=True,
    )
    univ_fig = density_chart(
        [(label, _tlfd_frame(mapping.get("univ"), tlfd_col)) for label, mapping in tlfd_list],
        x_col="distbin",
        y_col="freq",
        title=f"University TLFD - {selected_geo}",
        xaxis_title="Distance (miles)",
        as_percent=as_percent,
        run_colors=run_colors,
        normalize=True,
    )
    schl_fig = density_chart(
        [(label, _tlfd_frame(mapping.get("schl"), tlfd_col)) for label, mapping in tlfd_list],
        x_col="distbin",
        y_col="freq",
        title=f"School TLFD - {selected_geo}",
        xaxis_title="Distance (miles)",
        as_percent=as_percent,
        run_colors=run_colors,
        normalize=True,
    )

    return mo.vstack(
        [
            mo.md("## Long-Term Choices"),
            _maybe_control_row(mo, [geo_sel]) if config.geography_enabled else mo.md("Geography controls are disabled in config."),
            _plot(mo, auto_fig),
            mo.md("### Trip Length Frequency Distributions"),
            mo.hstack([_plot(mo, work_fig), _plot(mo, univ_fig), _plot(mo, schl_fig)], widths="equal"),
            mo.hstack([_plot(mo, tc_fig), _plot(mo, wfh_fig)], widths="equal"),
            mo.md("### Home-Work Geography Flows"),
            make_run_tables(
                mo,
                flow_list,
                empty_text="No geography flow table is available.",
                format_mapping=lambda df: kpi_format_mapping(df, digits=0),
            ),
            mo.md("### Average Mandatory Tour Lengths (miles)"),
            make_run_tables(
                mo,
                mand_len_list,
                empty_text="No mandatory tour length table is available.",
                format_mapping=lambda df: kpi_format_mapping(df, digits=2),
            ),
        ],
        gap=1.0,
    )


def render_tour_summary(
    runs: Runs,
    config: Config,
    as_percent: bool,
    run_colors: Sequence[str],
    mo: Any,
    controls: dict[str, Any] | None = None,
    control_values: dict[str, Any] | None = None,
):
    dap_list = [(label, tours.dap_summary(rd, config)) for label, rd in runs]
    mtf_list = [(label, tours.mandatory_tour_freq(rd, config)) for label, rd in runs]
    inm_list = [(label, tours.indiv_nm_summary(rd, config)) for label, rd in runs]

    ptype_opts = person_type_options(runs, config, include_total=True)
    ptype_map = person_type_label_map(runs, config, include_total=True)
    ptype_sel = _control_widget(controls, "ptype")
    selected_label = _control_value(control_values, "ptype", ptype_opts[0])
    selected_ptype = ptype_map.get(selected_label, selected_label)

    dap_fig = bar_chart(
        [(label, _ordered_dap(df, selected_ptype)) for label, df in dap_list],
        x_col="DAP",
        y_col="freq",
        title=f"Daily Activity Pattern - {selected_label}",
        xaxis_title="Pattern",
        yaxis_title="Persons",
        as_percent=as_percent,
        run_colors=run_colors,
    )
    mtf_fig = bar_chart(
        [(label, _ordered_mtf(df, selected_ptype)) for label, df in mtf_list],
        x_col="MTF_label",
        y_col="freq",
        title=f"Mandatory Tour Frequency - {selected_label}",
        xaxis_title="Alternative",
        yaxis_title="Persons",
        as_percent=as_percent,
        run_colors=run_colors,
    )
    inm_fig = bar_chart(
        [(label, _ordered_inm(df, selected_ptype)) for label, df in inm_list],
        x_col="nmtours",
        y_col="freq",
        title=f"Individual NM Tours - {selected_label}",
        xaxis_title="Number of Tours",
        yaxis_title="Persons",
        as_percent=as_percent,
        run_colors=run_colors,
    )

    return mo.vstack(
        [
            mo.md("## Tour Summary"),
            _maybe_control_row(mo, [ptype_sel]),
            mo.hstack([_plot(mo, dap_fig), _plot(mo, mtf_fig)], widths="equal"),
            _plot(mo, inm_fig),
        ],
        gap=1.0,
    )


def render_joint_tours(
    runs: Runs,
    config: Config,
    as_percent: bool,
    run_colors: Sequence[str],
    mo: Any,
    controls: dict[str, Any] | None = None,
    control_values: dict[str, Any] | None = None,
):
    del config
    jtf_list = [(label, tours.joint_tour_freq(rd)) for label, rd in runs]
    comp_list = [(label, _ordered_joint_comp(tours.joint_composition(rd))) for label, rd in runs]
    party_list = [
        (label, tours.joint_party_size(rd).with_columns(pl.col("NUMBER_HH").cast(pl.Utf8)))
        for label, rd in runs
    ]
    hhsize_list = [(label, tours.joint_tours_hhsize(rd)) for label, rd in runs]

    hhsize_opts = _joint_hhsize_options(hhsize_list)
    hhsize_sel = _control_widget(controls, "hhsize")
    selected_hhsize = _control_value(control_values, "hhsize", hhsize_opts[0])

    jtf_fig = bar_chart(
        jtf_list,
        x_col="alt_name",
        y_col="freq",
        title="Joint Tour Frequency",
        xaxis_title="Alternative",
        yaxis_title="Households",
        as_percent=as_percent,
        run_colors=run_colors,
        height=450,
    )
    comp_fig = bar_chart(
        comp_list,
        x_col="tour_composition",
        y_col="freq",
        title="Joint Tour Composition",
        xaxis_title="Composition",
        yaxis_title="Tours",
        as_percent=as_percent,
        run_colors=run_colors,
    )
    party_fig = bar_chart(
        party_list,
        x_col="NUMBER_HH",
        y_col="freq",
        title="Joint Tour Party Size",
        xaxis_title="Party Size",
        yaxis_title="Tours",
        as_percent=as_percent,
        run_colors=run_colors,
    )
    hhsize_fig = bar_chart(
        [(label, _joint_presence_frame(df, selected_hhsize)) for label, df in hhsize_list],
        x_col="jointTours",
        y_col="freq",
        title=f"Joint Tour Presence by HH Size - {selected_hhsize}",
        xaxis_title="Joint Tours",
        yaxis_title="Households",
        as_percent=as_percent and selected_hhsize != "Total",
        run_colors=run_colors,
    )

    return mo.vstack(
        [
            mo.md("## Joint Tours"),
            _plot(mo, jtf_fig),
            mo.hstack([_plot(mo, comp_fig), _plot(mo, party_fig)], widths="equal"),
            _maybe_control_row(mo, [hhsize_sel]),
            _plot(mo, hhsize_fig),
        ],
        gap=1.0,
    )


def render_destination(
    runs: Runs,
    config: Config,
    as_percent: bool,
    run_colors: Sequence[str],
    mo: Any,
    controls: dict[str, Any] | None = None,
    control_values: dict[str, Any] | None = None,
):
    del config
    purpose_opts = _destination_purpose_options(runs)
    purpose_sel = _control_widget(controls, "purpose")
    selected_purpose = _control_value(control_values, "purpose", purpose_opts[0])
    avg_df = _destination_avg_distance_table(runs)

    dist_fig = density_chart(
        [(label, _nm_dist_by_purpose(rd, selected_purpose)) for label, rd in runs],
        x_col="distbin",
        y_col="freq",
        title=f"NM Tour Distance Distribution - {selected_purpose}",
        xaxis_title="Distance (miles)",
        as_percent=as_percent,
        run_colors=run_colors,
        normalize=True,
    )

    return mo.vstack(
        [
            mo.md("## Destination Choice"),
            _maybe_control_row(mo, [purpose_sel]),
            _plot(mo, dist_fig),
            mo.md("### Average Tour Distances (miles)"),
            make_table(
                mo,
                avg_df,
                empty_text="No distance data is available.",
                column_order=["Purpose", *[label for label, _ in runs]],
                format_mapping=kpi_format_mapping(avg_df, digits=2),
            ),
        ],
        gap=1.0,
    )


def render_tour_tod(
    runs: Runs,
    config: Config,
    as_percent: bool,
    run_colors: Sequence[str],
    mo: Any,
    controls: dict[str, Any] | None = None,
    control_values: dict[str, Any] | None = None,
):
    del config
    tod_list = [(label, tour_tod.tod_profiles(rd)) for label, rd in runs]
    purpose_opts = _summary_value_options(tod_list, "purpose", default=["Total"])
    purpose_sel = _control_widget(controls, "purpose")
    selected_purpose = _control_value(control_values, "purpose", purpose_opts[0])

    maxbin = _max_timebin(tod_list)
    dep_fig = density_chart(
        [(label, _tour_tod_frame(df, selected_purpose, "freq_dep", maxbin)) for label, df in tod_list],
        x_col="clock_time",
        y_col="freq",
        title=f"Departure - {selected_purpose}",
        xaxis_title="Clock time (start at 03:00)",
        as_percent=as_percent,
        run_colors=run_colors,
    )
    arr_fig = density_chart(
        [(label, _tour_tod_frame(df, selected_purpose, "freq_arr", maxbin)) for label, df in tod_list],
        x_col="clock_time",
        y_col="freq",
        title=f"Arrival - {selected_purpose}",
        xaxis_title="Clock time (start at 03:00)",
        as_percent=as_percent,
        run_colors=run_colors,
    )
    dur_fig = density_chart(
        [(label, _tour_duration_frame(df, selected_purpose, maxbin)) for label, df in tod_list],
        x_col="duration_hours",
        y_col="freq",
        title=f"Duration - {selected_purpose}",
        xaxis_title="Duration (hours)",
        as_percent=as_percent,
        run_colors=run_colors,
    )
    dur_fig.update_xaxes(dtick=1, tick0=0, showgrid=True)

    return mo.vstack(
        [
            mo.md("## Tour Time of Day"),
            _maybe_control_row(mo, [purpose_sel]),
            _plot(mo, dep_fig),
            _plot(mo, arr_fig),
            _plot(mo, dur_fig),
        ],
        gap=1.0,
    )


def render_tour_mode(
    runs: Runs,
    config: Config,
    as_percent: bool,
    run_colors: Sequence[str],
    mo: Any,
    controls: dict[str, Any] | None = None,
    control_values: dict[str, Any] | None = None,
):
    mode_list = [(label, tour_mode.tour_mode_profile(rd, config)) for label, rd in runs]
    grouped_list = [(label, tour_mode.grouped_tour_mode_profile(rd, config)) for label, rd in runs]

    purpose_opts = _summary_value_options(mode_list, "purpose", default=["Total"])
    purpose_sel = _control_widget(controls, "purpose")
    selected_purpose = _control_value(control_values, "purpose", purpose_opts[0])

    def _filtered_mode(df: pl.DataFrame, col: str) -> pl.DataFrame:
        subset = _filter_value(df, "purpose", selected_purpose)
        if len(subset) == 0 or col not in subset.columns:
            return pl.DataFrame({"tour_mode": [], "freq": []})
        return _sort_modes(subset.select(["tour_mode", col]).rename({col: "freq"}), "tour_mode", config)

    all_fig = bar_chart(
        [(label, _filtered_mode(df, "freq_all")) for label, df in mode_list],
        x_col="tour_mode",
        y_col="freq",
        title=f"All Households - {selected_purpose}",
        xaxis_title="Mode",
        yaxis_title="Tours",
        as_percent=as_percent,
        run_colors=run_colors,
    )
    as0_fig = bar_chart(
        [(label, _filtered_mode(df, "freq_as0")) for label, df in mode_list],
        x_col="tour_mode",
        y_col="freq",
        title=f"Zero Autos - {selected_purpose}",
        xaxis_title="Mode",
        yaxis_title="Tours",
        as_percent=as_percent,
        run_colors=run_colors,
    )
    as1_fig = bar_chart(
        [(label, _filtered_mode(df, "freq_as1")) for label, df in mode_list],
        x_col="tour_mode",
        y_col="freq",
        title=f"Autos < Workers - {selected_purpose}",
        xaxis_title="Mode",
        yaxis_title="Tours",
        as_percent=as_percent,
        run_colors=run_colors,
    )
    as2_fig = bar_chart(
        [(label, _filtered_mode(df, "freq_as2")) for label, df in mode_list],
        x_col="tour_mode",
        y_col="freq",
        title=f"Autos >= Workers - {selected_purpose}",
        xaxis_title="Mode",
        yaxis_title="Tours",
        as_percent=as_percent,
        run_colors=run_colors,
    )

    rows: list[Any] = [
        mo.md("## Tour Mode Choice"),
        _maybe_control_row(mo, [purpose_sel]),
        mo.hstack([_plot(mo, all_fig), _plot(mo, as0_fig)], widths="equal"),
        mo.hstack([_plot(mo, as1_fig), _plot(mo, as2_fig)], widths="equal"),
    ]

    if config.mode_groups:
        grouped_fig = bar_chart(
            [
                (
                    label,
                    _filter_value(df, "purpose", selected_purpose)
                    .select(["mode_group", "freq_all"])
                    .rename({"freq_all": "freq"})
                    if len(df) > 0
                    else pl.DataFrame({"mode_group": [], "freq": []}),
                )
                for label, df in grouped_list
            ],
            x_col="mode_group",
            y_col="freq",
            title=f"Grouped Tour Mode - {selected_purpose}",
            xaxis_title="Mode Group",
            yaxis_title="Tours",
            as_percent=as_percent,
            run_colors=run_colors,
        )
        rows.extend([mo.md("### Grouped Mode Summary"), _plot(mo, grouped_fig)])

    return mo.vstack(rows, gap=1.0)


def render_stop_frequency(
    runs: Runs,
    config: Config,
    as_percent: bool,
    run_colors: Sequence[str],
    mo: Any,
    controls: dict[str, Any] | None = None,
    control_values: dict[str, Any] | None = None,
):
    del config
    stop_list = [(label, stops.stop_freq(rd)) for label, rd in runs]
    purpose_list = [(label, stops.stop_purpose_by_tour_purpose(rd)) for label, rd in runs]

    purpose_opts = _summary_value_options(stop_list, "primary_purpose", default=["Total"], include_total=True)
    purpose_sel = _control_widget(controls, "purpose")
    selected_purpose = _control_value(control_values, "purpose", purpose_opts[0])

    ob_fig = bar_chart(
        [(label, _stop_freq_frame(df, selected_purpose, "ob_stops", 3)) for label, df in stop_list],
        x_col="stops",
        y_col="freq",
        title=f"Outbound Stops - {selected_purpose}",
        xaxis_title="Stops",
        yaxis_title="Tours",
        as_percent=as_percent,
        run_colors=run_colors,
    )
    ib_fig = bar_chart(
        [(label, _stop_freq_frame(df, selected_purpose, "ib_stops", 3)) for label, df in stop_list],
        x_col="stops",
        y_col="freq",
        title=f"Inbound Stops - {selected_purpose}",
        xaxis_title="Stops",
        yaxis_title="Tours",
        as_percent=as_percent,
        run_colors=run_colors,
    )
    tot_fig = bar_chart(
        [(label, _stop_freq_frame(df, selected_purpose, "tot_stops", 6)) for label, df in stop_list],
        x_col="stops",
        y_col="freq",
        title=f"Total Stops - {selected_purpose}",
        xaxis_title="Stops",
        yaxis_title="Tours",
        as_percent=as_percent,
        run_colors=run_colors,
    )
    purpose_fig = bar_chart(
        [(label, _stop_purpose_frame(df, selected_purpose)) for label, df in purpose_list],
        x_col="purpose",
        y_col="freq",
        title=f"Stop Purpose - tour={selected_purpose}",
        xaxis_title="Stop Purpose",
        yaxis_title="Stops",
        as_percent=as_percent,
        run_colors=run_colors,
    )

    return mo.vstack(
        [
            mo.md("## Stop Frequency"),
            _maybe_control_row(mo, [purpose_sel]),
            mo.hstack([_plot(mo, ob_fig), _plot(mo, ib_fig), _plot(mo, tot_fig)], widths="equal"),
            _plot(mo, purpose_fig),
        ],
        gap=1.0,
    )


def render_stop_location(
    runs: Runs,
    config: Config,
    as_percent: bool,
    run_colors: Sequence[str],
    mo: Any,
    controls: dict[str, Any] | None = None,
    control_values: dict[str, Any] | None = None,
):
    del config
    loc_list = [(label, stops.stop_location(rd)) for label, rd in runs]
    purpose_opts = _summary_value_options(loc_list, "primary_purpose", default=["All"], include_all=True)
    purpose_sel = _control_widget(controls, "purpose")
    selected_purpose = _control_value(control_values, "purpose", purpose_opts[0])

    loc_fig = density_chart(
        [(label, _stop_location_frame(df, selected_purpose)) for label, df in loc_list],
        x_col="distbin",
        y_col="freq",
        title=f"Stop Out-of-Direction Distance - {selected_purpose}",
        xaxis_title="Miles",
        as_percent=as_percent,
        run_colors=run_colors,
        normalize=True,
    )

    return mo.vstack(
        [
            mo.md("## Stop Location"),
            _maybe_control_row(mo, [purpose_sel]),
            _plot(mo, loc_fig),
        ],
        gap=1.0,
    )


def render_stop_timing(
    runs: Runs,
    config: Config,
    as_percent: bool,
    run_colors: Sequence[str],
    mo: Any,
    controls: dict[str, Any] | None = None,
    control_values: dict[str, Any] | None = None,
):
    del config
    timing_list = [(label, stops.stop_timing(rd)) for label, rd in runs]
    purpose_opts = _summary_value_options(timing_list, "primary_purpose", default=["Total"])
    purpose_sel = _control_widget(controls, "purpose")
    selected_purpose = _control_value(control_values, "purpose", purpose_opts[0])

    maxbin = _max_timebin(timing_list)
    trip_fig = density_chart(
        [(label, _stop_timing_frame(df, selected_purpose, "freq_trip_dep", maxbin)) for label, df in timing_list],
        x_col="clock_time",
        y_col="freq",
        title=f"Trip Departure - {selected_purpose}",
        xaxis_title="Clock time (start at 03:00)",
        as_percent=as_percent,
        run_colors=run_colors,
    )
    stop_fig = density_chart(
        [(label, _stop_timing_frame(df, selected_purpose, "freq_stop_dep", maxbin)) for label, df in timing_list],
        x_col="clock_time",
        y_col="freq",
        title=f"Stop Departure - {selected_purpose}",
        xaxis_title="Clock time (start at 03:00)",
        as_percent=as_percent,
        run_colors=run_colors,
    )

    return mo.vstack(
        [
            mo.md("## Stop Timing"),
            _maybe_control_row(mo, [purpose_sel]),
            _plot(mo, trip_fig),
            _plot(mo, stop_fig),
        ],
        gap=1.0,
    )


def render_trip_mode(
    runs: Runs,
    config: Config,
    as_percent: bool,
    run_colors: Sequence[str],
    mo: Any,
    controls: dict[str, Any] | None = None,
    control_values: dict[str, Any] | None = None,
):
    trip_list = [(label, trips.trip_mode_profile(rd, config)) for label, rd in runs]
    purpose_opts = _summary_value_options(trip_list, "primary_purpose", default=["Total"], include_total=True)
    tour_mode_opts = trip_tour_mode_options(runs, include_all=True)

    purpose_sel = _control_widget(controls, "purpose")
    mode_sel = _control_widget(controls, "tour_mode")
    selected_purpose = _control_value(control_values, "purpose", purpose_opts[0])
    selected_mode = _control_value(control_values, "tour_mode", tour_mode_opts[0])

    trip_fig = bar_chart(
        [(label, _trip_mode_frame(df, selected_purpose, selected_mode, config)) for label, df in trip_list],
        x_col="trip_mode",
        y_col="freq",
        title=f"Trip Mode - {selected_purpose} / Tour Mode: {selected_mode}",
        xaxis_title="Trip Mode",
        yaxis_title="Trips",
        as_percent=as_percent,
        run_colors=run_colors,
    )

    return mo.vstack(
        [
            mo.md("## Trip Mode Choice"),
            _maybe_control_row(mo, [purpose_sel, mode_sel]),
            _plot(mo, trip_fig),
        ],
        gap=1.0,
    )


def _kpi_card(
    mo: Any,
    label: str,
    totals_list: list[tuple[str, pl.DataFrame]],
    metric: str,
    run_colors: Sequence[str],
    icon: str,
):
    values = [
        (
            run_label,
            float(df[metric][0]) if metric in df.columns and len(df) > 0 else 0.0,
        )
        for run_label, df in totals_list
    ]
    return mo.Html(kpi_card_html(label=label, values=values, run_colors=run_colors, icon=icon))


def _ordered_dap(df: pl.DataFrame, ptype: str) -> pl.DataFrame:
    base = pl.DataFrame({"DAP": ["M", "N", "H"]})
    subset = _filter_value(df, "ptype", ptype)
    if len(subset) == 0:
        return base.with_columns(pl.lit(0.0).alias("freq"))
    normalized = subset.with_columns(pl.col("DAP").cast(pl.Utf8))
    return (
        base.join(normalized.select(["DAP", "freq"]), on="DAP", how="left")
        .with_columns(pl.col("freq").fill_null(0.0))
    )


def _ordered_mtf(df: pl.DataFrame, ptype: str) -> pl.DataFrame:
    base = pl.DataFrame({"MTF": [1, 2, 3, 4, 5]})
    labels = pl.DataFrame(
        {
            "MTF": [1, 2, 3, 4, 5],
            "MTF_label": ["work1", "work2", "school1", "school2", "work and school"],
        }
    )
    subset = _filter_value(df, "ptype", ptype)
    if len(subset) == 0:
        return base.join(labels, on="MTF", how="left").with_columns(pl.lit(0.0).alias("freq")).select(["MTF_label", "freq"])
    normalized = subset.with_columns(pl.col("MTF").cast(pl.Int64))
    return (
        base.join(normalized.select(["MTF", "freq"]), on="MTF", how="left")
        .with_columns(pl.col("freq").fill_null(0.0))
        .join(labels, on="MTF", how="left")
        .select(["MTF_label", "freq"])
    )


def _ordered_inm(df: pl.DataFrame, ptype: str) -> pl.DataFrame:
    base = pl.DataFrame({"nmtours": ["0", "1", "2", "3pl"]})
    subset = _filter_value(df, "ptype", ptype).with_columns(pl.col("nmtours").cast(pl.Utf8))
    if len(subset) == 0:
        return base.with_columns(pl.lit(0.0).alias("freq"))
    return base.join(subset.select(["nmtours", "freq"]), on="nmtours", how="left").with_columns(pl.col("freq").fill_null(0.0))


def _ordered_joint_comp(df: pl.DataFrame) -> pl.DataFrame:
    base = pl.DataFrame({"tour_composition": ["adults", "mixed", "children"]})
    if len(df) == 0:
        return base.with_columns(pl.lit(0.0).alias("freq"))
    normalized = df.with_columns(pl.col("tour_composition").cast(pl.Utf8).str.to_lowercase().alias("tour_composition"))
    return (
        base.join(normalized.select(["tour_composition", "freq"]), on="tour_composition", how="left")
        .with_columns(pl.col("freq").fill_null(0.0))
    )


def _joint_hhsize_options(hhsize_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    values = _summary_value_options(hhsize_list, "hhsize", default=["Total"])
    return ["Total"] + [value for value in values if value != "Total"]


def _is_joint_hhsize_option(value: str) -> bool:
    if value == "Total":
        return True
    try:
        return int(float(value)) >= 2
    except (TypeError, ValueError):
        return False


def _joint_presence_frame(df: pl.DataFrame, hhsize: str) -> pl.DataFrame:
    base = pl.DataFrame({"jointTours": ["0", "1", "2+"]})
    if len(df) == 0:
        return base.with_columns(pl.lit(0.0).alias("freq"))
    if hhsize == "Total":
        subset = df.group_by("jointTours").agg(pl.col("freq").sum().alias("freq"))
        joined = base.join(subset, on="jointTours", how="left").with_columns(pl.col("freq").fill_null(0.0))
        total = float(joined["freq"].sum())
        if total > 0:
            joined = joined.with_columns((pl.col("freq") / total * 100.0).alias("freq"))
        return joined
    subset = df.filter(pl.col("hhsize").cast(pl.Utf8) == hhsize)
    return base.join(subset.select(["jointTours", "freq"]), on="jointTours", how="left").with_columns(pl.col("freq").fill_null(0.0))


def _destination_purpose_options(runs: Runs) -> list[str]:
    purposes: set[str] = set()
    for _, rd in runs:
        if {"tour_category", "primary_purpose"}.issubset(rd.tours.columns):
            nm_tours = rd.tours.filter(pl.col("tour_category").is_in(["non-mandatory", "atwork", "joint"]))
            purposes.update(str(value) for value in nm_tours["primary_purpose"].drop_nulls().unique().to_list())
    return ["All NM"] + sorted(purposes)


def _select_distance_frame(df: pl.DataFrame) -> pl.DataFrame:
    if len(df) == 0 or "SKIMDIST" not in df.columns or "finalweight" not in df.columns:
        return pl.DataFrame()
    return df.select(["SKIMDIST", "finalweight"])


def _nm_dist_by_purpose(rd: RunData, purpose: str | None) -> pl.DataFrame:
    if "tour_category" not in rd.tours.columns:
        return pl.DataFrame({"distbin": list(range(41)), "freq": [0.0] * 41})

    indiv = rd.tours.filter(pl.col("tour_category").is_in(["non-mandatory", "atwork"]))
    joint = rd.tours.filter(pl.col("tour_category") == "joint")
    if len(joint) > 0:
        joint = joint.with_columns((pl.col("finalweight") * pl.col("NUMBER_HH")).alias("finalweight"))

    if purpose in (None, "All NM"):
        frames = [_select_distance_frame(indiv), _select_distance_frame(joint)]
    else:
        if "primary_purpose" not in rd.tours.columns:
            return pl.DataFrame({"distbin": list(range(41)), "freq": [0.0] * 41})
        frames = [
            _select_distance_frame(indiv.filter(pl.col("primary_purpose") == purpose)),
            _select_distance_frame(joint.filter(pl.col("primary_purpose") == purpose)),
        ]

    valid_frames = [frame for frame in frames if len(frame) > 0]
    combined = pl.concat(valid_frames, how="vertical_relaxed") if valid_frames else pl.DataFrame()
    if len(combined) == 0 or "SKIMDIST" not in combined.columns:
        return pl.DataFrame({"distbin": list(range(41)), "freq": [0.0] * 41})

    counts = (
        combined.with_columns(pl.col("SKIMDIST").cast(pl.Int32).clip(0, 40).alias("distbin"))
        .group_by("distbin")
        .agg(pl.col("finalweight").sum().alias("freq"))
    )
    return pl.DataFrame({"distbin": list(range(41))}).join(counts, on="distbin", how="left").fill_null(0).sort("distbin")


def _destination_avg_distance_table(runs: Runs) -> pl.DataFrame:
    purposes = [value for value in _destination_purpose_options(runs) if value != "All NM"]
    rows: list[dict[str, object]] = []
    for purpose in purposes:
        row: dict[str, object] = {"Purpose": purpose}
        for run_label, rd in runs:
            if not {"SKIMDIST", "primary_purpose", "finalweight"}.issubset(rd.tours.columns):
                row[run_label] = None
                continue
            subset = rd.tours.filter(pl.col("primary_purpose") == purpose)
            if len(subset) == 0 or float(subset["finalweight"].sum()) <= 0:
                row[run_label] = None
                continue
            avg = subset.select((pl.col("SKIMDIST") * pl.col("finalweight")).sum() / pl.col("finalweight").sum()).item()
            row[run_label] = round(float(avg), 2) if avg is not None else None
        rows.append(row)
    return pl.DataFrame(rows) if rows else pl.DataFrame()


def _tour_tod_frame(df: pl.DataFrame, purpose: str, value_col: str, maxbin: int) -> pl.DataFrame:
    subset = _filter_value(df, "purpose", purpose)
    if len(subset) == 0:
        return pl.DataFrame({"clock_time": [], "freq": []})
    return (
        subset.select(["timebin", value_col])
        .rename({value_col: "freq"})
        .with_columns(
            pl.col("timebin").map_elements(lambda tb: _time_label(int(tb), maxbin), return_dtype=pl.Utf8).alias("clock_time")
        )
        .select(["clock_time", "freq"])
    )


def _tour_duration_frame(df: pl.DataFrame, purpose: str, maxbin: int) -> pl.DataFrame:
    subset = _filter_value(df, "purpose", purpose)
    if len(subset) == 0:
        return pl.DataFrame({"duration_hours": [], "freq": []})
    return (
        subset.select(["timebin", "freq_dur"])
        .rename({"freq_dur": "freq"})
        .with_columns(
            pl.col("timebin")
            .map_elements(lambda tb: _duration_hours(int(tb), maxbin), return_dtype=pl.Float64)
            .alias("duration_hours")
        )
        .select(["duration_hours", "freq"])
    )


def _stop_freq_frame(df: pl.DataFrame, purpose: str, source_col: str, max_stops: int) -> pl.DataFrame:
    base = pl.DataFrame({"stops": [str(i) for i in range(max_stops + 1)]})
    subset = df
    if purpose != "Total" and "primary_purpose" in df.columns:
        subset = df.filter(pl.col("primary_purpose") == purpose)
    if len(subset) == 0:
        return base.with_columns(pl.lit(0.0).alias("freq"))
    grouped = (
        subset.group_by(source_col)
        .agg(pl.col("freq").sum().alias("freq"))
        .with_columns(pl.col(source_col).cast(pl.Utf8).alias("stops"))
        .select(["stops", "freq"])
    )
    return base.join(grouped, on="stops", how="left").with_columns(pl.col("freq").fill_null(0.0))


def _stop_purpose_frame(df: pl.DataFrame, purpose: str) -> pl.DataFrame:
    if len(df) == 0:
        return pl.DataFrame({"purpose": [], "freq": []})
    subset = df if purpose == "Total" else df.filter(pl.col("primary_purpose") == purpose)
    if len(subset) == 0:
        return pl.DataFrame({"purpose": [], "freq": []})
    return subset.group_by("purpose").agg(pl.col("freq").sum().alias("freq")).sort("purpose")


def _stop_location_frame(df: pl.DataFrame, purpose: str) -> pl.DataFrame:
    base = pl.DataFrame({"distbin": list(range(41))})
    if len(df) == 0:
        return base.with_columns(pl.lit(0.0).alias("freq"))
    if purpose == "All":
        grouped = df.group_by("distbin").agg(pl.col("freq").sum().alias("freq")).sort("distbin")
    else:
        grouped = df.filter(pl.col("primary_purpose") == purpose).select(["distbin", "freq"]).sort("distbin")
    return base.join(grouped, on="distbin", how="left").with_columns(pl.col("freq").fill_null(0.0))


def _stop_timing_frame(df: pl.DataFrame, purpose: str, value_col: str, maxbin: int) -> pl.DataFrame:
    subset = _filter_value(df, "primary_purpose", purpose)
    if len(subset) == 0:
        return pl.DataFrame({"clock_time": [], "freq": []})
    return (
        subset.select(["timebin", value_col])
        .rename({value_col: "freq"})
        .with_columns(
            pl.col("timebin").map_elements(lambda tb: _time_label(int(tb), maxbin), return_dtype=pl.Utf8).alias("clock_time")
        )
        .select(["clock_time", "freq"])
    )


def _trip_mode_frame(df: pl.DataFrame, purpose: str, selected_mode: str, config: Config) -> pl.DataFrame:
    subset = df
    if purpose != "Total" and "primary_purpose" in subset.columns:
        subset = subset.filter(pl.col("primary_purpose") == purpose)
    if selected_mode != "All" and "tour_mode" in subset.columns:
        subset = subset.filter(pl.col("tour_mode") == selected_mode)
    if len(subset) == 0:
        return pl.DataFrame({"trip_mode": [], "freq": []})
    return _sort_modes(subset.group_by("trip_mode").agg(pl.col("freq").sum().alias("freq")), "trip_mode", config)


def _tlfd_geography_options(tlfd_list: list[tuple[str, dict[str, pl.DataFrame]]]) -> list[str]:
    values: set[str] = set()
    for _, mapping in tlfd_list:
        for df in mapping.values():
            for column in df.columns:
                if column not in {"distbin", "Total"}:
                    values.add(str(column))
    ordered = sorted(values)
    return ["All"] + ordered if ordered else ["All"]


def _tlfd_frame(df: pl.DataFrame | None, column: str) -> pl.DataFrame:
    if df is None or len(df) == 0:
        return pl.DataFrame({"distbin": list(range(1, 52)), "freq": [0.0] * 51})
    source_col = column if column in df.columns else "Total"
    return df.select(["distbin", source_col]).rename({source_col: "freq"}).sort("distbin")


def _controls_long_term(runs: Runs, config: Config, mo: Any) -> dict[str, Any]:
    if not config.geography_enabled:
        return {}
    return {"geography": _dropdown_widget(mo, "Geography", geography_options(runs, include_all=True))}


def _controls_tour_summary(runs: Runs, config: Config, mo: Any) -> dict[str, Any]:
    return {"ptype": _dropdown_widget(mo, "Person Type", person_type_options(runs, config, include_total=True))}


def _controls_joint_tours(runs: Runs, config: Config, mo: Any) -> dict[str, Any]:
    del config
    options = [value for value in hh_size_options(runs, include_total=True) if _is_joint_hhsize_option(value)]
    return {"hhsize": _dropdown_widget(mo, "HH Size", options or ["Total"])}


def _controls_destination(runs: Runs, config: Config, mo: Any) -> dict[str, Any]:
    del config
    return {"purpose": _dropdown_widget(mo, "Purpose", _destination_purpose_options(runs))}


def _controls_tour_tod(runs: Runs, config: Config, mo: Any) -> dict[str, Any]:
    summary_list = [(label, tour_tod.tod_profiles(rd)) for label, rd in runs]
    options = _summary_value_options(summary_list, "purpose", default=["Total"])
    return {"purpose": _dropdown_widget(mo, "Purpose", options)}


def _controls_tour_mode(runs: Runs, config: Config, mo: Any) -> dict[str, Any]:
    summary_list = [(label, tour_mode.tour_mode_profile(rd, config)) for label, rd in runs]
    options = _summary_value_options(summary_list, "purpose", default=["Total"])
    return {"purpose": _dropdown_widget(mo, "Purpose", options)}


def _controls_stop_frequency(runs: Runs, config: Config, mo: Any) -> dict[str, Any]:
    del config
    options = purpose_options_from_tours(runs, include_total=True)
    return {"purpose": _dropdown_widget(mo, "Tour Purpose", options)}


def _controls_stop_location(runs: Runs, config: Config, mo: Any) -> dict[str, Any]:
    del config
    options = ["All"] + [value for value in purpose_options_from_trips(runs, include_total=False) if value != "All"]
    return {"purpose": _dropdown_widget(mo, "Purpose", options or ["All"])}


def _controls_stop_timing(runs: Runs, config: Config, mo: Any) -> dict[str, Any]:
    del config
    options = purpose_options_from_trips(runs, include_total=True)
    return {"purpose": _dropdown_widget(mo, "Purpose", options)}


def _controls_trip_mode(runs: Runs, config: Config, mo: Any) -> dict[str, Any]:
    del config
    return {
        "purpose": _dropdown_widget(mo, "Tour Purpose", purpose_options_from_trips(runs, include_total=True)),
        "tour_mode": _dropdown_widget(mo, "Tour Mode", trip_tour_mode_options(runs, include_all=True)),
    }


PAGE_CONTROL_BUILDERS = {
    "Long-Term": _controls_long_term,
    "Tour Summary": _controls_tour_summary,
    "Joint Tours": _controls_joint_tours,
    "Destination": _controls_destination,
    "Tour TOD": _controls_tour_tod,
    "Tour Mode": _controls_tour_mode,
    "Stop Frequency": _controls_stop_frequency,
    "Stop Location": _controls_stop_location,
    "Stop Timing": _controls_stop_timing,
    "Trip Mode": _controls_trip_mode,
}


PAGE_RENDERERS = {
    "Overview": render_overview,
    "Long-Term": render_long_term,
    "Tour Summary": render_tour_summary,
    "Joint Tours": render_joint_tours,
    "Destination": render_destination,
    "Tour TOD": render_tour_tod,
    "Tour Mode": render_tour_mode,
    "Stop Frequency": render_stop_frequency,
    "Stop Location": render_stop_location,
    "Stop Timing": render_stop_timing,
    "Trip Mode": render_trip_mode,
}
