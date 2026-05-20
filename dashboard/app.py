"""ActivitySim Panel dashboard - main app assembly."""

from __future__ import annotations

import panel as pn

from dashboard import DashboardState
from dashboard.components import (
    build_run_legend_panes,
    set_percent_mode,
    set_run_colors,
    set_run_label_order,
)
from dashboard.page_registry import (
    build_dashboard_prepared_run_provider,
    build_registered_live_pages,
    resolve_live_navigation_entries,
)
from dashboard.page_base import GroupedDashboardPage
from processor.models import RunData
from processor.summarize.cache import SummaryRun
from runtime.config import Config

pn.extension("plotly", "tabulator", sizing_mode="stretch_width")
pn.config.raw_css.append("""
.bk-root { font-family: Inter, 'Segoe UI', Arial, sans-serif; }
.bk-tab { font-weight: 600; }
.bk-tabs-header { margin-bottom: 12px; }
.pn-loading.arc:before { border-width: 3px; }
.bk-btn-group .bk-btn { border-width: 1.5px; font-weight: 600; }
.bk-btn-group .bk-btn.bk-active { box-shadow: inset 0 0 0 2px rgba(0,0,0,.15); }
""")


def build_dashboard(
    prepared_runs: list[tuple[str, RunData]],
    config: Config,
    # static_export: bool = False,
    summary_runs: list[SummaryRun] | None = None,
) -> pn.template.FastListTemplate:
    """Assemble the full Panel dashboard from a list of (label, RunData) tuples."""
    set_run_colors(config.run_colors)
    prepared_run_provider = build_dashboard_prepared_run_provider(prepared_runs, config)
    state = DashboardState(
        summary_runs=summary_runs,
        weighting_modes=config.weighting_modes,
        prepared_run_provider=prepared_run_provider,
        dashboard_segmentation_type=config.segmentation.dashboard.segmentation_type,
        default_segmentation_visibility=config.segmentation.dashboard.visibility,
    )
    run_labels = state.run_labels
    set_run_label_order(run_labels)

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
    # if static_export:
    #     weight_mode.disabled = True
    #     value_mode.disabled = True
    #     set_percent_mode(True)
    #     pages = build_registered_live_pages(state, config)
    #     for page in pages:
    #         page.mark_stale()
    #         page.refresh_if_needed()
    #         if page.view is not None:
    #             _disable_export_controls(page.view)
    #     main_content = pn.Tabs(
    #         *[(page.name, page.view) for page in pages if page.view is not None],
    #         dynamic=False,
    #     )
    #     watchers = []
    # else:
    leaf_pages = build_registered_live_pages(state, config)
    leaf_page_by_id = {page.page_id(): page for page in leaf_pages}
    pages = []
    for entry in resolve_live_navigation_entries(config):
        child_pages = [
            leaf_page_by_id[page_definition.page_id]
            for page_definition in entry.page_definitions
        ]
        if entry.group_definition is None:
            pages.append(child_pages[0])
            continue
        pages.append(
            GroupedDashboardPage(
                entry.group_definition.group_id,
                entry.title,
                child_pages,
                default_child_page_id=entry.group_definition.default_page_id,
            )
        )
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
        *build_run_legend_panes(run_labels),
        pn.layout.Divider(),
        pn.pane.Markdown("## Display Options"),
        pn.pane.HTML(
            "<div style='font-size:12px;color:#666;margin-bottom:4px'>"
            "Display mode controls." + "</div>"
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
    template._dashboard_leaf_pages = leaf_pages
    template._dashboard_watchers = watchers
    return template
