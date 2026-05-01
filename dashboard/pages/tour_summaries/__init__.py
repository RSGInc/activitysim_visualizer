"""Tour-related dashboard page group."""

from dashboard.page_definitions import DashboardGroupDefinition

GROUP = DashboardGroupDefinition(
    group_id="tour_summaries",
    title="Tour Summaries",
    order=60,
    default_page_id="tour_purpose",
)

