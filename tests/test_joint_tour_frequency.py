from __future__ import annotations

from types import SimpleNamespace

import polars as pl
import pytest

from processor.models import RunData
from processor.summarize.cache_types import strip_weights
from processor.summarize.summaries.joint_travel import (
    joint_composition,
    joint_composition_by_party_size,
    joint_party_size,
    joint_participation_person_by_hhsize,
    joint_tour_freq,
    jtf_by_hhsize,
)
from processor.summarize.summaries.summary_helpers import (
    household_tour_weight_expr,
)
from processor.summarize.summaries.tour import tour_category, tour_purpose
from processor.summarize.summaries.tour_profiles import stop_freq, tour_distance, tour_tod


def _run_with_tours(tours: pl.DataFrame) -> RunData:
    return RunData(
        label="Test",
        run_dir="C:/runs/test",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=tours,
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
    )


def test_joint_tour_frequency_uses_fixed_legacy_purpose_alternatives() -> None:
    households = pl.DataFrame(
        {
            "household_id": [1, 2, 3, 4, 5, 6, 7],
            "finalweight": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
        }
    )
    tours = pl.DataFrame(
        {
            "household_id": [2, 3, 4, 4, 5, 5, 6, 6, 7, 7],
            "tour_category": ["joint"] * 10,
            "tour_purpose": [
                "shopping",
                "othmaint",
                "maintenance",
                "othmaint",
                "SHOPPING",
                "maintenance",
                "eatout",
                "social",
                "othdiscr",
                "other_discretionary",
            ],
        }
    )
    run = RunData(
        label="Test",
        run_dir="C:/runs/test",
        skim_file=None,
        hh=households,
        per=pl.DataFrame(),
        tours=tours,
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
    )

    result = joint_tour_freq(run).filter(pl.col("household_count") > 0)

    assert result.to_dicts() == [
        {"jtf_code": 1, "jtf_label": "No Joint Tours", "household_count": 1.0},
        {"jtf_code": 2, "jtf_label": "1 Shopping", "household_count": 2.0},
        {"jtf_code": 3, "jtf_label": "1 Maintenance", "household_count": 3.0},
        {
            "jtf_code": 8,
            "jtf_label": "1 Shopping / 1 Maintenance",
            "household_count": 5.0,
        },
        {"jtf_code": 12, "jtf_label": "2 Maintenance", "household_count": 4.0},
        {
            "jtf_code": 17,
            "jtf_label": "1 Eating Out / 1 Visiting",
            "household_count": 6.0,
        },
        {
            "jtf_code": 21,
            "jtf_label": "2 Other Discretionary",
            "household_count": 7.0,
        },
    ]


