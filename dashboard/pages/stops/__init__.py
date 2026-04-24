"""Stop-related dashboard page group."""

from dashboard.page_definitions import DashboardGroupDefinition

GROUP = DashboardGroupDefinition(
    group_id="stops",
    title="Stops",
    order=80,
    default_child_id="frequency",
)
