"""Canonical summary-table output schemas used by dashboard pages."""

from __future__ import annotations

from processor.summarize.contracts import get_summary_contract
from processor.summarize.summary_specs import SUMMARY_SPECS


def _columns_for(summary_id: str) -> tuple[str, ...]:
    for spec in SUMMARY_SPECS:
        if spec.summary_id != summary_id:
            continue
        contract = get_summary_contract(spec.builder)
        return tuple(contract.schema.keys()) if contract is not None else ()
    return ()


SUMMARY_OUTPUT_COLUMNS: dict[str, tuple[str, ...]] = {
    summary_id: _columns_for(summary_id)
    for summary_id in (
        "tour_stop_frequency_by_tour_purpose",
        "stop_destination_purpose_by_tour_purpose",
        "stop_out_of_direction_distance_by_tour_purpose",
        "trip_departure_time_by_purpose",
        "trip_mode_by_tour_purpose_and_tour_mode",
        "tour_mode_by_tour_purpose_and_auto_sufficiency",
        "tour_time_of_day_by_tour_purpose",
        "destination_distance",
        "destination_average_distance",
    )
}


LONG_TERM_SUMMARIES_COLUMNS = {
    summary_id: _columns_for(summary_id)
    for summary_id in (
        "license_holding_status_distribution",
        "bicycle_comfort_level_distribution",
        "autonomous_vehicle_ownership_totals",
        "auto_ownership_distribution",
        "work_from_home_rate_by_geography",
        "internal_external_worker_by_geography",
        "external_worker_workplace_locations",
        "workplace_location_employment_comparison",
        "workplace_shadow_pricing_residuals",
        "workplace_shadow_pricing_residual_histogram",
        "school_location_enrollment_comparison",
        "school_shadow_pricing_residuals",
        "school_shadow_pricing_residual_histogram",
        "park_and_ride_location_residuals",
        "park_and_ride_location_residual_histogram",
        "commuting_flows",
        "vehicle_age_distribution",
        "vehicle_fuel_type_distribution",
        "vehicle_body_type_distribution",
        "transit_pass_ownership_by_person_type",
        "transit_subsidy_by_person_type",
        "free_parking_eligibility_by_workplace_geography",
    )
}