def test_joint_tour_frequency_does_not_pool_multiday_diaries() -> None:
    run = RunData(
        label="Multi-day Survey",
        run_dir="C:/runs/test",
        skim_file=None,
        hh=pl.DataFrame(
            {
                "household_id": [1],
                "HHSIZE": [2],
                "finalweight": [3.0],
            }
        ),
        per=pl.DataFrame(),
        day=pl.DataFrame(
            {
                "household_id": [1, 1, 1, 1],
                "person_id": [10, 20, 10, 20],
                "day_num": [1, 1, 2, 2],
                "finalweight": [3.0, 3.0, 3.0, 3.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "household_id": [1, 1],
                "tour_category": ["joint", "joint"],
                "tour_purpose": ["shopping", "shopping"],
            }
        ),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
    )

    assert joint_tour_freq(run).is_empty()
    assert jtf_by_hhsize(run).is_empty()


def test_joint_tour_frequency_counts_unique_tours_by_household_day() -> None:
    run = RunData(
        label="Multi-day Survey",
        run_dir="C:/runs/test",
        skim_file=None,
        hh=pl.DataFrame(
            {"household_id": [1], "HHSIZE": [2], "finalweight": [3.0]}
        ),
        per=pl.DataFrame(),
        day=pl.DataFrame(
            {
                "household_id": [1, 1, 1, 1],
                "person_id": [10, 20, 10, 20],
                "day_num": [1, 1, 2, 2],
                "finalweight": [3.0, 3.0, 3.0, 3.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "household_id": [1, 1, 1, 1],
                "day_num": [1, 1, 2, 2],
                "tour_id": [11, 12, 21, 22],
                "joint_tour_id": [100, 100, 200, 200],
                "tour_category": ["joint"] * 4,
                "tour_purpose": ["shopping"] * 4,
            }
        ),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
    )

    frequency = joint_tour_freq(run).filter(pl.col("household_count") > 0)
    participation = jtf_by_hhsize(run)

    assert frequency.to_dicts() == [
        {"jtf_code": 2, "jtf_label": "1 Shopping", "household_count": 6.0}
    ]
    assert participation.to_dicts() == [
        {"jtf": "1", "household_size": "2", "household_percent": 100.0}
    ]


def test_person_joint_participation_uses_person_days_for_multiday_data() -> None:
    run = RunData(
        label="Multi-day Survey",
        run_dir="C:/runs/test",
        skim_file=None,
        hh=pl.DataFrame(
            {"household_id": [1], "HHSIZE": [2], "finalweight": [1.0]}
        ),
        per=pl.DataFrame(
            {
                "household_id": [1, 1],
                "person_id": [10, 20],
                "finalweight": [1.0, 1.0],
            }
        ),
        day=pl.DataFrame(
            {
                "household_id": [1, 1, 1, 1],
                "person_id": [10, 20, 10, 20],
                "day_num": [1, 1, 2, 2],
                "finalweight": [1.0, 1.0, 1.0, 1.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "household_id": [1],
                "day_num": [1],
                "tour_id": [11],
                "joint_tour_id": [100],
                "tour_category": ["joint"],
            }
        ),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(
            {
                "tour_id": [11, 11],
                "joint_tour_id": [100, 100],
                "person_id": [10, 20],
            }
        ),
        land_use=pl.DataFrame(),
        skim_matrix=None,
    )

    assert joint_participation_person_by_hhsize(run, None).to_dicts() == [
        {
            "household_size": 2,
            "joint_tour_person_count": 2.0,
            "total_person_count": 4.0,
        }
    ]


def test_joint_party_summaries_exclude_995_sentinel() -> None:
    tours = pl.DataFrame(
        {
            "tour_category": ["joint", "joint"],
            "NUMBER_HH": [2, 995],
            "number_of_participants": [2, 995],
            "composition": ["mixed", "mixed"],
            "finalweight": [2.0, 100.0],
        }
    )
    run = RunData(
        label="Test",
        run_dir="C:/runs/test",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=tours,
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
    )

    assert joint_party_size(run).to_dicts() == [
        {"party_size": 2, "joint_tour_count": 2.0},
        {"party_size": 5, "joint_tour_count": 0.0},
    ]
    assert joint_composition_by_party_size(run, None).to_dicts() == [
        {"tour_composition": "mixed", "party_size": 2, "joint_tour_count": 2.0}
    ]


def test_household_tour_summaries_fractionally_use_every_participant_row() -> None:
    raw_tours = pl.DataFrame(
        {
            "tour_category": ["joint", "joint", "joint"],
            "tour_purpose": ["shopping", "shopping", "shopping"],
            "tour_id": [11, 12, 13],
            "joint_tour_id": [100, 100, 100],
            "NUMBER_HH": [1, 1, 1],
            "number_of_participants": [3, 3, 3],
            "composition": ["mixed", "mixed", "mixed"],
            "start_hour": [10, 10, 10],
            "end_hour": [12, 12, 12],
            "tourdur": [2, 2, 2],
            "SKIMDIST": [4.0, 4.0, 4.0],
            "num_ob_stops": pl.Series([1, 1, 1], dtype=pl.Int32),
            "num_ib_stops": pl.Series([2, 2, 2], dtype=pl.Int32),
            "num_tot_stops": pl.Series([3, 3, 3], dtype=pl.Int32),
            "finalweight": [2.0, 2.0, 2.0],
        }
    )
    model_tours = raw_tours.head(1).drop("joint_tour_id").with_columns(
        pl.lit(3).alias("NUMBER_HH")
    )
    raw_run = _run_with_tours(raw_tours)
    model_run = _run_with_tours(model_tours)

    represented_raw = raw_tours.with_columns(
        household_tour_weight_expr(raw_tours, output_col="household_tour_weight")
    )
    represented_unweighted = strip_weights(raw_run).tours.with_columns(
        household_tour_weight_expr(
            strip_weights(raw_run).tours,
            output_col="household_tour_weight",
        )
    )
    assert represented_raw.height == raw_tours.height
    assert represented_raw["household_tour_weight"].to_list() == pytest.approx(
        [2.0 / 3.0] * 3
    )
    assert represented_unweighted["household_tour_weight"].to_list() == (
        pytest.approx([1.0 / 3.0] * 3)
    )

    for run, expected in (
        (raw_run, 2.0),
        (model_run, 2.0),
        (strip_weights(raw_run), 1.0),
        (strip_weights(model_run), 1.0),
    ):
        assert joint_party_size(run).filter(pl.col("party_size") == 3)[
            "joint_tour_count"
        ].item() == pytest.approx(expected)
        assert 1 not in joint_party_size(run)["party_size"].to_list()
        assert joint_composition(run).filter(pl.col("tour_composition") == "mixed")[
            "joint_tour_count"
        ].item() == pytest.approx(expected)
        assert joint_composition_by_party_size(run, None).filter(
            (pl.col("tour_composition") == "mixed") & (pl.col("party_size") == 3)
        )["joint_tour_count"].item() == pytest.approx(expected)
        assert tour_tod(run, SimpleNamespace()).filter(
            (pl.col("tour_purpose") == "shopping") & (pl.col("time_bin") == 10)
        )["departure_tour_count"].item() == pytest.approx(expected)
        assert tour_distance(run, SimpleNamespace()).filter(
            (pl.col("tour_purpose") == "shopping")
            & (pl.col("distance_bin") == "4")
        )["tour_count"].item() == pytest.approx(expected)
        assert stop_freq(run, SimpleNamespace()).filter(
            (pl.col("tour_purpose") == "shopping")
            & (pl.col("outbound_stop_count") == 1)
            & (pl.col("inbound_stop_count") == 2)
        )["tour_count"].item() == pytest.approx(expected)
        assert tour_category(run, SimpleNamespace()).filter(
            pl.col("tour_category") == "joint"
        )["tour_count"].item() == pytest.approx(expected)
        assert tour_purpose(run, SimpleNamespace()).filter(
            pl.col("tour_purpose") == "shopping"
        )["tour_count"].item() == pytest.approx(expected)


def test_household_tour_weight_does_not_use_sentinel_party_size() -> None:
    tours = pl.DataFrame(
        {
            "tour_category": ["joint", "joint"],
            "joint_tour_id": [200, 200],
            "NUMBER_HH": [995, 995],
            "number_of_participants": [995, 995],
            "finalweight": [4.0, 4.0],
        }
    )

    represented = tours.with_columns(
        household_tour_weight_expr(tours, output_col="household_tour_weight")
    )

    assert represented.height == tours.height
    assert represented["household_tour_weight"].to_list() == [4.0, 4.0]
