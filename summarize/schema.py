"""Canonical summary-table output schemas used by dashboard pages."""

from __future__ import annotations

SUMMARY_OUTPUT_COLUMNS: dict[str, tuple[str, ...]] = {
    "stop_freq": ("purpose", "ob_stops", "ib_stops", "tot_stops", "freq"),
    "stop_purpose_by_tour_purpose": ("tour_purpose", "stop_purpose", "freq"),
    "stop_location": ("distbin", "purpose", "freq"),
    "stop_timing": ("timebin", "purpose", "freq_stop_dep", "freq_trip_dep"),
    "trip_mode_profile": ("purpose", "tour_mode", "trip_mode", "freq"),
    "tour_mode_profile": (
        "tour_mode",
        "purpose",
        "freq_as0",
        "freq_as1",
        "freq_as2",
        "freq_all",
    ),
    "grouped_tour_mode_profile": (
        "mode_group",
        "purpose",
        "freq_as0",
        "freq_as1",
        "freq_as2",
        "freq_all",
    ),
    "tour_tod_profiles": ("timebin", "purpose", "freq_dep", "freq_arr", "freq_dur"),
    "destination_distance": ("purpose", "distbin", "freq"),
    "destination_average_distance": ("purpose", "avg_distance"),
}
