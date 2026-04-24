"""Long-Term Choices-related dashboard page group."""

from dashboard.page_definitions import DashboardGroupDefinition

GROUP = DashboardGroupDefinition(
    group_id="long_term_choices",
    title="Long-Term Choices",
    order=80,
    default_child_id="individual_choices",
)
