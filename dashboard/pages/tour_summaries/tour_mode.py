"""Tour mode page."""

from __future__ import annotations

from dashboard import DashboardPage, dashboard_page

from ._tour_mode import *
from ._tour_mode.composition import TourModeCompositionMixin
from ._tour_mode.features import TourModeFeatureMixin
from ._tour_mode.selector_domains import TourModeSelectorDomainsMixin


@dashboard_page(
    page_id="tour_mode",
    title="Tour Mode",
    group_id="tour_summaries",
    order=42,
    required_summary_ids=(
        "tour_mode_by_tour_purpose_and_auto_sufficiency",
        "allocated_vehicle_age_by_occupancy",
        "allocated_vehicle_fuel_type_by_occupancy",
        "allocated_vehicle_body_type_by_occupancy",
    ),
)
class TourModePage(
    TourModeCompositionMixin,
    TourModeSelectorDomainsMixin,
    TourModeFeatureMixin,
    DashboardPage,
):
    """Render tour mode splits and allocated vehicle characteristics."""

    TOTAL_PURPOSE_LABEL = "All Tour Purposes"
