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


def _build_tlfd_work(rd: RunData, config: Config) -> pl.DataFrame:
    return long_term.tlfd(rd, config)["work"]


def _build_tlfd_univ(rd: RunData, config: Config) -> pl.DataFrame:
    return long_term.tlfd(rd, config)["univ"]


def _build_tlfd_schl(rd: RunData, config: Config) -> pl.DataFrame:
    return long_term.tlfd(rd, config)["schl"]


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
        _build_tlfd_work,
    ),
    SummarySpec(
        "university_location_distance_distribution_by_geography",
        "university_location_distance_distribution_by_geography",
        _build_tlfd_univ,
    ),
    SummarySpec(
        "school_location_distance_distribution_by_geography",
        "school_location_distance_distribution_by_geography",
        _build_tlfd_schl,
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
    # total escorted tours
    # number escorted tours to/from school
    # tour rate per person
    # trip rate per person
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
    # joint tour composition by party size
    # joint tour participation per person by hh size
    SummarySpec(
        "household_jtp_by_household_size_and_jtf",
        "household_jtp_by_household_size_and_jtf",
        joint_travel.jtf_by_hhsize,
    ),
    # TOUR SUMMARIES
    # tour category
    # tour purpose
    # allocated vehicle age
    # allocated vehicle fuel type
    # allocated vehicle body type
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
    # at-work sub-tour frequency
    SummarySpec(
        "tour_time_of_day_by_tour_purpose",
        "tour_time_of_day_by_tour_purpose",
        tour.tour_tod,
    ),
    # tour distance
    SummarySpec(
        "average_mandatory_tour_distance_by_purpose_and_geography",
        "average_mandatory_tour_distance_by_purpose_and_geography",
        tour.avg_mand_tour_distance,
    ),
    # avg non-mandatory tour distance
    # interval vs external non mandatory tour freq
    # external nonmandatory tour location
    # TRIP SUMMARIES
    # trip purpose
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
    # trip distance
    SummarySpec(
        "stop_out_of_direction_distance_by_tour_purpose",
        "stop_out_of_direction_distance_by_tour_purpose",
        trip.stop_ood_distance,
    ),
    # parking location
    # VALIDATION SUMMARIES
    # traffic count comparisons
    # screenline flow comparisons
    # total transit boardings
    # transit transfer rates
    SummarySpec("auto_vmt_totals", "auto_vmt_totals", validation.auto_vmt_totals),
    # commercial vehicle vmt
    # bicycle vmt by facility type
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
