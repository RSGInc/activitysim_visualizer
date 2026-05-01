"""Stop-related dashboard page group."""

from dashboard.page_definitions import DashboardGroupDefinition

GROUP = DashboardGroupDefinition(
    group_id="stops",
    title="Stops",
    order=90,
    default_page_id="stop_frequency",
)

