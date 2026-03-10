"""ActivitySim Panel dashboard — main app assembly."""
from __future__ import annotations
import panel as pn
import polars as pl
from summarize.reader import RunData, Config
from dashboard.components import set_percent_mode, set_run_colors, run_color
from dashboard.pages import (
    overview, long_term, tour_summary, joint_tours, destination,
    tour_tod, tour_mode, stop_freq, stop_location, stop_timing, trip_mode,
)

pn.extension("plotly", "tabulator", sizing_mode="stretch_width")
pn.config.raw_css.append("""
.bk-root { font-family: Inter, 'Segoe UI', Arial, sans-serif; }
.bk-tab { font-weight: 600; }
.bk-tabs-header { margin-bottom: 12px; }
.pn-loading.arc:before { border-width: 3px; }
.bk-btn-group .bk-btn { border-width: 1.5px; font-weight: 600; }
.bk-btn-group .bk-btn.bk-active { box-shadow: inset 0 0 0 2px rgba(0,0,0,.15); }
""")


def _strip_weights(rd: RunData) -> RunData:
    """Return a copy of RunData with finalweight=1.0 on all tables (raw counts)."""
    def _reset(df: pl.DataFrame) -> pl.DataFrame:
        if "finalweight" in df.columns:
            return df.with_columns(pl.lit(1.0).alias("finalweight"))
        return df
    return RunData(
        label=rd.label,
        run_dir=rd.run_dir,
        skim_file=rd.skim_file,
        hh=_reset(rd.hh),
        per=_reset(rd.per),
        tours=_reset(rd.tours),
        trips=_reset(rd.trips),
        joint_participants=rd.joint_participants,
        land_use=rd.land_use,
        skim_matrix=rd.skim_matrix,
        skim_zone_map=rd.skim_zone_map,
        hh_weight_col=None,
        person_weight_col=None,
        trip_weight_col=None,
    )


def build_dashboard(
    runs: list[tuple[str, RunData]],
    config: Config,
    static_export: bool = False,
) -> pn.template.FastListTemplate:
    """Assemble the full Panel dashboard from a list of (label, RunData) tuples."""
    set_run_colors(config.run_colors)
    run_labels = [label for label, _ in runs]

    # Pre-compute unweighted variant (finalweight=1 everywhere)
    unweighted_runs = [(label, _strip_weights(rd)) for label, rd in runs]

    weight_mode = pn.widgets.RadioButtonGroup(
        name="Weighting",
        options=["Weighted", "Unweighted"],
        value="Weighted",
        button_type="primary",
        width=250,
    )
    value_mode = pn.widgets.RadioButtonGroup(
        name="Values",
        options=["Percent", "Count"],
        value="Percent",
        button_type="primary",
        width=220,
    )

    def make_tabs(cur_runs: list[tuple[str, RunData]], as_percent: bool, dynamic: bool = True) -> pn.Tabs:
        set_percent_mode(as_percent)
        return pn.Tabs(
            ("Overview",       overview.build(cur_runs, config)),
            ("Long-Term",      long_term.build(cur_runs, config)),
            ("Tour Summary",   tour_summary.build(cur_runs, config)),
            ("Joint Tours",    joint_tours.build(cur_runs, config)),
            ("Destination",    destination.build(cur_runs, config)),
            ("Tour TOD",       tour_tod.build(cur_runs, config)),
            ("Tour Mode",      tour_mode.build(cur_runs, config)),
            ("Stop Frequency", stop_freq.build(cur_runs, config)),
            ("Stop Location",  stop_location.build(cur_runs, config)),
            ("Stop Timing",    stop_timing.build(cur_runs, config)),
            ("Trip Mode",      trip_mode.build(cur_runs, config)),
            dynamic=dynamic,
        )

    if static_export:
        weight_mode.disabled = True
        value_mode.disabled = True
        main_content = make_tabs(runs, as_percent=True, dynamic=False)
    else:
        # Build tab sets lazily and cache so toggling is fast without rebuilding every time.
        tabs_cache: dict[tuple[bool, bool], pn.Tabs] = {}
        def _get_tabs(weighting: str, values: str) -> pn.Tabs:
            use_weights = weighting == "Weighted"
            as_percent = values == "Percent"
            key = (use_weights, as_percent)
            if key not in tabs_cache:
                tabs_cache[key] = make_tabs(runs if use_weights else unweighted_runs, as_percent)
            return tabs_cache[key]
        main_content = pn.bind(_get_tabs, weight_mode, value_mode)

    sidebar_items = [
        pn.pane.Markdown("## Runs Loaded"),
        *[pn.pane.HTML(
            f'<div style="padding:8px 10px;border-left:4px solid {_color(i)};margin:6px 0;'
            f'border-radius:6px;background:rgba(127,127,127,0.06)">'
            f'<b style="color:{_color(i)}">{label}</b></div>'
          )
          for i, label in enumerate(run_labels)],
        pn.layout.Divider(),
        pn.pane.Markdown("## Display Options"),
        pn.pane.HTML("<div style='font-size:12px;color:#666;margin-bottom:4px'>"
                     "Display mode controls."
                     + ("<br><b>Note:</b> Static HTML export is a snapshot; these controls require a live Panel session."
                        if static_export else "")
                     + "</div>"),
        weight_mode,
        value_mode,
    ]

    template = pn.template.FastListTemplate(
        title=config.dashboard_title,
        sidebar=sidebar_items,
        main=[main_content],
        theme="default",
        accent_base_color="#4E79A7",
        header_background="#4E79A7",
        sidebar_width=340,
    )
    return template

def build_export_view(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    """Build a non-template view for static HTML export with embedded widget states."""
    set_run_colors(config.run_colors)
    set_percent_mode(True)
    tabs = pn.Tabs(
        ("Overview",       overview.build(runs, config)),
        ("Long-Term",      long_term.build(runs, config)),
        ("Tour Summary",   tour_summary.build(runs, config)),
        ("Joint Tours",    joint_tours.build(runs, config)),
        ("Destination",    destination.build(runs, config)),
        ("Tour TOD",       tour_tod.build(runs, config)),
        ("Tour Mode",      tour_mode.build(runs, config)),
        ("Stop Frequency", stop_freq.build(runs, config)),
        ("Stop Location",  stop_location.build(runs, config)),
        ("Stop Timing",    stop_timing.build(runs, config)),
        ("Trip Mode",      trip_mode.build(runs, config)),
        dynamic=False,
    )
    return pn.Column(
        pn.pane.Markdown(f"# {config.dashboard_title}"),
        pn.pane.Markdown("**Static export mode** (defaults: Weighted + Percent)."),
        tabs,
        sizing_mode="stretch_width",
    )


def _color(idx: int) -> str:
    return run_color(idx)

