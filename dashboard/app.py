"""ActivitySim Panel dashboard - main app assembly."""

from __future__ import annotations

import json
from collections.abc import Iterable

import panel as pn

from dashboard import DashboardState
from dashboard.components import run_color, set_percent_mode, set_run_colors
from dashboard.live_pages import (
    DestinationPage,
    TourSummaryPage,
    TripModePage,
    build_live_pages,
)
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
from summarize.cache import SummaryRun
from summarize.reader import Config, RunData

pn.extension("plotly", "tabulator", sizing_mode="stretch_width")
pn.config.raw_css.append("""
.bk-root { font-family: Inter, 'Segoe UI', Arial, sans-serif; }
.bk-tab { font-weight: 600; }
.bk-tabs-header { margin-bottom: 12px; }
.pn-loading.arc:before { border-width: 3px; }
.bk-btn-group .bk-btn { border-width: 1.5px; font-weight: 600; }
.bk-btn-group .bk-btn.bk-active { box-shadow: inset 0 0 0 2px rgba(0,0,0,.15); }
""")

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

_EXPORT_WIDGET_STATE_SPEC = {
    ("Tour Summary", "Person Type"): [
        "Total",
        "Full-time worker",
        "University student",
    ],
    ("Destination", "Purpose"): ["All NM", "eatout", "social"],
    ("Trip Mode", "Tour Purpose"): ["Total", "shopping"],
    ("Trip Mode", "Tour Mode"): ["All", "DRIVEALONE"],
}


def _build_tabs(
    runs: list[tuple[str, RunData]],
    config: Config,
    dynamic: bool = True,
) -> pn.Tabs:
    """Build a simple tabs view from the configured page builders."""
    return _tabs_from_views(_build_tab_views(runs, config), dynamic=dynamic)


def _build_tab_views(
    runs: list[tuple[str, RunData]],
    config: Config,
) -> list[tuple[str, pn.viewable.Viewable]]:
    """Build the configured page views paired with their tab titles."""
    return [(title, builder(runs, config)) for title, builder in _TAB_BUILDERS]


def _tabs_from_views(
    tab_views: Iterable[tuple[str, pn.viewable.Viewable]],
    dynamic: bool = True,
) -> pn.Tabs:
    """Build tabs from preconstructed `(title, view)` pairs."""
    return pn.Tabs(
        *list(tab_views),
        dynamic=dynamic,
    )


def build_dashboard(
    runs: list[tuple[str, RunData]],
    config: Config,
    static_export: bool = False,
    summary_runs: list[SummaryRun] | None = None,
) -> pn.template.FastListTemplate:
    """Assemble the full Panel dashboard from a list of (label, RunData) tuples."""
    set_run_colors(config.run_colors)
    state = DashboardState(
        runs,
        summary_runs=summary_runs,
        weighting_modes=config.weighting_modes,
    )
    run_labels = state.run_labels

    weight_mode = pn.widgets.RadioButtonGroup(
        name="Weighting",
        options=list(state.param.weight_mode.objects),
        value=state.weight_mode,
        button_type="primary",
        width=250,
    )
    if len(weight_mode.options) <= 1:
        weight_mode.disabled = True
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


