"""Mandatory location choice page."""

from __future__ import annotations

from dashboard import DashboardPage, dashboard_page

from ._mandatory_location_choice import *
from ._mandatory_location_choice.composition import MandatoryLocationCompositionMixin
from ._mandatory_location_choice.domains import MandatoryLocationDomainMixin
from ._mandatory_location_choice.features import MandatoryLocationFeatureMixin


@dashboard_page(
    page_id="mandatory_location_choice",
    title="Mandatory Location Choice",
    group_id="long_term_choices",
    order=27,
    required_summary_ids=(
        "internal_external_worker_by_geography",
        "external_worker_workplace_locations",
        "work_location_distance_distribution_by_geography",
        "school_location_distance_distribution_by_geography",
        "university_location_distance_distribution_by_geography",
        "work_from_home_rate_by_geography",
        "telecommute_frequency_distribution",
        "average_mandatory_tour_distance_by_purpose_and_geography",
    ),
)
class MandatoryLocationChoicePage(
    MandatoryLocationCompositionMixin,
    MandatoryLocationDomainMixin,
    MandatoryLocationFeatureMixin,
    DashboardPage,
):
    pass
