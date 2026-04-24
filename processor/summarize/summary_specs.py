from __future__ import annotations


from dataclasses import dataclass
from typing import Callable

import polars as pl

from processor.models import RunData
from runtime.config import Config
from processor.summarize.summaries import (
    daily_travel,
    demographics,
    joint_travel,
    legacy,
    long_term,
    tour,
    trip,
    validation,
)


@dataclass(frozen=True)
class SummarySpec:
    summary_id: str
    filename: str
    builder: Callable[[RunData, Config], pl.DataFrame]


SUMMARY_SPECS: tuple[SummarySpec, ...] = (
    ### DEMOGRAPHIC SUMMARIES
    SummarySpec(
        "household_size_distribution",
        "household_size_distribution",
        demographics.hh_size,
    ),
    SummarySpec(
        "person_type_distribution", "person_type_distribution", demographics.person_type
    ),
    SummarySpec(
        "population_totals", "population_totals", demographics.population_totals
    ),
    ### LONG TERM SUMMARIES
    SummarySpec(
        "license_holding_status_distribution",
        "license_holding_status_distribution",
        long_term.license_holding_status,
    ),
    SummarySpec(
        "bicycle_comfort_level_distribution",
        "bicycle_comfort_level_distribution",
        long_term.bicycle_comfort_level,
    ),
    SummarySpec(
        "autonomous_vehicle_ownership_totals",
        "autonomous_vehicle_ownership_totals",
        long_term.av_ownership,
    ),
    SummarySpec(
        "auto_ownership_distribution",
        "auto_ownership_distribution",
        long_term.auto_ownership,
    ),
    SummarySpec(
        "work_from_home_rate_by_geography",
        "work_from_home_rate_by_geography",
        long_term.wfh,
    ),
    SummarySpec(
        "internal_external_worker_by_geography",
        "internal_external_worker_by_geography",
        long_term.internal_vs_external,
    ),
    SummarySpec(
        "external_worker_workplace_locations",
        "external_worker_workplace_locations",
        long_term.external_workplace_loc,
    ),
    SummarySpec(
        "workplace_location_employment_comparison",
        "workplace_location_employment_comparison",
        long_term.workplace_vs_land_use_employment,
    ),
    SummarySpec(
        "school_location_enrollment_comparison",
        "school_location_enrollment_comparison",
        long_term.school_loc_vs_land_use_enrollment,
    ),
    SummarySpec(
        "commuting_flows",
        "commuting_flows",
        long_term.commuting_flows,
    ),
    SummarySpec(
        "work_location_distance_distribution_by_geography",
        "work_location_distance_distribution_by_geography",
        long_term.work_tlfd,
    ),
    SummarySpec(
        "university_location_distance_distribution_by_geography",
        "university_location_distance_distribution_by_geography",
        long_term.univ_tlfd,
    ),
    SummarySpec(
        "school_location_distance_distribution_by_geography",
        "school_location_distance_distribution_by_geography",
        long_term.schl_tlfd,
    ),
    SummarySpec(
        "vehicle_age_distribution",
        "vehicle_age_distribution",
        long_term.vehicle_char_age,
    ),
    SummarySpec(
        "vehicle_fuel_type_distribution",
        "vehicle_fuel_type_distribution",
        long_term.vehicle_char_fuel,
    ),
    SummarySpec(
        "vehicle_body_type_distribution",
        "vehicle_body_type_distribution",
        long_term.vehicle_char_body,
    ),
    SummarySpec(
        "transit_pass_ownership_by_person_type",
        "transit_pass_ownership_by_person_type",
        long_term.transit_pass,
    ),
    SummarySpec(
        "transit_subsidy_by_person_type",
        "transit_subsidy_by_person_type",
        long_term.transit_subsidy,
    ),
    SummarySpec(
        "free_parking_eligibility_by_workplace_geography",
        "free_parking_eligibility_by_workplace_geography",
        long_term.free_parking,
    ),
    SummarySpec(
        "telecommute_frequency_distribution",
        "telecommute_frequency_distribution",
        long_term.telecommute,
    ),
    ### DAILY TRAVEL SUMMARIES
    SummarySpec(
        "daily_activity_pattern_by_person_type",
        "daily_activity_pattern_by_person_type",
        daily_travel.dap_summary,
    ),
    SummarySpec(
        "mandatory_tour_frequency_by_person_type",
        "mandatory_tour_frequency_by_person_type",
        daily_travel.mandatory_tour_freq,
    ),
    SummarySpec(
        "nonmandatory_tour_frequency_by_person_type",
        "nonmandatory_tour_frequency_by_person_type",
        daily_travel.indiv_nm_summary,
    ),
    SummarySpec(
        "escorted_tour_totals",
        "escorted_tour_totals",
        daily_travel.total_escorted_tours,
    ),
    SummarySpec(
        "school_escorted_tours_by_escort_type_and_direction",
        "school_escorted_tours_by_escort_type_and_direction",
        daily_travel.escorted_tours_to_from_school,
    ),
    SummarySpec(
        "tour_rates_by_person_type_and_tour_purpose",
        "tour_rates_by_person_type_and_tour_purpose",
        daily_travel.tour_rate_per_person,
    ),
    SummarySpec(
        "trip_rates_by_person_type_and_trip_purpose",
        "trip_rates_by_person_type_and_trip_purpose",
        daily_travel.trip_rate_per_person,
    ),
    ### JOINT TRAVEL SUMMARIES
    SummarySpec("jtf_distribution", "jtf_distribution", joint_travel.joint_tour_freq),
    SummarySpec(
        "joint_tours_by_household_size",
        "joint_tours_by_household_size",
        joint_travel.joint_tours_hhsize,
    ),
    SummarySpec(
        "joint_tour_party_size_distribution",
        "joint_tour_party_size_distribution",
        joint_travel.joint_party_size,
    ),
    SummarySpec(
        "joint_tour_composition_distribution",
        "joint_tour_composition_distribution",
        joint_travel.joint_composition,
    ),
    SummarySpec(
        "joint_tour_composition_by_party_size",
        "joint_tour_composition_by_party_size",
        joint_travel.joint_composition_by_party_size,
    ),
    SummarySpec(
        "person_jtp_by_household_size",
        "person_jtp_by_household_size",
        joint_travel.joint_participation_person_by_hhsize,
    ),
    SummarySpec(
        "household_jtp_by_household_size_and_jtf",
        "household_jtp_by_household_size_and_jtf",
        joint_travel.jtf_by_hhsize,
    ),
    # TOUR SUMMARIES
    SummarySpec(
        "tour_category_distribution",
        "tour_category_distribution",
        tour.tour_category,
    ),
    SummarySpec(
        "tour_purpose_distribution",
        "tour_purpose_distribution",
        tour.tour_purpose,
    ),
    SummarySpec(
        "allocated_vehicle_age_by_occupancy",
        "allocated_vehicle_age_by_occupancy",
        tour.allocated_vehicle_age,
    ),
    SummarySpec(
        "allocated_vehicle_fuel_type_by_occupancy",
        "allocated_vehicle_fuel_type_by_occupancy",
        tour.allocated_vehicle_fuel,
    ),
    SummarySpec(
        "allocated_vehicle_body_type_by_occupancy",
        "allocated_vehicle_body_type_by_occupancy",
        tour.allocated_vehicle_body,
    ),
    SummarySpec(
        "tour_mode_by_tour_purpose_and_auto_sufficiency",
        "tour_mode_by_tour_purpose_and_auto_sufficiency",
        tour.tour_mode,
    ),
    SummarySpec(
        "tour_stop_frequency_by_tour_purpose",
        "tour_stop_frequency_by_tour_purpose",
        tour.stop_freq,
    ),
    SummarySpec(
        "atwork_subtour_frequency_distribution",
        "atwork_subtour_frequency_distribution",
        tour.at_work_sub_tour_freq,
    ),
    SummarySpec(
        "tour_time_of_day_by_tour_purpose",
        "tour_time_of_day_by_tour_purpose",
        tour.tour_tod,
    ),
    SummarySpec(
        "tour_distance_by_tour_purpose",
        "tour_distance_by_tour_purpose",
        tour.tour_distance,
    ),
    SummarySpec(
        "average_mandatory_tour_distance_by_purpose_and_geography",
        "average_mandatory_tour_distance_by_purpose_and_geography",
        tour.avg_mand_tour_distance,
    ),
    SummarySpec(
        "average_nonmandatory_tour_distance_by_purpose_and_geography",
        "average_nonmandatory_tour_distance_by_purpose_and_geography",
        tour.avg_non_mand_tour_distance,
    ),
    SummarySpec(
        "internal_external_nonmandatory_tour_frequency_by_home_geography",
        "internal_external_nonmandatory_tour_frequency_by_home_geography",
        tour.int_vs_ext_non_mand_tour_freq,
    ),
    SummarySpec(
        "external_nonmandatory_tour_locations",
        "external_nonmandatory_tour_locations",
        tour.ext_non_mand_tour_loc,
    ),
    # TRIP SUMMARIES
    SummarySpec(
        "trip_purpose_distribution",
        "trip_purpose_distribution",
        trip.trip_purpose,
    ),
    SummarySpec(
        "stop_destination_purpose_by_tour_purpose",
        "stop_destination_purpose_by_tour_purpose",
        trip.stop_purpose_by_tour_purpose,
    ),
    SummarySpec(
        "trip_mode_by_tour_purpose_and_tour_mode",
        "trip_mode_by_tour_purpose_and_tour_mode",
        trip.trip_mode,
    ),
    SummarySpec(
        "trip_departure_time_by_purpose",
        "trip_departure_time_by_purpose",
        trip.trip_stop_tod,
    ),
    SummarySpec(
        "trip_distance_by_purpose",
        "trip_distance_by_purpose",
        trip.trip_distance,
    ),
    SummarySpec(
        "stop_out_of_direction_distance_by_tour_purpose",
        "stop_out_of_direction_distance_by_tour_purpose",
        trip.stop_ood_distance,
    ),
    SummarySpec(
        "parking_locations",
        "parking_locations",
        trip.parking_locations,
    ),
    # VALIDATION SUMMARIES
    SummarySpec(
        "traffic_count_comparisons",
        "traffic_count_comparisons",
        validation.traffic_count_comparisons,
    ),
    SummarySpec(
        "screenline_flow_comparisons",
        "screenline_flow_comparisons",
        validation.screenline_flow_comparisons,
    ),
    SummarySpec(
        "transit_boardings_by_operator_and_technology",
        "transit_boardings_by_operator_and_technology",
        validation.total_transit_boardings,
    ),
    SummarySpec(
        "transit_transfer_rate",
        "transit_transfer_rate",
        validation.transit_transfer_rate,
    ),
    SummarySpec("auto_vmt_totals", "auto_vmt_totals", validation.auto_vmt_totals),
    SummarySpec(
        "commercial_vmt_totals",
        "commercial_vmt_totals",
        validation.commercial_vehicle_vmt,
    ),
    SummarySpec(
        "bicycle_vmt_by_facility_type",
        "bicycle_vmt_by_facility_type",
        validation.bicycle_vmt_by_facility,
    ),
    # TEMPORARY LEGACY SUMMARIES
    SummarySpec("geo_flows", "geoFlows", legacy.geo_flows),
    SummarySpec("nm_tour_rates", "nm_tour_rates", legacy.nm_tour_rates),
    SummarySpec(
        "grouped_tour_mode_profile",
        "groupedTmodeProfile_vis",
        legacy.grouped_tour_mode_profile,
    ),
    SummarySpec(
        "destination_distance",
        "destinationDistByPurpose",
        legacy.distance_distribution,
    ),
    SummarySpec(
        "destination_average_distance",
        "destinationAvgDistance",
        legacy.average_distance,
    ),
    SummarySpec("totals", "totals", legacy.system_totals),
)

SUMMARY_SPEC_BY_ID = {spec.summary_id: spec for spec in SUMMARY_SPECS}
SUMMARY_FILENAME_BY_ID = {
    spec.summary_id: f"{spec.filename}.csv" for spec in SUMMARY_SPECS
}
DEFAULT_SUMMARY_IDS = [spec.summary_id for spec in SUMMARY_SPECS]
