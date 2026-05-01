"""Shared regression expectations for dashboard page order and titles."""

EXPECTED_DEFAULT_PAGES = [
    ("overview", "Overview"),
    ("tours", "Tours"),
    ("joint_travel", "Joint Travel"),
    ("daily_travel", "Daily Travel"),
    ("long_term_choices", "Long-Term Choices"),
    ("tour_summaries", "Tour Summaries"),
    ("trip_summaries", "Trip Summaries"),
    ("validation", "Validation Summaries"),
    ("stops", "Stops"),
]

EXPECTED_DEFAULT_LEAF_PAGES = [
    ("overview", "Overview"),
    ("tour_summary", "Tour Summary"),
    ("tour_tod", "Tour TOD"),
    ("tr_mode", "Old Tour Mode"),
    ("joint_travel", "Joint Travel"),
    ("daily_activity_pattern", "Daily Activity Pattern"),
    ("escorted_tours", "Escorted Tours"),
    ("individual_choices", "Individual Choices"),
    ("internal_external_tours", "Internal vs. External Tours"),
    ("mandatory_location_choice", "Mandatory Location Choice"),
    ("park_and_ride_location", "Park-and-Ride Location"),
    ("parking_location", "Parking Location"),
    ("shadow_pricing", "Shadow Pricing"),
    ("tour_distance", "Tour Distance"),
    ("tour_mode", "Tour Mode"),
    ("tour_purpose", "Tour Purpose"),
    ("tour_stop_frequency", "Tour Stop Frequency"),
    ("tour_time", "Tour Time"),
    ("traffic", "Traffic Validation"),
    ("transit", "Transit Validation"),
    ("trip_mode", "Trip Mode"),
    ("trip_stop_distance", "Trip and Stop Distance"),
    ("trip_stop_purpose", "Trip and Stop Purpose"),
    ("trip_stop_time", "Trip and Stop Time"),
    ("vehicle_ownership_type", "Vehicle Ownership and Type"),
    ("vmt", "VMT Validation"),
    ("stop_frequency", "Stop Frequency"),
    ("stop_location", "Stop Location"),
    ("stop_timing", "Stop Timing"),
]

EXPECTED_DEFAULT_PAGE_IDS = [page_id for page_id, _ in EXPECTED_DEFAULT_PAGES]
EXPECTED_DEFAULT_PAGE_TITLES = [title for _, title in EXPECTED_DEFAULT_PAGES]
EXPECTED_DEFAULT_LEAF_PAGE_IDS = [page_id for page_id, _ in EXPECTED_DEFAULT_LEAF_PAGES]
EXPECTED_DEFAULT_LEAF_PAGE_TITLES = [title for _, title in EXPECTED_DEFAULT_LEAF_PAGES]
