"""ActivitySim Panel dashboard - main app assembly."""

from __future__ import annotations

import panel as pn

from dashboard import DashboardState
from dashboard.components import run_color, set_percent_mode, set_run_colors
from dashboard.page_registry import (
    build_dashboard_raw_run_provider,
    build_registered_live_pages,
)
from runtime.config import Config
from runtime.models import RunData
from summarize.cache import SummaryRun

pn.extension("plotly", "tabulator", sizing_mode="stretch_width")
pn.config.raw_css.append("""
.bk-root { font-family: Inter, 'Segoe UI', Arial, sans-serif; }
.bk-tab { font-weight: 600; }
.bk-tabs-header { margin-bottom: 12px; }
.pn-loading.arc:before { border-width: 3px; }
.bk-btn-group .bk-btn { border-width: 1.5px; font-weight: 600; }
.bk-btn-group .bk-btn.bk-active { box-shadow: inset 0 0 0 2px rgba(0,0,0,.15); }
""")


def _color(idx: int) -> str:
    return run_color(idx)


def build_dashboard(
    runs: list[tuple[str, RunData]],
    config: Config,
    # static_export: bool = False,
    summary_runs: list[SummaryRun] | None = None,
) -> pn.template.FastListTemplate:
    """Assemble the full Panel dashboard from a list of (label, RunData) tuples."""
    set_run_colors(config.run_colors)
    raw_run_provider = build_dashboard_raw_run_provider(runs, config)
    state = DashboardState(
        summary_runs=summary_runs,
        weighting_modes=config.weighting_modes,
        raw_run_provider=raw_run_provider,
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
    pages = build_registered_live_pages(state, config)
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
    template._dashboard_watchers = watchers
    return template


# STALE: Superseded by build_export_html_document workflow in export_html.py

# def build_export_view(
#     runs: list[tuple[str, RunData]],
#     config: Config,
#     summary_runs: list[SummaryRun] | None = None,
# ) -> tuple[pn.viewable.Viewable, dict[pn.widgets.Widget, list[object]]]:
#     """Build a single-file HTML export view with embedded global widget states.

#
#     """
#     set_run_colors(config.run_colors)
#     state = DashboardState(
#         summary_runs=summary_runs,
#         weighting_modes=config.weighting_modes,
#         raw_run_provider=build_dashboard_raw_run_provider(runs, config),
#     )
#     export_weight_values = config.export_html.panel_weighting_values()
#     export_value_values = config.export_html.panel_value_values()
#     state.weight_mode = export_weight_values[0]
#     state.value_mode = export_value_values[0]
#     set_percent_mode(state.value_mode == "Percent")

#     weight_mode = pn.widgets.RadioButtonGroup(
#         name="Weighting",
#         options=export_weight_values,
#         value=state.weight_mode,
#         button_type="primary",
#         width=250,
#         disabled=len(export_weight_values) <= 1,
#     )
#     value_mode = pn.widgets.RadioButtonGroup(
#         name="Values",
#         options=export_value_values,
#         value=state.value_mode,
#         button_type="primary",
#         width=220,
#         disabled=len(export_value_values) <= 1,
#     )

#     pages = build_registered_live_pages(state, config)

#     def _refresh_all_pages() -> None:
#         set_percent_mode(state.value_mode == "Percent")
#         for page in pages:
#             page.mark_stale()
#             page.refresh_if_needed()

#     def _on_weight_widget_change(event) -> None:
#         state.weight_mode = event.new

#     def _on_value_widget_change(event) -> None:
#         state.value_mode = event.new

#     _refresh_all_pages()
#     for page in pages:
#         if page.view is not None:
#             _disable_export_controls(page.view)

#     watchers = [
#         weight_mode.param.watch(_on_weight_widget_change, "value"),
#         value_mode.param.watch(_on_value_widget_change, "value"),
#         state.param.watch(lambda event: _refresh_all_pages(), "weight_mode"),
#         state.param.watch(lambda event: _refresh_all_pages(), "value_mode"),
#     ]

#     tabs = pn.Tabs(
#         *[(page.name, page.view) for page in pages if page.view is not None],
#         dynamic=False,
#     )
#     export_view = pn.Column(
#         pn.pane.Markdown(f"# {config.dashboard_title}"),
#         pn.pane.Markdown(
#             "**Offline export**\n\n"
#             "This HTML embeds only the configured global **Weighting** and **Values** states. "
#             "Page-level selectors are shown for context but disabled offline."
#         ),
#         pn.Row(weight_mode, value_mode),
#         tabs,
#         sizing_mode="stretch_width",
#     )
#     export_view._export_watchers = watchers
#     export_view._export_state = state
#     export_view._export_pages = pages
#     return export_view, {
#         weight_mode: list(export_weight_values),
#         value_mode: list(export_value_values),
#     }


# def _disable_export_controls(view: pn.viewable.Viewable) -> None:
#     """Disable page-local controls in static export views."""
#     for widget in view.select(pn.widgets.Widget):
#         widget.disabled = True
