"""Tour-related dashboard page group."""

from dashboard.page_definitions import DashboardGroupDefinition

GROUP = DashboardGroupDefinition(
    group_id="tours",
    title="Tours",
    order=30,
    default_page_id="tour_summary",
)