def build_export_view(
    runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> tuple[pn.viewable.Viewable, dict[pn.widgets.Widget, list[object]]]:
    """Build a static HTML export view with frontend-only saved widget states."""
    set_run_colors(config.run_colors)
    set_percent_mode(True)
    state = DashboardState(
        runs,
        summary_runs=summary_runs,
        weighting_modes=config.weighting_modes,
    )
    pages = build_live_pages(state, config)
    tab_views: list[tuple[str, pn.viewable.Viewable]] = []

    # example of embedded widget states
    for page in pages:
        if page.name == "Tour Summary":
            tab_views.append(
                (
                    page.name,
                    _build_export_tour_summary(runs, config, summary_runs=summary_runs),
                )
            )
        elif page.name == "Destination":
            tab_views.append(
                (
                    page.name,
                    _build_export_destination(runs, config, summary_runs=summary_runs),
                )
            )
        elif page.name == "Trip Mode":
            tab_views.append(
                (
                    page.name,
                    _build_export_trip_mode(runs, config, summary_runs=summary_runs),
                )
            )
        else:
            page.refresh(force=True)
            if page.view is not None:
                _disable_export_controls(page.view)
                tab_views.append((page.name, page.view))
    tabs = _tabs_from_views(tab_views, dynamic=False)
    export_view = pn.Column(
        pn.pane.Markdown(f"# {config.dashboard_title}"),
        pn.pane.Markdown(
            "**Static export saved-state demo**\n\n"
            "This HTML keeps **Weighted** and **Percent** fixed. Only these existing selectors "
            "remain interactive offline: **Tour Summary > Person Type**, "
            "**Destination > Purpose**, and **Trip Mode > Tour Purpose / Tour Mode**. "
            "All other page selectors are shown but disabled, and no new plots or selectors were added."
        ),
        tabs,
        sizing_mode="stretch_width",
    )
    return export_view, {}


def _disable_export_controls(view: pn.viewable.Viewable) -> None:
    """Disable controls in static export views that are not JS-backed demos."""
    for widget_type in (pn.widgets.Select, pn.widgets.RadioButtonGroup):
        for widget in view.select(widget_type):
            widget.disabled = True


def _build_export_tour_summary(
    runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> pn.viewable.Viewable:
    options = _EXPORT_WIDGET_STATE_SPEC[("Tour Summary", "Person Type")]
    selector = pn.widgets.Select(
        name="Person Type",
        options=options,
        value=options[0],
    )
    bodies = {
        label: _build_tour_summary_body(
            runs,
            config,
            label,
            visible=(label == selector.value),
            summary_runs=summary_runs,
        )
        for label in options
    }
    _attach_single_selector_visibility(selector, bodies)
    return pn.Column(
        pn.pane.Markdown("## Tour Summary"),
        pn.Row(pn.pane.Markdown("**Person Type:**"), selector),
        *bodies.values(),
        sizing_mode="stretch_width",
    )


def _build_export_destination(
    runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> pn.viewable.Viewable:
    options = _EXPORT_WIDGET_STATE_SPEC[("Destination", "Purpose")]
    selector = pn.widgets.Select(
        name="Purpose",
        options=options,
        value=options[0],
    )
    bodies = {
        label: _build_destination_body(
            runs,
            config,
            label,
            visible=(label == selector.value),
            summary_runs=summary_runs,
        )
        for label in options
    }
    _attach_single_selector_visibility(selector, bodies)
    return pn.Column(
        pn.pane.Markdown("## Destination Choice (NM Tour Distances)"),
        pn.Row(pn.pane.Markdown("**Purpose:**"), selector),
        *bodies.values(),
        sizing_mode="stretch_width",
    )


def _build_export_trip_mode(
    runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> pn.viewable.Viewable:
    purpose_options = _EXPORT_WIDGET_STATE_SPEC[("Trip Mode", "Tour Purpose")]
    mode_options = _EXPORT_WIDGET_STATE_SPEC[("Trip Mode", "Tour Mode")]
    purpose_selector = pn.widgets.Select(
        name="Tour Purpose",
        options=purpose_options,
        value=purpose_options[0],
    )
    mode_selector = pn.widgets.Select(
        name="Tour Mode",
        options=mode_options,
        value=mode_options[0],
    )
    bodies = {
        (purpose, mode): _build_trip_mode_body(
            runs,
            config,
            purpose,
            mode,
            visible=(purpose == purpose_selector.value and mode == mode_selector.value),
            summary_runs=summary_runs,
        )
        for purpose in purpose_options
        for mode in mode_options
    }
    _attach_dual_selector_visibility(purpose_selector, mode_selector, bodies)
    return pn.Column(
        pn.pane.Markdown("## Trip Mode Choice"),
        pn.Row(purpose_selector, mode_selector),
        *bodies.values(),
        sizing_mode="stretch_width",
    )


def _build_tour_summary_body(
    runs: list[tuple[str, RunData]],
    config: Config,
    person_type: str,
    visible: bool,
    summary_runs: list[SummaryRun] | None = None,
) -> pn.Column:
    page = TourSummaryPage(
        DashboardState(
            runs, summary_runs=summary_runs, weighting_modes=config.weighting_modes
        ),
        config,
    )
    page.ptype_sel.value = person_type
    page.refresh(force=True)
    return pn.Column(
        *list(page._body.objects), sizing_mode="stretch_width", visible=visible
    )


def _build_destination_body(
    runs: list[tuple[str, RunData]],
    config: Config,
    purpose: str,
    visible: bool,
    summary_runs: list[SummaryRun] | None = None,
) -> pn.Column:
    page = DestinationPage(
        DashboardState(
            runs, summary_runs=summary_runs, weighting_modes=config.weighting_modes
        ),
        config,
    )
    page.purp_sel.value = purpose
    page.refresh(force=True)
    return pn.Column(
        *list(page._body.objects), sizing_mode="stretch_width", visible=visible
    )


def _build_trip_mode_body(
    runs: list[tuple[str, RunData]],
    config: Config,
    purpose: str,
    mode: str,
    visible: bool,
    summary_runs: list[SummaryRun] | None = None,
) -> pn.Column:
    page = TripModePage(
        DashboardState(
            runs, summary_runs=summary_runs, weighting_modes=config.weighting_modes
        ),
        config,
    )
    page.purp_sel.value = purpose
    page.tmode_sel.value = mode
    page.refresh(force=True)
    return pn.Column(
        *list(page._body.objects), sizing_mode="stretch_width", visible=visible
    )


def _attach_single_selector_visibility(
    selector: pn.widgets.Select,
    bodies: dict[str, pn.Column],
) -> None:
    args = {f"body_{i}": body for i, body in enumerate(bodies.values())}
    code = "\n".join(
        f"body_{i}.visible = source.value === {json.dumps(label)};"
        for i, label in enumerate(bodies)
    )
    selector.jscallback(args=args, value=code)


def _attach_dual_selector_visibility(
    purpose_selector: pn.widgets.Select,
    mode_selector: pn.widgets.Select,
    bodies: dict[tuple[str, str], pn.Column],
) -> None:
    args = {
        "purpose_selector": purpose_selector,
        "mode_selector": mode_selector,
        **{f"body_{i}": body for i, body in enumerate(bodies.values())},
    }
    code_lines = [
        "const purpose = purpose_selector.value;",
        "const mode = mode_selector.value;",
    ]
    for i, (purpose, mode) in enumerate(bodies):
        code_lines.append(
            f"body_{i}.visible = purpose === {json.dumps(purpose)} && mode === {json.dumps(mode)};"
        )
    code = "\n".join(code_lines)
    purpose_selector.jscallback(args=args, value=code)
    mode_selector.jscallback(args=args, value=code)


def _color(idx: int) -> str:
    return run_color(idx)
