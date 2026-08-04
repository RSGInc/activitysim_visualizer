"""Escorted tours page."""

from __future__ import annotations

from dashboard import DashboardPage, dashboard_page

from ._escorted_tours import *
from ._escorted_tours.composition import EscortedToursCompositionMixin
from ._escorted_tours.domains import EscortedToursDomainMixin
from ._escorted_tours.features import EscortedToursFeatureMixin


@dashboard_page(
    page_id="escorted_tours",
    title="Escorted Tours",
    group_id="daily_travel",
    order=29,
    required_summary_ids=CORE_SUMMARY_IDS,
    optional_summary_ids=OPTIONAL_SUMMARY_IDS,
)
class EscortedToursPage(
    EscortedToursCompositionMixin,
    EscortedToursDomainMixin,
    EscortedToursFeatureMixin,
    DashboardPage,
):
    """Render school escorting and adult chauffeur escorting summaries."""
