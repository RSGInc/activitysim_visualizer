"""Long-term summary facade grouped by domain."""

from processor.summarize.summaries.long_term_distance import (
    schl_tlfd,
    tlfd,
    univ_tlfd,
    work_tlfd,
)
from processor.summarize.summaries.long_term_geography import (
    commuting_flows,
    external_workplace_loc,
    free_parking,
    internal_vs_external,
    school_loc_vs_land_use_enrollment,
    wfh,
    workplace_vs_land_use_employment,
)
from processor.summarize.summaries.long_term_person import (
    bicycle_comfort_level,
    license_holding_status,
    telecommute,
    transit_pass,
    transit_subsidy,
)
from processor.summarize.summaries.long_term_vehicle import (
    auto_ownership,
    av_ownership,
    vehicle_char_age,
    vehicle_char_body,
    vehicle_char_fuel,
)

__all__ = [
    "auto_ownership",
    "av_ownership",
    "bicycle_comfort_level",
    "commuting_flows",
    "external_workplace_loc",
    "free_parking",
    "internal_vs_external",
    "license_holding_status",
    "school_loc_vs_land_use_enrollment",
    "schl_tlfd",
    "telecommute",
    "tlfd",
    "transit_pass",
    "transit_subsidy",
    "univ_tlfd",
    "vehicle_char_age",
    "vehicle_char_body",
    "vehicle_char_fuel",
    "wfh",
    "work_tlfd",
    "workplace_vs_land_use_employment",
]
