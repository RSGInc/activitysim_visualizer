"""Trip-related dashboard page group."""

from dashboard.page_definitions import DashboardGroupDefinition

GROUP = DashboardGroupDefinition(
    group_id="trip_summaries",
    title="Trip Summaries",
    order=70,
    default_page_id="trip_stop_purpose",
)
