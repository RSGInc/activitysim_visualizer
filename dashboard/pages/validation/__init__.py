"""Validation-related dashboard page group."""

from dashboard.page_definitions import DashboardGroupDefinition

GROUP = DashboardGroupDefinition(
    group_id="validation",
    title="Validation Summaries",
    order=80,
    default_page_id="traffic",
)
