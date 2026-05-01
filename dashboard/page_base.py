"""Base classes for persistent Panel dashboard pages."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

import panel as pn

from activitysim_viz_logging import get_logger
from dashboard import DashboardState
from dashboard.components import data_unavailable_card
from dashboard.data_access import (
    DashboardDataSelection,
    VisualizationDiagnostic,
    VisualizationInputResult,
    VisualizationRunAvailability,
)
from runtime.config import Config

if TYPE_CHECKING:
    from dashboard.page_definitions import DashboardPageDefinition

LOGGER = get_logger("dashboard.page")

SectionContent = (
    pn.viewable.Viewable
    | list[pn.viewable.Viewable]
    | tuple[pn.viewable.Viewable, ...]
)


@dataclass(frozen=True)
class RegisteredPageSelector:
    selector_id: str
    widget: pn.widgets.Widget
    label: str
    exportable: bool = True


@dataclass
class RegisteredPageSection:
    section_id: str
    container: pn.Column
    selector_ids: tuple[str, ...]
    export: bool
    render: Callable[[], SectionContent]
    dirty: bool = True


class DashboardPage:
    """Persistent controller for one dashboard page.

    Pages own widget instances, page-local cached views, and the summary/prepared-run
    lookups needed to refresh their visible Panel layout.
    """

    definition: DashboardPageDefinition | None = None

    def __init__(self, *args) -> None:
        if len(args) == 2:
            state, config = args
            definition = self.definition
            derived_name = definition.title if definition is not None else type(self).__name__
        elif len(args) == 3:
            derived_name, state, config = args
        else:
            raise TypeError(
                "DashboardPage expects (state, config) or legacy (name, state, config)."
            )
        if not isinstance(state, DashboardState):
            raise TypeError("DashboardPage requires a DashboardState instance.")
        if not isinstance(config, Config):
            raise TypeError("DashboardPage requires a Config instance.")

        name = str(derived_name)
        self.name = name
        self.state = state
        self.config = config
        self._page_state = state.get_page_state(name)
        self.view: pn.viewable.Viewable | None = None
        self._registered_selectors: dict[str, RegisteredPageSelector] = {}
        self._registered_sections: dict[str, RegisteredPageSection] = {}
        self._selector_ids_by_widget_id: dict[int, str] = {}
        self._is_refreshing = False
        self._queued_selector_ids: set[str] = set()
        self._active_section_id: str | None = None

        if type(self).build_page is not DashboardPage.build_page:
            self.view = self.build_page()
            self._validate_registered_components()

    def refresh_if_needed(self) -> None:
        """Refresh the page when its rendered global state is stale."""
        if self._page_state.get("last_rendered_state") != self.state.global_state_key():
            self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        """Refresh the page content."""
        current_state_key = self.state.global_state_key()
        last_state_key = self._page_state.get("last_rendered_state")
        global_state_changed = force or last_state_key != current_state_key
        if not force and not global_state_changed and not self._dirty_sections():
            return
        self._page_state["visualization_diagnostics"] = []
        if self._registered_sections:
            if global_state_changed:
                self.on_global_state_changed()
                for section in self._registered_sections.values():
                    section.dirty = True
            self._refresh_registered_sections()
        else:
            self._active_section_id = None
            self._refresh()
        self._page_state["last_rendered_state"] = current_state_key

    def mark_stale(self) -> None:
        """Mark the page stale so the next activation refreshes it."""
        self._page_state["last_rendered_state"] = None
        for section in self._registered_sections.values():
            section.dirty = True

    def mark_section_stale(self, *section_ids: str) -> None:
        """Mark one or more registered sections stale."""
        for section_id in section_ids:
            section = self._registered_sections.get(section_id)
            if section is None:
                raise KeyError(f"Unknown section id {section_id!r} on page {self.name!r}.")
            section.dirty = True

    def build_page(self) -> pn.viewable.Viewable:
        raise NotImplementedError

    def sync_controls(self) -> None:
        """Update selector options/values before rendering dirty sections."""

    def on_global_state_changed(self) -> None:
        """Hook for page-local cache invalidation on global dashboard state changes."""

    def selector(
        self,
        selector_id: str,
        *,
        widget: pn.widgets.Widget,
        label: str,
        exportable: bool = True,
    ) -> pn.widgets.Widget:
        """Register one page-local selector widget."""
        if selector_id in self._registered_selectors:
            raise ValueError(
                f"Dashboard page {self.name!r} declares duplicate selector id {selector_id!r}."
            )
        selector = RegisteredPageSelector(
            selector_id=selector_id,
            widget=widget,
            label=label,
            exportable=exportable,
        )
        self._registered_selectors[selector_id] = selector
        self._selector_ids_by_widget_id[id(widget)] = selector_id
        widget.param.watch(
            lambda event, sid=selector_id: self._handle_selector_change(sid),
            "value",
        )
        return widget

    def section(
        self,
        section_id: str,
        *,
        selectors: tuple[str, ...] = (),
        export: bool = True,
        render: Callable[[], SectionContent],
    ) -> pn.Column:
        """Register one stable page section."""
        if section_id in self._registered_sections:
            raise ValueError(
                f"Dashboard page {self.name!r} declares duplicate section id {section_id!r}."
            )
        unknown_selectors = [
            selector_id
            for selector_id in selectors
            if selector_id not in self._registered_selectors
        ]
        if unknown_selectors:
            raise ValueError(
                f"Dashboard page {self.name!r} section {section_id!r} references unknown selectors: "
                + ", ".join(repr(selector_id) for selector_id in unknown_selectors)
            )
        container = self.new_section()
        self._registered_sections[section_id] = RegisteredPageSection(
            section_id=section_id,
            container=container,
            selector_ids=tuple(selectors),
            export=export,
            render=render,
        )
        return container

    def section_view(self, section_id: str) -> pn.Column:
        section = self._registered_sections.get(section_id)
        if section is None:
            raise KeyError(f"Unknown section id {section_id!r} on page {self.name!r}.")
        return section.container

    @property
    def registered_selectors(self) -> tuple[RegisteredPageSelector, ...]:
        return tuple(self._registered_selectors.values())

    @property
    def registered_sections(self) -> tuple[RegisteredPageSection, ...]:
        return tuple(self._registered_sections.values())

    def _dirty_sections(self) -> tuple[RegisteredPageSection, ...]:
        return tuple(
            section for section in self._registered_sections.values() if section.dirty
        )

    def _handle_selector_change(self, selector_id: str) -> None:
        if self._is_refreshing:
            self._queued_selector_ids.add(selector_id)
            return
        self._mark_sections_for_selectors({selector_id})
        self.refresh(force=False)

    def _mark_sections_for_selectors(self, selector_ids: set[str]) -> None:
        for section in self._registered_sections.values():
            if selector_ids.intersection(section.selector_ids):
                section.dirty = True

    def _refresh_registered_sections(self) -> None:
        self._is_refreshing = True
        try:
            rerun_requested = False
            for _ in range(2):
                self._queued_selector_ids.clear()
                self.sync_controls()
                dirty_sections = list(self._dirty_sections())
                if not dirty_sections and not self._queued_selector_ids:
                    break
                for section in dirty_sections:
                    self._render_section(section)
                    section.dirty = False
                if not self._queued_selector_ids:
                    break
                self._mark_sections_for_selectors(set(self._queued_selector_ids))
                rerun_requested = True
            if rerun_requested:
                self._queued_selector_ids.clear()
        finally:
            self._is_refreshing = False

    def _render_section(self, section: RegisteredPageSection) -> None:
        previous_section_id = self._active_section_id
        self._active_section_id = section.section_id
        try:
            rendered = section.render()
        finally:
            self._active_section_id = previous_section_id
        if isinstance(rendered, pn.viewable.Viewable):
            objects = [rendered]
        else:
            objects = list(rendered)
        section.container.objects = objects

    def _validate_registered_components(self) -> None:
        if self.view is None:
            raise ValueError(f"Dashboard page {self.name!r} build_page() returned no view.")
        if not isinstance(self.view, pn.viewable.Viewable):
            raise TypeError(
                f"Dashboard page {self.name!r} build_page() must return a Panel viewable."
            )

    def _watch_widget(self, widget: pn.widgets.Widget) -> None:
        """Legacy helper for pages that have not migrated to selector()."""
        widget.param.watch(lambda event: self.refresh(force=True), "value")

    def new_section(self, *objects, **kwargs) -> pn.Column:
        """Create a stable page section container that can be refreshed in place."""
        kwargs.setdefault("sizing_mode", "stretch_width")
        return pn.Column(*objects, **kwargs)

    @property
    def as_percent(self) -> bool:
        """Return whether the current display mode should show percentages."""
        return self.state.value_mode == "Percent"

    @property
    def weighting_key(self) -> str:
        """Return the current weighting key used for summary-table lookup."""
        return self.state.weighting_key()

    @classmethod
    def page_id(cls) -> str | None:
        """Return the registered page id when one has been assigned."""
        return cls.definition.page_id if cls.definition is not None else None

    @classmethod
    def page_title(cls) -> str | None:
        """Return the registered page title when one has been assigned."""
        return cls.definition.title if cls.definition is not None else None

    @property
    def required_summary_ids(self) -> tuple[str, ...]:
        if self.definition is None:
            return ()
        return self.definition.required_summary_ids

    @property
    def prepared_data_mode(self) -> str:
        if self.definition is None:
            return "none"
        return self.definition.prepared_data_mode

    def _warn_once(self, key: str, message: str) -> None:
        warnings = self._page_state.setdefault("warnings_emitted", set())
        if key in warnings:
            return
        LOGGER.warning(message)
        warnings.add(key)

    def data_not_available_card(
        self,
        *,
        detail: str,
        missing_items: list[str] | tuple[str, ...] | None = None,
        title: str = "Data Not Available",
    ) -> pn.Card:
        effective_title = title
        effective_detail = detail
        if missing_items:
            effective_detail = self._augment_missing_data_detail(detail, missing_items)
            if title == "Data Not Available":
                statuses = self._missing_item_statuses(missing_items)
                if statuses and statuses == {"empty"}:
                    effective_title = "Data Empty"
                elif statuses and statuses == {"schema_mismatch"}:
                    effective_title = "Schema Mismatch"
                elif statuses and statuses == {"failed"}:
                    effective_title = "Data Failed"
        return data_unavailable_card(
            effective_title,
            effective_detail,
            missing_items=missing_items,
        )

    @property
    def missing_data_display(self) -> str:
        return self.config.missing_data_display

    @property
    def visualization_diagnostics(self) -> list[VisualizationDiagnostic]:
        return list(self._page_state.get("visualization_diagnostics", []))

    def _record_visualization_diagnostic(
        self,
        result: VisualizationInputResult,
    ) -> None:
        render_state = "rendered"
        if not result.has_usable_runs:
            render_state = "skipped"
        elif result.excluded_runs:
            render_state = "partial"
        diagnostics = self._page_state.setdefault("visualization_diagnostics", [])
        diagnostics.append(
            VisualizationDiagnostic(
                visualization_id=result.visualization_id,
                render_state=render_state,
                input_kind=result.input_kind,
                input_ids=result.input_ids,
                usable_run_labels=tuple(
                    label
                    for label, _ in next(iter(result.usable_by_input.values()), [])
                ),
                excluded_runs=tuple(result.excluded_runs),
            )
        )

    def _combine_selections(
        self,
        visualization_id: str,
        selections: dict[str, DashboardDataSelection],
    ) -> VisualizationInputResult:
        usable_labels_by_input = {
            input_id: {label for label, _ in selection.usable_runs}
            for input_id, selection in selections.items()
        }
        common_labels = (
            set.intersection(*usable_labels_by_input.values())
            if usable_labels_by_input
            else set()
        )
        usable_by_input = {
            input_id: [
                (label, value)
                for label, value in selection.usable_runs
                if label in common_labels
            ]
            for input_id, selection in selections.items()
        }
        excluded_by_key: dict[tuple[str, str, str], VisualizationRunAvailability] = {}
        for selection in selections.values():
            for issue in selection.excluded_runs:
                excluded_by_key[(issue.label, issue.source_kind, issue.source_id)] = issue
            for label, _ in selection.usable_runs:
                if label in common_labels:
                    continue
                excluded_by_key[(label, selection.source_kind, selection.source_id)] = (
                    VisualizationRunAvailability(
                        label=label,
                        status="missing",
                        detail="required alongside another unavailable input for this visualization",
                        source_kind=selection.source_kind,
                        source_id=selection.source_id,
                    )
                )
        input_kinds = {selection.source_kind for selection in selections.values()}
        input_kind = (
            next(iter(input_kinds)) if len(input_kinds) == 1 else "mixed"
        )
        result = VisualizationInputResult(
            visualization_id=visualization_id,
            input_kind=input_kind,
            usable_by_input=usable_by_input,
            excluded_runs=list(excluded_by_key.values()),
            input_ids=tuple(selections),
        )
        self._record_visualization_diagnostic(result)
        return result

    def resolve_summary_visualization(
        self,
        visualization_id: str,
        *,
        summary_requirements: dict[str, tuple[str, ...]],
        weighting_key: str | None = None,
    ) -> VisualizationInputResult:
        selections = {
            summary_name: self.state.inspect_summary_table(
                summary_name,
                weighting_key=weighting_key or self.weighting_key,
                required_columns=required_columns,
            )
            for summary_name, required_columns in summary_requirements.items()
        }
        return self._combine_selections(visualization_id, selections)

    def resolve_prepared_visualization(
        self,
        visualization_id: str,
        *,
        table_requirements: dict[str, tuple[str, ...]],
        weighted: bool | None = None,
    ) -> VisualizationInputResult:
        selections = {
            table_name: self.state.inspect_prepared_table(
                table_name,
                weighted=weighted,
                required_columns=required_columns,
            )
            for table_name, required_columns in table_requirements.items()
        }
        return self._combine_selections(visualization_id, selections)

    def unavailable_visualization(
        self,
        result: VisualizationInputResult,
        *,
        detail: str,
        title: str = "Data Not Available",
    ) -> pn.viewable.Viewable:
        if self.missing_data_display == "blank":
            return pn.Spacer(height=0)
        missing_items = list(result.input_ids)
        if result.excluded_runs:
            detail = self._format_issue_detail(detail, result.excluded_runs)
        return self.data_not_available_card(
            detail=detail,
            missing_items=missing_items,
            title=title,
        )

    def get_summary(self, summary_name: str):
        """Return one summary table per run for the current weighting mode."""
        return self.state.get_summary_table_set(summary_name, self.weighting_key)

    def has_summary(self, summary_name: str) -> bool:
        return self.state.has_summary_table_set(summary_name, self.weighting_key)

    def require_summary(self, summary_name: str):
        """Return one summary table per run, warning once when unavailable."""
        selection = self.state.inspect_summary_table(
            summary_name,
            weighting_key=self.weighting_key,
        )
        self._page_state.setdefault("required_summary_selections", {})[summary_name] = (
            selection
        )
        if not selection.has_usable_runs:
            self._warn_once(
                f"missing-summary:{summary_name}",
                (
                    f"Warning: dashboard page '{self.name}' requires summary "
                    f"'{summary_name}' for weighting mode '{self.weighting_key}', "
                    "but no usable data was available."
                ),
            )
            return None
        return [(label, table) for label, table in selection.usable_runs]

    def inspect_summary(
        self,
        summary_name: str,
        *,
        required_columns: tuple[str, ...] = (),
    ):
        """Inspect one summary table and store its availability for page diagnostics."""
        selection = self.state.inspect_summary_table(
            summary_name,
            weighting_key=self.weighting_key,
            required_columns=required_columns,
        )
        self._page_state.setdefault("required_summary_selections", {})[summary_name] = (
            selection
        )
        return selection

    def optional_summary(
        self,
        summary_name: str,
        *,
        required_columns: tuple[str, ...] = (),
    ):
        """Return usable rows for one summary or ``None`` when unavailable."""
        selection = self.inspect_summary(
            summary_name,
            required_columns=required_columns,
        )
        if not selection.has_usable_runs:
            return None
        return [(label, table) for label, table in selection.usable_runs]

    def require_summaries(self, *summary_names: str) -> dict[str, Any] | None:
        """Return multiple summary tables or ``None`` when any are missing."""
        selections = {
            summary_name: self.state.inspect_summary_table(
                summary_name,
                weighting_key=self.weighting_key,
            )
            for summary_name in summary_names
        }
        self._page_state["required_summary_selections"] = selections
        missing = [
            summary_name
            for summary_name in summary_names
            if not selections[summary_name].has_usable_runs
        ]
        if missing:
            for summary_name in missing:
                self._warn_once(
                    f"missing-summary:{summary_name}",
                    (
                        f"Warning: dashboard page '{self.name}' requires summary "
                        f"'{summary_name}' for weighting mode '{self.weighting_key}', "
                        "but no usable data was available."
                    ),
                )
            return None
        return {
            summary_name: [
                (label, table)
                for label, table in selections[summary_name].usable_runs
            ]
            for summary_name in summary_names
        }

    def _missing_item_statuses(
        self,
        missing_items: list[str] | tuple[str, ...],
    ) -> set[str]:
        selections = self._page_state.get("required_summary_selections", {})
        statuses: set[str] = set()
        for item in missing_items:
            selection = selections.get(item)
            if selection is None:
                continue
            statuses.update(issue.status for issue in selection.excluded_runs)
        return statuses

    def _augment_missing_data_detail(
        self,
        detail: str,
        missing_items: list[str] | tuple[str, ...],
    ) -> str:
        selections = self._page_state.get("required_summary_selections", {})
        excluded_runs: list[VisualizationRunAvailability] = []
        for item in missing_items:
            selection = selections.get(item)
            if selection is None:
                continue
            excluded_runs.extend(selection.excluded_runs)
        if not excluded_runs:
            return detail
        return self._format_issue_detail(detail, excluded_runs)

    def _format_issue_detail(
        self,
        detail: str,
        issues: list[VisualizationRunAvailability] | tuple[VisualizationRunAvailability, ...],
    ) -> str:
        lines = [detail, "", "Availability details:"]
        by_source: dict[str, list[VisualizationRunAvailability]] = defaultdict(list)
        for issue in issues:
            by_source[issue.source_id].append(issue)

        status_order = {
            "empty": 0,
            "schema_mismatch": 1,
            "unavailable": 2,
            "failed": 3,
            "missing": 4,
        }
        for source_id in sorted(by_source):
            source_issues = by_source[source_id]
            grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
            for issue in source_issues:
                grouped[(issue.status, issue.detail)].append(issue.label)
            for (status, issue_detail), labels in sorted(
                grouped.items(),
                key=lambda item: (
                    status_order.get(item[0][0], 99),
                    item[0][0],
                    item[0][1],
                ),
            ):
                label_list = ", ".join(f"`{label}`" for label in sorted(labels))
                lines.append(
                    f"- `{source_id}` is {status.replace('_', ' ')} for {label_list}: {issue_detail}"
                )
        return "\n".join(lines)

    def get_prepared_runs(self, *, weighted: bool | None = None):
        """Return prepared runs when this dashboard session has loaded them explicitly."""
        return self.state.get_prepared_runs_if_loaded(weighted=weighted)

    def require_prepared_runs(self, *, weighted: bool | None = None):
        """Return prepared runs or warn once when this session does not have them."""
        prepared_runs = self.get_prepared_runs(weighted=weighted)
        if prepared_runs is not None:
            return prepared_runs

        availability = self.state.prepared_run_availability
        reason = (
            "prepared run data was not requested for this dashboard session"
            if availability == "not_requested"
            else "prepared run data is unavailable"
        )
        self._warn_once(
            f"missing-prepared-runs:{availability}",
            (
                f"Warning: dashboard page '{self.name}' requires prepared run data, "
                f"but {reason}."
            ),
        )
        return None

    def get_filtered_view(self, view_name: str, *filters: Any, factory):
        """Return a cached chart-ready filtered view for the current page state."""
        page_cache_id = self.page_id() or self.name
        return self.state.get_or_create_cached(
            "filtered_view",
            page_cache_id,
            self._active_section_id or "*",
            self.weighting_key,
            view_name,
            *filters,
            factory=factory,
        )

    def clear_filtered_view_cache(self) -> None:
        """Clear cached filtered views for this page and weighting mode."""
        page_cache_id = self.page_id() or self.name
        cache = self.state.get_cache("filtered_view")
        prefix = (page_cache_id, self.weighting_key)
        stale_keys = [key for key in cache if key[0] == page_cache_id and key[2] == self.weighting_key]
        for key in stale_keys:
            cache.pop(key, None)

    def _refresh(self) -> None:
        raise NotImplementedError


class GroupedDashboardPage:
    """Top-level navigation wrapper that renders child dashboard pages as tabs."""

    def __init__(
        self,
        group_id: str,
        title: str,
        pages: list[DashboardPage],
        default_child_page_id: str | None = None,
    ) -> None:
        if not pages:
            raise ValueError("GroupedDashboardPage requires at least one child page.")
        self._group_id = group_id
        self.name = title
        self.pages = pages
        self.view = pn.Tabs(
            *[(page.name, page.view) for page in pages],
            dynamic=False,
        )
        self._active_child = self._default_child_index(default_child_page_id)
        self.view.active = self._active_child
        self.view.param.watch(self._on_child_tab_change, "active")

    def _default_child_index(self, default_child_page_id: str | None) -> int:
        if default_child_page_id is None:
            return 0
        for index, page in enumerate(self.pages):
            if page.page_id() == default_child_page_id:
                return index
        return 0

    def _on_child_tab_change(self, event) -> None:
        self._active_child = int(event.new)
        self.refresh_if_needed()

    def page_id(self) -> str:
        return self._group_id

    @property
    def active_child(self) -> DashboardPage:
        return self.pages[self._active_child]

    def refresh_if_needed(self) -> None:
        self.active_child.refresh_if_needed()

    def refresh(self, force: bool = False) -> None:
        self.active_child.refresh(force=force)

    def mark_stale(self) -> None:
        for page in self.pages:
            page.mark_stale()
