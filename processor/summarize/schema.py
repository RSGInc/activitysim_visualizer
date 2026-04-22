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
