"""Stable VMT summary, selector, and chart contracts."""

EXTERNAL_TOD_ORDER = ["EA", "AM", "MD", "PM", "EV", "EV1", "EV2"]
EXTERNAL_COMMERCIAL_COLUMNS = ["car", "mu", "su"]
EXTERNAL_COMMERCIAL_BREAKDOWN_OPTIONS = ["Time Period", "Commercial Vehicle Type"]
EXTERNAL_COMMERCIAL_DAILY_PERIOD = "Daily"
EXTERNAL_COMMERCIAL_TIME_ORDER = [*EXTERNAL_TOD_ORDER, EXTERNAL_COMMERCIAL_DAILY_PERIOD]
COMMERCIAL_VEHICLE_TYPE_CATEGORY_ID = "commercial_vehicle_type"
EXTERNAL_TRAVEL_COLUMNS = [
    "hbcoll",
    "hbo",
    "hbr",
    "hbs",
    "hbsch",
    "hbw",
    "nhbnw",
    "nhbw",
    "truck",
]
EXTERNAL_TRAVEL_TOTAL_COLUMN = "Total"
EXTERNAL_TRAVEL_BREAKDOWN_OPTIONS = ["Time Period", "Trip Purpose"]
EXTERNAL_TRAVEL_PURPOSE_CATEGORY_ID = "trip_purpose"
PERSONAL_AUTO_VMT_SUMMARY_ID = "auto_vmt_by_home_geography_income_hhsize_time_period"
NON_MOTORIZED_VMT_SUMMARY_ID = (
    "non_motorized_vmt_by_home_geography_income_hhsize_time_period"
)
EXTERNAL_VMT_SUMMARY_ID = "external_vmt_validation_summary"
COMMERCIAL_VMT_SUMMARY_ID = "commercial_vehicle_vmt_validation_summary"
PERSONAL_AUTO_VMT_REQUIRED_COLUMNS = (
    "geography_type",
    "geography_id",
    "income_segment",
    "household_size",
    "time_period",
    "auto_vmt",
    "trip_count",
    "distance_source",
    "time_period_source",
)
NON_MOTORIZED_VMT_REQUIRED_COLUMNS = (
    "geography_type",
    "geography_id",
    "income_segment",
    "household_size",
    "time_period",
    "mode",
    "non_motorized_vmt",
    "trip_count",
    "distance_source",
    "time_period_source",
)
PERSONAL_AUTO_VMT_ALL_MODES = "All Auto"
PERSONAL_AUTO_VMT_MODE_CATEGORY_ID = "mode"
NON_MOTORIZED_VMT_MODE_ORDER = ["WALK", "BIKE", "EBIKE"]
PERSONAL_AUTO_VMT_BREAKDOWN_COLUMNS = {
    "Time Period": "time_period",
    "Mode": "mode",
    "Income Segment": "income_segment",
    "Household Size": "household_size",
    "Home Geography": "geography_id",
}
PERSONAL_AUTO_VMT_BREAKDOWN_AXIS_TITLES = {
    "Time Period": "Time Period",
    "Mode": "Mode",
    "Income Segment": "Income Segment",
    "Household Size": "Household Size",
    "Home Geography": "Home Geography",
}
PERSONAL_AUTO_VMT_TIME_ORDER = ["EA", "AM", "MD", "PM", "EV", "EV1", "EV2", "Daily"]
PERSONAL_AUTO_VMT_MODE_ORDER = ["SOV", "HOV2", "HOV3"]
PERSONAL_AUTO_VMT_TOP_GEOGRAPHIES = 25
VMT_OVERVIEW_ROWS = ("Personal Auto", "Non-Motorized", "External", "Commercial")
