"""Shared regression expectations for dashboard page order and titles."""

EXPECTED_DEFAULT_PAGES = [
    ("overview", "Overview"),
    ("daily_travel", "Daily Travel"),
    ("joint_travel", "Joint Travel"),
    ("long_term_choices", "Long-Term Choices"),
    ("tour_summaries", "Tour Summaries"),
    ("trip_summaries", "Trip Summaries"),
    ("validation", "Validation Summaries"),
]

EXPECTED_DEFAULT_LEAF_PAGES = [
    ("overview", "Overview"),
    ("daily_activity_pattern", "Daily Activity Pattern"),
    ("escorted_tours", "Escorted Tours"),
    ("joint_travel", "Joint Travel"),
    ("individual_choices", "Individual Choices"),
    ("vehicle_ownership_type", "Vehicle Ownership and Type"),
    ("mandatory_location_choice", "Mandatory Location Choice"),
    ("shadow_pricing", "Shadow Pricing"),
    ("tour_purpose", "Tour Purpose"),
    ("tour_mode", "Tour Mode"),
    ("tour_time", "Tour Time"),
    ("tour_distance", "Tour Distance"),
    ("tour_stop_frequency", "Tour Stop Frequency"),
    ("internal_external_tours", "Internal vs. External Tours"),
    ("park_and_ride_location", "Park-and-Ride Location"),
    ("trip_stop_purpose", "Trip and Stop Purpose"),
    ("trip_mode", "Trip Mode"),
    ("trip_stop_time", "Trip and Stop Time"),
    ("trip_stop_distance", "Trip and Stop Distance"),
    ("traffic", "Traffic Validation"),
    ("transit", "Transit Validation"),
    ("vmt", "VMT Validation"),
]

EXPECTED_DEFAULT_PAGE_IDS = [page_id for page_id, _ in EXPECTED_DEFAULT_PAGES]
EXPECTED_DEFAULT_PAGE_TITLES = [title for _, title in EXPECTED_DEFAULT_PAGES]
EXPECTED_DEFAULT_LEAF_PAGE_IDS = [page_id for page_id, _ in EXPECTED_DEFAULT_LEAF_PAGES]
EXPECTED_DEFAULT_LEAF_PAGE_TITLES = [title for _, title in EXPECTED_DEFAULT_LEAF_PAGES]
