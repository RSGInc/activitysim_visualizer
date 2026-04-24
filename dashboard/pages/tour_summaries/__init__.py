"""Tour-related dashboard page group."""

from dashboard.page_definitions import DashboardGroupDefinition

GROUP = DashboardGroupDefinition(
    group_id="tour_summaries",
    title="Tour Summaries",
    order=80,
    default_child_id="tour_purpose",
)
