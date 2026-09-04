from __future__ import annotations

from types import SimpleNamespace

import polars as pl
import pytest

from processor.models import RunData
from processor.summarize.cache_types import strip_weights
from processor.summarize.summaries.daily_travel_activity import (
    tour_rate_per_person,
    trip_rate_per_person,
)
from processor.summarize.summaries.demographics import population_totals
from processor.summarize.summaries.trip import trip_mode
from processor.summarize.summaries.trip_distributions import trip_distance


def _config() -> SimpleNamespace:
    return SimpleNamespace()


def _run() -> RunData:
    return RunData(
        label="Test",
        run_dir="C:/runs/test",
        skim_file=None,
        hh=pl.DataFrame({"finalweight": [5.0]}),
        per=pl.DataFrame(
            {
                "person_id": [1, 2],
                "person_type": ["worker", "student"],
                "finalweight": [2.0, 3.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "person_id": [1, 1, 2, 2, 2, 2, 2],
                "tour_purpose": [
                    "work",
                    "eat",
                    "shopping",
                    "shopping",
                    "escort",
                    "social",
                    "other",
                ],
                "tour_category": [
                    "mandatory",
                    "atwork",
                    "joint",
                    "non_mandatory",
                    "joint",
                    "joint",
                    "joint",
                ],
                "NUMBER_HH": [1, 1, 4, 995, 995, 0, None],
                "finalweight": [2.0, 100.0, 3.0, 5.0, 7.0, 11.0, 13.0],
            }
        ),
        trips=pl.DataFrame(
            {
                "person_id": [1, 2, 2, 2, 2, 2],
                "tour_purpose": [
                    "work",
                    "shopping",
                    "escort",
                    "social",
                    "other",
                    "shopping",
                ],
                "trip_purpose": [
                    "work",
                    "shopping",
                    "escort",
                    "social",
                    "other",
                    "shopping",
                ],
                "tour_category": [
                    "mandatory",
                    "joint",
                    "joint",
                    "joint",
                    "joint",
                    "non_mandatory",
                ],
                "tour_mode": ["SOV", "HOV", "HOV", "HOV", "HOV", "SOV"],
                "trip_mode": ["SOV", "HOV", "HOV", "HOV", "HOV", "SOV"],
                "num_participants": [995, 4, 995, 0, None, 4],
                "od_dist": [1.2] * 6,
                "stops": [1, 1, 1, 0, 1, 1],
                "finalweight": [2.0, 3.0, 5.0, 7.0, 11.0, 13.0],
            }
        ),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )


def test_daily_rates_expand_only_valid_joint_parties_and_exclude_atwork() -> None:
    run = _run()

    tour_rates = tour_rate_per_person(run, _config()).filter(
        pl.col("person_type") == "all_person_types"
    )
    trip_rates = trip_rate_per_person(run, _config()).filter(
        pl.col("person_type") == "all_person_types"
    )

    assert "eat" not in tour_rates["tour_purpose"].to_list()
    assert dict(zip(tour_rates["tour_purpose"], tour_rates["tour_rate"])) == (
        pytest.approx(
            {
                "escort": 7.0 / 5.0,
                "other": 13.0 / 5.0,
                "shopping": 17.0 / 5.0,
                "social": 11.0 / 5.0,
                "work": 2.0 / 5.0,
            }
        )
    )
    assert dict(zip(trip_rates["trip_purpose"], trip_rates["trip_rate"])) == (
        pytest.approx(
            {
                "escort": 5.0 / 5.0,
                "other": 11.0 / 5.0,
                "shopping": 25.0 / 5.0,
                "social": 7.0 / 5.0,
                "work": 2.0 / 5.0,
            }
        )
    )


def test_daily_rates_use_each_joint_participants_weight() -> None:
    run = _run()
    run.per = pl.DataFrame(
        {
            "person_id": [1, 2, 3],
            "person_type": ["worker", "student", "child"],
            "finalweight": [2.0, 1.0, 3.0],
        }
    )
    run.tours = pl.DataFrame(
        {
            "tour_id": [10, 20],
            "person_id": [1, 1],
            "tour_purpose": ["shopping", "escort"],
            "tour_category": ["joint", "joint"],
            "NUMBER_HH": [3, 2],
            "finalweight": [4.0, 5.0],
        }
    )
    run.trips = pl.DataFrame(
        {
            "tour_id": [10, 20],
            "person_id": [1, 1],
            "trip_purpose": ["shopping", "escort"],
            "tour_category": ["joint", "joint"],
            "num_participants": [3, 2],
            "finalweight": [2.0, 3.0],
        }
    )
    run.joint_participants = pl.DataFrame(
        {
            "tour_id": [10, 10, 10],
            "person_id": [1, 2, 3],
        }
    )

    tour_rates = tour_rate_per_person(run, _config())
    trip_rates = trip_rate_per_person(run, _config())
    unweighted_tour_rates = tour_rate_per_person(strip_weights(run), _config())
    unweighted_trip_rates = trip_rate_per_person(strip_weights(run), _config())

    shopping_tours = tour_rates.filter(pl.col("tour_purpose") == "shopping")
    assert dict(zip(shopping_tours["person_type"], shopping_tours["tour_rate"])) == (
        pytest.approx(
            {
                "worker": 1.0,
                "student": 1.0,
                "child": 1.0,
                "all_person_types": 1.0,
            }
        )
    )
    escort_tours = tour_rates.filter(pl.col("tour_purpose") == "escort")
    assert dict(zip(escort_tours["person_type"], escort_tours["tour_rate"])) == (
        pytest.approx(
            {
                "worker": 10.0 / 2.0,
                "all_person_types": 10.0 / 6.0,
            }
        )
    )
    shopping_trips = trip_rates.filter(pl.col("trip_purpose") == "shopping")
    assert dict(zip(shopping_trips["person_type"], shopping_trips["trip_rate"])) == (
        pytest.approx(
            {
                "worker": 1.0,
                "student": 1.0,
                "child": 1.0,
                "all_person_types": 1.0,
            }
        )
    )
    assert unweighted_tour_rates.filter(pl.col("tour_purpose") == "shopping")[
        "tour_rate"
    ].to_list() == [1.0, 1.0, 1.0, 1.0]
    assert unweighted_trip_rates.filter(pl.col("trip_purpose") == "shopping")[
        "trip_rate"
    ].to_list() == [1.0, 1.0, 1.0, 1.0]
    escort_trips = trip_rates.filter(pl.col("trip_purpose") == "escort")
    assert dict(zip(escort_trips["person_type"], escort_trips["trip_rate"])) == (
        pytest.approx(
            {
                "worker": 6.0 / 2.0,
                "all_person_types": 6.0 / 6.0,
            }
        )
    )


def test_daily_rates_do_not_multiply_person_level_joint_rows() -> None:
    run = _run()
    run.per = pl.DataFrame(
        {
            "person_id": [1, 2],
            "person_type": ["worker", "student"],
            "finalweight": [2.0, 1.0],
        }
    )
    run.tours = pl.DataFrame(
        {
            "tour_id": [10, 11],
            "person_id": [1, 2],
            "tour_purpose": ["shopping", "shopping"],
            "tour_category": ["joint", "joint"],
            "NUMBER_HH": [2, 2],
            "finalweight": [2.0, 1.0],
        }
    )
    run.trips = pl.DataFrame(
        {
            "tour_id": [10, 11],
            "person_id": [1, 2],
            "trip_purpose": ["shopping", "shopping"],
            "tour_category": ["joint", "joint"],
            "num_participants": [2, 2],
            "finalweight": [2.0, 1.0],
        }
    )
    run.joint_participants = pl.DataFrame(
        {
            "tour_id": [10, 11],
            "person_id": [1, 2],
        }
    )

    for mode_run in (run, strip_weights(run)):
        tour_rate = tour_rate_per_person(mode_run, _config()).filter(
            pl.col("person_type") == "all_person_types"
        )["tour_rate"].sum()
        trip_rate = trip_rate_per_person(mode_run, _config()).filter(
            pl.col("person_type") == "all_person_types"
        )["trip_rate"].sum()

        assert tour_rate == pytest.approx(1.0)
        assert trip_rate == pytest.approx(1.0)


def test_population_totals_count_joint_travel_for_each_participant() -> None:
    result = population_totals(_run())

    assert result.to_dicts() == [
        {
            "person_count": 5.0,
            "household_count": 5.0,
            "tour_count": 150.0,
            "trip_count": 50.0,
            "stop_count": 43.0,
        }
    ]


def test_trip_mode_and_distance_ignore_sentinel_and_nonjoint_party_sizes() -> None:
    run = _run()

    modes = trip_mode(run, _config())
    shopping_sov = modes.filter(
        (pl.col("tour_purpose") == "shopping")
        & (pl.col("tour_mode") == "SOV")
        & (pl.col("trip_mode") == "SOV")
    )
    shopping_hov = modes.filter(
        (pl.col("tour_purpose") == "shopping")
        & (pl.col("tour_mode") == "HOV")
        & (pl.col("trip_mode") == "HOV")
    )
    distances = trip_distance(run, _config()).filter(pl.col("distance_bin") == "1")

    assert shopping_sov["trip_count"].to_list() == [13.0]
    assert shopping_hov["trip_count"].to_list() == [12.0]
    assert distances.filter(pl.col("tour_purpose") == "shopping")[
        "trip_count"
    ].to_list() == [25.0]
    assert distances.filter(pl.col("tour_purpose") == "all_tour_purposes")[
        "trip_count"
    ].to_list() == [50.0]
