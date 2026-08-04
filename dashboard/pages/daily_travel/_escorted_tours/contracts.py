"""Stable contracts and copy for the Escorted Tours page."""

STUDENT_ESCORT_TYPE_ORDER = [
    "not_escorted",
    "pure_escort",
    "ride_share",
]
CORE_SUMMARY_IDS = (
    "escorted_tour_totals",
    "school_escorted_tours_by_escort_type_and_direction",
    "adult_escort_event_stop_distribution",
    "adult_escorted_tours_by_person_type_and_direction",
    "adult_escorted_tour_distance_distribution_by_direction",
    "adult_escorted_trip_distance_distribution_by_direction",
)
OPTIONAL_SUMMARY_IDS = (
    "student_school_escort_status_by_direction",
    "student_households_by_student_count",
    "households_with_school_escorting_by_student_count_and_direction",
    "schoolkids_per_escorted_tour_by_student_count_and_direction",
)
STOP_SEGMENT_LABELS = {
    "outbound_before_dropoff": "Adult Escort Stops Before Dropoff - Outbound",
    "outbound_after_dropoff": "Adult Escort Stops After Dropoff - Outbound",
    "inbound_before_pickup": "Adult Escort Stops Before Pickup - Inbound",
    "inbound_after_pickup": "Adult Escort Stops After Pickup - Inbound",
}
STUDENT_ESCORT_DESCRIPTION = (
    "Student school tours by escort type. `Both Directions` means the same child "
    "school tour is escorted in both outbound and inbound directions."
)
HOUSEHOLD_ESCORT_DESCRIPTION = (
    "Households with school escorting by number of students per household. "
    "A household counts if it has at least one escorted school tour in the "
    "selected direction."
)
SCHOOLKIDS_DESCRIPTION = (
    "Average number of escortees on adult chauffer tours, grouped by number of students "
    "in the household. `Both Directions` only counts chauffer tours where "
    "escorting occurred in both directions."
)
STOP_DISTRIBUTION_DESCRIPTION = (
    "Number of stops before and after the dropoff/pickup on each adult chauffeur trip. "
)
PERSON_TYPE_DESCRIPTION = (
    "Adult chauffeur tours by person type. `Both Directions` means the "
    "chauffer escorted in both outbound and inbound directions."
)
DISTANCE_DESCRIPTION = (
    "Distance distributions for adult chauffeur tours and trips. "
    "`Both Directions` means the chauffer escorted in both outbound and inbound "
    "directions."
)
