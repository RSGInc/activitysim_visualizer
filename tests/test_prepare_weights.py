from __future__ import annotations

from pathlib import Path

import polars as pl

from processor.models import RunData
from processor.prepare.enrichment.weights import compute_weights
from processor.summarize.cache_types import strip_weights
from runtime.config import Config


def _config(tmp_path: Path) -> Config:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Prepare Weight Test"',
                "runs: []",
                "root: summary_cache",
                "dashboard:",
                '  title: "Prepare Weight Test"',
            ]
        ),
        encoding="utf-8",
    )
    return Config.from_yaml(config_path)


def test_person_weights_flow_to_activity_tables_without_dropping_records(
    tmp_path: Path,
) -> None:
    hh = pl.DataFrame(
        {
            "household_id": [1, 2],
            "hh_weight": [0.25, 2.0],
        }
    )
    per = pl.DataFrame(
        {
            "person_id": [10, 20],
            "household_id": [1, 2],
            "person_weight": [0.25, 2.0],
        }
    )
    day = pl.DataFrame(
        {
            "day_id": [100, 200],
            "person_id": [10, 20],
            "household_id": [1, 2],
        }
    )
    tours = pl.DataFrame(
        {
            "tour_id": [101, 102, 201],
            "person_id": [10, 10, 20],
            "household_id": [1, 1, 2],
            "tour_weight": [1.0, 1.0, 1.0],
        }
    )
    trips = pl.DataFrame(
        {
            "trip_id": [1001, 1002, 1003, 2001],
            "tour_id": [101, 101, 102, 201],
            "person_id": [10, 10, 10, 20],
            "household_id": [1, 1, 1, 2],
            "linked_trip_weight": [1.0, 1.0, 1.0, 1.0],
        }
    )
    vehicles = pl.DataFrame(
        {
            "vehicle_id": [1, 2],
            "household_id": [1, 2],
        }
    )

    weighted_tables = compute_weights(
        hh,
        per,
        day,
        tours,
        trips,
        vehicles,
        _config(tmp_path),
        hh_weight_col="hh_weight",
        person_weight_col="person_weight",
        trip_weight_col=None,
    )
    (
        weighted_hh,
        weighted_per,
        weighted_day,
        weighted_tours,
        weighted_trips,
        weighted_vehicles,
    ) = weighted_tables

    assert weighted_tours.height == tours.height
    assert weighted_trips.height == trips.height
    assert (
        weighted_tours.sort("tour_id")["tour_id"].to_list()
        == tours.sort("tour_id")["tour_id"].to_list()
    )
    assert (
        weighted_trips.sort("trip_id")["trip_id"].to_list()
        == trips.sort("trip_id")["trip_id"].to_list()
    )
    assert weighted_tours.sort("tour_id")["finalweight"].to_list() == [0.25, 0.25, 2.0]
    assert weighted_trips.sort("trip_id")["finalweight"].to_list() == [
        0.25,
        0.25,
        0.25,
        2.0,
    ]

    weighted = RunData(
        label="Weighted",
        run_dir=".",
        skim_file=None,
        hh=weighted_hh,
        per=weighted_per,
        day=weighted_day,
        tours=weighted_tours,
        trips=weighted_trips,
        vehicles=weighted_vehicles,
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        hh_weight_col="hh_weight",
        person_weight_col="person_weight",
    )
    unweighted = strip_weights(weighted)

    for weighted_frame, unweighted_frame in (
        (weighted.hh, unweighted.hh),
        (weighted.per, unweighted.per),
        (weighted.day, unweighted.day),
        (weighted.tours, unweighted.tours),
        (weighted.trips, unweighted.trips),
        (weighted.vehicles, unweighted.vehicles),
    ):
        assert unweighted_frame.height == weighted_frame.height
        assert (
            unweighted_frame["finalweight"].to_list() == [1.0] * weighted_frame.height
        )


def test_day_weight_source_can_explicitly_inherit_person_weights(tmp_path: Path) -> None:
    hh = pl.DataFrame({"household_id": [1], "hh_weight": [1.0]})
    per = pl.DataFrame(
        {
            "household_id": [1, 1],
            "person_id": [10, 20],
            "person_weight": [1 / 7, 2.0],
        }
    )
    day = pl.DataFrame(
        {
            "household_id": [1, 1],
            "person_id": [10, 20],
            "day_weight": [1.0, 1.0],
        }
    )
    empty = pl.DataFrame()

    default_day = compute_weights(
        hh,
        per,
        day,
        empty,
        empty,
        empty,
        _config(tmp_path),
        hh_weight_col="hh_weight",
        person_weight_col="person_weight",
    )[2]
    inherited_day = compute_weights(
        hh,
        per,
        day,
        empty,
        empty,
        empty,
        _config(tmp_path),
        hh_weight_col="hh_weight",
        person_weight_col="person_weight",
        day_weight_col=None,
    )[2]

    assert default_day["finalweight"].to_list() == [1.0, 1.0]
    assert inherited_day["finalweight"].to_list() == [1 / 7, 2.0]
