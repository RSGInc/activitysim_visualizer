"""ActivitySim Panel dashboard - main app assembly."""
from __future__ import annotations

import panel as pn

from dashboard import DashboardState
from dashboard.components import run_color, set_percent_mode, set_run_colors
from dashboard.live_pages import build_live_pages
from dashboard.pages import (
    destination,
    joint_tours,
    long_term,
    overview,
    stop_freq,
    stop_location,
    stop_timing,
    tour_mode,
    tour_summary,
    tour_tod,
    trip_mode,
)
from summarize.reader import Config, RunData

pn.extension("plotly", "tabulator", sizing_mode="stretch_width")
pn.config.raw_css.append(
    """
.bk-root { font-family: Inter, 'Segoe UI', Arial, sans-serif; }
.bk-tab { font-weight: 600; }
.bk-tabs-header { margin-bottom: 12px; }
.pn-loading.arc:before { border-width: 3px; }
.bk-btn-group .bk-btn { border-width: 1.5px; font-weight: 600; }
.bk-btn-group .bk-btn.bk-active { box-shadow: inset 0 0 0 2px rgba(0,0,0,.15); }
"""
)

_TAB_BUILDERS = [
    ("Overview", overview.build),
    ("Long-Term", long_term.build),
    ("Tour Summary", tour_summary.build),
    ("Joint Tours", joint_tours.build),
    ("Destination", destination.build),
    ("Tour TOD", tour_tod.build),
    ("Tour Mode", tour_mode.build),
    ("Stop Frequency", stop_freq.build),
    ("Stop Location", stop_location.build),
    ("Stop Timing", stop_timing.build),
    ("Trip Mode", trip_mode.build),
]


def _build_tabs(
    runs: list[tuple[str, RunData]],
    config: Config,
    dynamic: bool = True,
) -> pn.Tabs:
    """Build a simple tabs view from the configured page builders."""
    return pn.Tabs(
        *[(title, builder(runs, config)) for title, builder in _TAB_BUILDERS],
        dynamic=dynamic,
    )


def build_dashboard(
    runs: list[tuple[str, RunData]],
    config: Config,
    static_export: bool = False,
) -> pn.template.FastListTemplate:
    """Assemble the full Panel dashboard from a list of (label, RunData) tuples."""
    set_run_colors(config.run_colors)
    run_labels = [label for label, _ in runs]
    state = DashboardState(runs)

    weight_mode = pn.widgets.RadioButtonGroup(
        name="Weighting",
        options=["Weighted", "Unweighted"],
        value=state.weight_mode,
        button_type="primary",
        width=250,
    )
    value_mode = pn.widgets.RadioButtonGroup(
        name="Values",
        options=["Percent", "Count"],
        value=state.value_mode,
        button_type="primary",
        width=220,
    )

    if static_export:
        weight_mode.disabled = True
        value_mode.disabled = True
        set_percent_mode(True)
        main_content = _build_tabs(runs, config, dynamic=False)
        pages = []
        watchers = []
    else:
        pages = build_live_pages(state, config)
        tabs = pn.Tabs(
            *[(page.name, page.view) for page in pages],
            dynamic=False,
        )

        def _render_tab(tab_index: int) -> None:
            pages[tab_index].refresh_if_needed()

        def _mark_all_tabs_stale() -> None:
            for page in pages:
                page.mark_stale()

        def _on_tab_change(event) -> None:
            state.active_tab = int(event.new)
            _render_tab(state.active_tab)

        def _on_weight_change(event) -> None:
            _mark_all_tabs_stale()
            _render_tab(state.active_tab)

        def _on_value_change(event) -> None:
            _mark_all_tabs_stale()
            _render_tab(state.active_tab)

        weight_mode.link(state, value="weight_mode")
        value_mode.link(state, value="value_mode")

        watchers = [
            tabs.param.watch(_on_tab_change, "active"),
            state.param.watch(_on_weight_change, "weight_mode"),
            state.param.watch(_on_value_change, "value_mode"),
        ]

        tabs.active = state.active_tab
        _render_tab(state.active_tab)
        main_content = tabs

    sidebar_items = [
        pn.pane.Markdown("## Runs Loaded"),
        *[
            pn.pane.HTML(
                f'<div style="padding:8px 10px;border-left:4px solid {_color(i)};margin:6px 0;'
                f'border-radius:6px;background:rgba(127,127,127,0.06)">'
                f'<b style="color:{_color(i)}">{label}</b></div>'
            )
            for i, label in enumerate(run_labels)
        ],
        pn.layout.Divider(),
        pn.pane.Markdown("## Display Options"),
        pn.pane.HTML(
            "<div style='font-size:12px;color:#666;margin-bottom:4px'>"
            "Display mode controls."
            + (
                "<br><b>Note:</b> Static HTML export is a snapshot; these controls require a live Panel session."
                if static_export
                else ""
            )
            + "</div>"
        ),
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
    template._dashboard_state = state
    template._dashboard_pages = pages
    template._dashboard_watchers = watchers
    return template


def build_export_view(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    """Build a non-template view for static HTML export with embedded widget states."""
    set_run_colors(config.run_colors)
    set_percent_mode(True)
    tabs = _build_tabs(runs, config, dynamic=False)
    return pn.Column(
        pn.pane.Markdown(f"# {config.dashboard_title}"),
        pn.pane.Markdown("**Static export mode** (defaults: Weighted + Percent)."),
        tabs,
        sizing_mode="stretch_width",
    )


def _color(idx: int) -> str:
    return run_color(idx)
