from __future__ import annotations

from types import SimpleNamespace

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from processor.models import RunData
from processor.summarize.cache_types import strip_weights
from processor.summarize.summaries.demographics import population_totals
from processor.summarize.summaries.tour_profiles import tour_mode
from processor.summarize.summaries.trip import (
    stop_purpose_by_tour_purpose,
    trip_mode,
    trip_purpose,
)
from processor.summarize.summaries.trip_distributions import (
    stop_ood_distance,
    trip_distance,
    trip_stop_tod,
)


def _config() -> SimpleNamespace:
    return SimpleNamespace()


def _person_travel_run(*, participant_rows: bool) -> RunData:
    person_ids = [1, 2, 3]
    person_weights = [2.0, 3.0, 4.0]
    if participant_rows:
        tour_ids = [101, 102, 103]
        tours = pl.DataFrame(
            {
                "tour_id": tour_ids,
                "person_id": person_ids,
                "tour_purpose": ["shopping"] * 3,
                "tour_category": ["joint"] * 3,
                "tour_mode": ["HOV3"] * 3,
                "NUMBER_HH": [3] * 3,
                "AUTOSUFF": [0] * 3,
                "finalweight": [97.0] * 3,
            }
        )
        trips = pl.DataFrame(
            {
                "tour_id": [tour_id for tour_id in tour_ids for _ in range(2)],
                "person_id": [person_id for person_id in person_ids for _ in range(2)],
                "tour_purpose": ["shopping"] * 6,
                "trip_purpose": ["shopping", "eatout"] * 3,
                "tour_category": ["joint"] * 6,
                "tour_mode": ["HOV3"] * 6,
                "trip_mode": ["HOV3"] * 6,
                "num_participants": [3] * 6,
                "od_dist": [1.2, 2.2] * 3,
                "out_dir_dist": [0.0, 3.2] * 3,
                "depart": [5, 6] * 3,
                "stops": [0, 1] * 3,
                "finalweight": [89.0] * 6,
            }
        )
        joint_participants = pl.DataFrame(
            {"tour_id": tour_ids, "person_id": person_ids}
        )
    else:
        tours = pl.DataFrame(
            {
                "tour_id": [10],
                "person_id": [1],
                "tour_purpose": ["shopping"],
                "tour_category": ["joint"],
                "tour_mode": ["HOV3"],
                "NUMBER_HH": [3],
                "AUTOSUFF": [0],
                "finalweight": [97.0],
            }
        )
        trips = pl.DataFrame(
            {
                "tour_id": [10, 10],
                "person_id": [1, 1],
                "tour_purpose": ["shopping", "shopping"],
                "trip_purpose": ["shopping", "eatout"],
                "tour_category": ["joint", "joint"],
                "tour_mode": ["HOV3", "HOV3"],
                "trip_mode": ["HOV3", "HOV3"],
                "num_participants": [3, 3],
                "od_dist": [1.2, 2.2],
                "out_dir_dist": [0.0, 3.2],
                "depart": [5, 6],
                "stops": [0, 1],
                "finalweight": [89.0, 89.0],
            }
        )
        joint_participants = pl.DataFrame(
            {"tour_id": [10, 10, 10], "person_id": person_ids}
        )

    return RunData(
        label="Raw participants" if participant_rows else "Model household",
        run_dir="C:/runs/test",
        skim_file=None,
        hh=pl.DataFrame({"finalweight": [4.0]}),
        per=pl.DataFrame(
            {"person_id": person_ids, "finalweight": person_weights}
        ),
        tours=tours,
        trips=trips,
        joint_participants=joint_participants,
        land_use=pl.DataFrame(),
        skim_matrix=None,
    )


@pytest.mark.parametrize(
    ("unweighted", "expected_tour_count", "expected_trip_count"),
    [(False, 9.0, 18.0), (True, 3.0, 6.0)],
)
def test_person_travel_summaries_match_model_and_raw_participant_rows(
    unweighted: bool,
    expected_tour_count: float,
    expected_trip_count: float,
) -> None:
    model = _person_travel_run(participant_rows=False)
    raw = _person_travel_run(participant_rows=True)
    if unweighted:
        model = strip_weights(model)
        raw = strip_weights(raw)

    builders = (
        population_totals,
        tour_mode,
        trip_purpose,
        stop_purpose_by_tour_purpose,
        trip_mode,
        trip_stop_tod,
        trip_distance,
        stop_ood_distance,
    )
    for builder in builders:
        assert_frame_equal(
            builder(model, _config()),
            builder(raw, _config()),
            check_row_order=False,
        )

    totals = population_totals(model)
    assert totals["tour_count"][0] == pytest.approx(expected_tour_count)
    assert totals["trip_count"][0] == pytest.approx(expected_trip_count)
    assert totals["stop_count"][0] == pytest.approx(expected_tour_count)

    mode_count = tour_mode(model, _config()).filter(
        pl.col("tour_purpose") == "shopping"
    )["tour_count_all_households"][0]
    assert mode_count == pytest.approx(expected_tour_count)

    trip_tod = trip_stop_tod(model, _config()).filter(
        (pl.col("tour_purpose") == "shopping") & (pl.col("time_bin") == 6)
    )
    assert trip_tod["departure_trip_count"][0] == pytest.approx(
        expected_tour_count
    )
    assert trip_tod["departure_stop_count"][0] == pytest.approx(
        expected_tour_count
    )
