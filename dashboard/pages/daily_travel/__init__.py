"""Daily Travel-related dashboard page group."""

from dashboard.page_definitions import DashboardGroupDefinition

GROUP = DashboardGroupDefinition(
    group_id="daily_travel",
    title="Daily Travel",
    order=80,
    default_child_id="daily_activity_pattern",
)
