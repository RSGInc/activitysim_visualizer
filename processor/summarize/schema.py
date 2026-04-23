"""Canonical summary-table output schemas used by dashboard pages."""

from __future__ import annotations

SUMMARY_OUTPUT_COLUMNS: dict[str, tuple[str, ...]] = {
    "tour_stop_frequency_by_tour_purpose": (
        "tour_purpose",
        "outbound_stop_count",
        "inbound_stop_count",
        "total_stop_count",
        "tour_count",
    ),
    "stop_destination_purpose_by_tour_purpose": (
        "stop_destination_purpose",
        "tour_purpose",
        "stop_count",
    ),
    "stop_out_of_direction_distance_by_tour_purpose": (
        "tour_purpose",
        "distance_bin",
        "stop_count",
    ),
    "trip_departure_time_by_purpose": (
        "tour_purpose",
        "time_bin",
        "departure_trip_count",
        "departure_stop_count",
    ),
    "trip_mode_by_tour_purpose_and_tour_mode": (
        "tour_purpose",
        "tour_mode",
        "trip_mode",
        "trip_count",
    ),
    "tour_mode_by_tour_purpose_and_auto_sufficiency": (
        "tour_purpose",
        "tour_mode",
        "tour_count_zero_auto",
        "tour_count_auto_deficient",
        "tour_count_auto_sufficient",
        "tour_count_all_households",
    ),
    "tour_time_of_day_by_tour_purpose": (
        "time_bin",
        "tour_purpose",
        "departure_tour_count",
        "arrival_tour_count",
        "duration_tour_count",
    ),
    "destination_distance": ("purpose", "distbin", "freq"),
    "destination_average_distance": ("purpose", "avg_distance"),
}


LONG_TERM_SUMMARIES_COLUMNS = {
    "license_holding_status_distribution": (
        "person_type",
        "license_holding_status",
        "person_type_label",
        "person_count",
    ),
    "bicycle_comfort_level_distribution": (),
    "autonomous_vehicle_ownership_totals": (),
    "auto_ownership_distribution": (
        "person_type",
        "bicycle_comfort_level",
        "person_type_label",
        "person_count",
    ),
    "work_from_home_rate_by_geography": (),
    "internal_external_worker_by_geography": (
        "geography_type",
        "geography_id",
        "internal_worker_count",
        "external_worker_count",
    ),
    "external_worker_workplace_locations": (
        "geography_type",
        "geography_id",
        "external_worker_count",
    ),
    "workplace_location_employment_comparison": (
        "geography_type",
        "geography_id",
        "employment_count",
        "worker_count",
    ),
    "school_location_enrollment_comparison": (
        "geography_type",
        "geography_id",
        "student_type",
        "enrollment_count",
        "student_count",
    ),
    "commuting_flows": (
        "origin_geography_type",
        "origin_geography_id",
        "destination_geography_type",
        "destination_geography_id",
        "commuter_count",
    ),
    "vehicle_age_distribution": (
        "age",
        "vehicle_count",
    ),
    "vehicle_fuel_type_distribution": (
        "fuel_type",
        "vehicle_count",
    ),
    "vehicle_body_type_distribution": (
        "body_type",
        "vehicle_count",
    ),
    "transit_pass_ownership_by_person_type": (
        "person_type",
        "transit_pass_ownership_status",
        "person_type_label",
        "person_count",
    ),
    "transit_subsidy_by_person_type": (
        "person_type",
        "transit_subsidy_status",
        "person_type_label",
        "person_count",
    ),
    "free_parking_eligibility_by_workplace_geography": (
        "geography_type",
        "geography_id",
        "workers_without_free_parking_count",
        "workers_with_free_parking_count",
    ),
}
