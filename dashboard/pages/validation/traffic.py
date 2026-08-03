"""Traffic validation page with count and screenline comparison charts."""

from __future__ import annotations

from dashboard import DashboardPage, dashboard_page

from ._traffic import *
from ._traffic.composition import TrafficPageCompositionMixin
from ._traffic.features import TrafficFeatureMixin
from ._traffic.selector_domains import TrafficSelectorDomainsMixin


@dashboard_page(
    page_id="traffic",
    title="Traffic Validation",
    group_id="validation",
    order=52,
    required_summary_ids=("screenline_flow_comparisons",),
    optional_summary_ids=(
        "link_validation_summary",
        "count_location_counts_validation_summary",
        "count_location_volumes_validation_summary",
        "count_location_scatter_validation_summary",
        "count_location_fit_validation_summary",
    ),
)
class TrafficValidationPage(
    TrafficPageCompositionMixin,
    TrafficFeatureMixin,
    TrafficSelectorDomainsMixin,
    DashboardPage,
):
    pass
