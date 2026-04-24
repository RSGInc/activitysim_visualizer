"""Shared regression expectations for dashboard page order and titles."""

EXPECTED_DEFAULT_PAGES = [
    ("overview", "Overview"),
    ("long_term", "Long-Term"),
    ("tours", "Tours"),
    ("joint_tours", "Joint Tours"),
    ("destination", "Destination"),
    ("stops", "Stops"),
    ("trip_mode", "Trip Mode"),
]

EXPECTED_DEFAULT_LEAF_PAGES = [
    ("overview", "Overview"),
    ("long_term", "Long-Term"),
    ("tour_summary", "Tour Summary"),
    ("tour_tod", "Tour TOD"),
    ("tour_mode", "Tour Mode"),
    ("joint_tours", "Joint Tours"),
    ("destination", "Destination"),
    ("stop_frequency", "Stop Frequency"),
    ("stop_location", "Stop Location"),
    ("stop_timing", "Stop Timing"),
    ("trip_mode", "Trip Mode"),
]

EXPECTED_DEFAULT_PAGE_IDS = [page_id for page_id, _ in EXPECTED_DEFAULT_PAGES]
EXPECTED_DEFAULT_PAGE_TITLES = [title for _, title in EXPECTED_DEFAULT_PAGES]
EXPECTED_DEFAULT_LEAF_PAGE_IDS = [page_id for page_id, _ in EXPECTED_DEFAULT_LEAF_PAGES]
EXPECTED_DEFAULT_LEAF_PAGE_TITLES = [title for _, title in EXPECTED_DEFAULT_LEAF_PAGES]
