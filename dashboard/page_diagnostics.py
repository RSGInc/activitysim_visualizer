"""Availability diagnostics and standard missing-data presentation for pages."""

from __future__ import annotations

from collections import defaultdict

import panel as pn

from dashboard.data_access import (
    DashboardDataSelection,
    VisualizationDiagnostic,
    VisualizationRunAvailability,
)
from dashboard.rendering import data_unavailable_card
from runtime.logging import get_logger

LOGGER = get_logger("dashboard.page")


class PageDiagnostics:
    """Internal diagnostics behavior mixed into ``DashboardPage``."""

    def _warn_once(self, key: str, message: str) -> None:
        warnings = self._page_state.setdefault("warnings_emitted", set())
        if key in warnings:
            return
        LOGGER.warning(message)
        warnings.add(key)

    def _record_data_selection(
        self, source_id: str, selection: DashboardDataSelection
    ) -> None:
        self._page_state.setdefault("required_summary_selections", {})[source_id] = (
            selection
        )
        render_state = (
            "skipped"
            if not selection.has_usable_runs
            else "partial"
            if selection.excluded_runs
            else "rendered"
        )
        self._page_state.setdefault("visualization_diagnostics", []).append(
            VisualizationDiagnostic(
                visualization_id=source_id,
                render_state=render_state,
                input_kind=selection.source_kind,
                input_ids=(source_id,),
                usable_run_labels=tuple(label for label, _ in selection.usable_runs),
                excluded_runs=tuple(selection.excluded_runs),
            )
        )

    def _warn_missing_summary(self, summary_id: str) -> None:
        self._warn_once(
            f"missing-summary:{summary_id}",
            f"Warning: dashboard page '{self.name}' requires summary '{summary_id}' "
            f"for weighting mode '{self.weighting_key}', but no usable data was available.",
        )

    def _warn_missing_prepared(self) -> None:
        availability = self.state.prepared_run_availability
        reason = (
            "prepared run data was not requested for this dashboard session"
            if availability == "not_requested"
            else "prepared run data is unavailable"
        )
        self._warn_once(
            f"missing-prepared-runs:{availability}",
            f"Warning: dashboard page '{self.name}' requires prepared run data, but {reason}.",
        )

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
                if statuses == {"empty"}:
                    effective_title = "Data Empty"
                elif statuses == {"schema_mismatch"}:
                    effective_title = "Schema Mismatch"
                elif statuses == {"failed"}:
                    effective_title = "Data Failed"
        return data_unavailable_card(
            effective_title, effective_detail, missing_items=missing_items
        )

    def no_runs_message(self) -> pn.pane.Markdown:
        return pn.pane.Markdown("No runs loaded.")

    def summary_only_unavailable_card(
        self,
        *,
        summary_ids: list[str] | tuple[str, ...] | None = None,
        detail: str = "This page only renders from precomputed summary tables.",
        title: str = "Data Not Available",
    ) -> pn.Card:
        return self.data_not_available_card(
            detail=detail,
            missing_items=list(summary_ids or self.required_summary_ids),
            title=title,
        )

    @property
    def missing_data_display(self) -> str:
        return self.config.missing_data_display

    @property
    def visualization_diagnostics(self) -> list[VisualizationDiagnostic]:
        return list(self._page_state.get("visualization_diagnostics", []))

    def _missing_item_statuses(
        self, missing_items: list[str] | tuple[str, ...]
    ) -> set[str]:
        selections = self._page_state.get("required_summary_selections", {})
        return {
            issue.status
            for item in missing_items
            for issue in getattr(selections.get(item), "excluded_runs", ())
        }

    def _augment_missing_data_detail(
        self, detail: str, missing_items: list[str] | tuple[str, ...]
    ) -> str:
        selections = self._page_state.get("required_summary_selections", {})
        issues = [
            issue
            for item in missing_items
            for issue in getattr(selections.get(item), "excluded_runs", ())
        ]
        return self._format_issue_detail(detail, issues) if issues else detail

    def _format_issue_detail(
        self,
        detail: str,
        issues: list[VisualizationRunAvailability]
        | tuple[VisualizationRunAvailability, ...],
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
            grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
            for issue in by_source[source_id]:
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
                    f"- `{source_id}` is {status.replace('_', ' ')} for "
                    f"{label_list}: {issue_detail}"
                )
        return "\n".join(lines)


__all__ = ["PageDiagnostics"]
