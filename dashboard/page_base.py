"""Small public facade for dashboard page authors."""

from dashboard.page_declarations import (
    PAGE_SELECTOR_STYLESHEET,
    RegisteredPageSection,
    RegisteredPageSelector,
    SectionContent,
)
from dashboard.page_features import PageFeature
from dashboard.page_lifecycle import DashboardPage
from dashboard.page_navigation import GroupedDashboardPage

__all__ = [
    "DashboardPage",
    "GroupedDashboardPage",
    "PageFeature",
    "PAGE_SELECTOR_STYLESHEET",
    "RegisteredPageSection",
    "RegisteredPageSelector",
    "SectionContent",
]
