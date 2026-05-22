"""Shared config defaults and table-id constants."""

from __future__ import annotations

FILE_MAPPING_DEFAULTS: dict[str, str] = {
    "households": "final_households",
    "persons": "final_persons",
    "day": "final_day",
    "tours": "final_tours",
    "trips": "final_trips",
    "vehicles": "final_vehicles",
    "joint_tour_participants": "final_joint_tour_participants",
    "land_use": "final_land_use",
}

PREPARED_TABLE_MAP_KEYS: tuple[str, ...] = tuple(FILE_MAPPING_DEFAULTS)
OPTIONAL_PREPARED_TABLE_IDS: set[str] = {
    "day",
    "vehicles",
    "joint_tour_participants",
    "land_use",
}

DEFAULT_RUN_COLORS: list[str] = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
]
