"""Base classes for persistent Panel dashboard pages."""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from typing import TYPE_CHECKING

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


class DashboardPage:
    """Persistent controller for one dashboard page.

    Pages own widget instances, page-local cached views, and the summary/prepared-run
    lookups needed to refresh their visible Panel layout.
    """

    definition: DashboardPageDefinition | None = None

    def __init__(self, name: str, state: DashboardState, config: Config) -> None:
        self.name = name
        self.state = state
        self.config = config
        self._page_state = state.get_page_state(name)
        self.view: pn.viewable.Viewable | None = None

    def refresh_if_needed(self) -> None:
        """Refresh the page when its rendered global state is stale."""
        if self._page_state.get("last_rendered_state") != self.state.global_state_key():
            self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        """Refresh the page content."""
        if (
            not force
            and self._page_state.get("last_rendered_state")
            == self.state.global_state_key()
        ):
            return
        self._page_state["visualization_diagnostics"] = []
        self._refresh()
        self._page_state["last_rendered_state"] = self.state.global_state_key()

    def mark_stale(self) -> None:
        """Mark the page stale so the next activation refreshes it."""
        self._page_state["last_rendered_state"] = None

    def _watch_widget(self, widget: pn.widgets.Widget) -> None:
        """Refresh the page when a page-local widget value changes."""
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
        stale_keys = [key for key in cache if key[:2] == prefix]
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
