"""Skim summaries dashboard page group."""

from dashboard.page_definitions import DashboardGroupDefinition

GROUP = DashboardGroupDefinition(
    group_id="skim_summaries",
    title="Skim Summaries",
    order=50,
    default_page_id="tour_skims",
)
