from __future__ import annotations

from pathlib import Path
import sys

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processor.summarize.cache import load_summary_run_cache, write_summary_run_cache
from processor.summarize.cache_types import create_summary_run
from processor.summarize.validation_derived import (
    COUNT_LOCATION_FIT_ID,
    COUNT_LOCATION_SCATTER_ID,
    apply_validation_derived_summaries,
    build_count_location_fit_validation_summary,
    build_count_location_scatter_validation_summary,
)
from processor.summarize.external import load_summary_table_map, merge_summary_table_map_run
from runtime.config import Config
from scripts import generate_validation_demo_fixtures as fixture_generator


def _write_config(tmp_path: Path) -> Config:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Derived Validation Test"',
                "runs: []",
                "root: summary_cache",
                "summarize:",
                "  weighting_modes: [weighted, unweighted]",
                "dashboard:",
                '  title: "Derived Validation Test"',
            ]
        ),
        encoding="utf-8",
    )
    return Config.from_yaml(config_path)


def _counts() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "id": [1, 2, 3],
            "FACTYPE": [3, 3, 4],
            "am_vol": [1.0, 2.0, 3.0],
            "md_vol": [2.0, 3.0, 4.0],
            "pm_vol": [3.0, 4.0, 5.0],
            "day_vol": [10.0, 20.0, 30.0],
        }
    )


def _volumes() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "id": [1, 2, 3],
            "FACTYPE": [3, 3, 4],
            "am_vol": [7.0, 9.0, 11.0],
            "md_vol": [9.0, 11.0, 13.0],
            "pm_vol": [11.0, 13.0, 15.0],
            "day_vol": [25.0, 45.0, 65.0],
        }
    )


def test_count_location_scatter_validation_summary_and_fit_summaries() -> None:
    scatter = build_count_location_scatter_validation_summary(_counts(), _volumes())

    assert scatter.height == 12
    assert set(scatter["period"].to_list()) == {"AM", "MD", "PM", "Day"}
    assert (
        scatter.filter((pl.col("period") == "Day") & (pl.col("facility_type") == "3"))
        .sort("id")
        .to_dicts()
        == [
            {
                "id": 1,
                "facility_type": "3",
                "period": "Day",
                "observed_volume": 10.0,
                "modeled_volume": 25.0,
            },
            {
                "id": 2,
                "facility_type": "3",
                "period": "Day",
                "observed_volume": 20.0,
                "modeled_volume": 45.0,
            },
        ]
    )

    fit = build_count_location_fit_validation_summary(scatter)
    all_day = fit.filter(
        (pl.col("period") == "Day") & (pl.col("facility_type") == "All")
    ).row(0, named=True)
    facility_day = fit.filter(
        (pl.col("period") == "Day") & (pl.col("facility_type") == "3")
    ).row(0, named=True)

    assert round(all_day["slope"], 6) == 2.0
    assert round(all_day["intercept"], 6) == 5.0
    assert round(all_day["r_squared"], 6) == 1.0
    assert all_day["n_locations"] == 3
    assert round(facility_day["slope"], 6) == 2.0
    assert round(facility_day["intercept"], 6) == 5.0


def test_count_location_fit_validation_summary_handles_zero_observed_variance() -> None:
    scatter = pl.DataFrame(
        {
            "id": [1, 2],
            "facility_type": ["3", "3"],
            "period": ["Day", "Day"],
            "observed_volume": [10.0, 10.0],
            "modeled_volume": [20.0, 30.0],
        }
    )

    fit = build_count_location_fit_validation_summary(scatter)

    assert fit.filter(pl.col("facility_type") == "3")["slope"].to_list() == [None]
    assert fit.filter(pl.col("facility_type") == "3")["r_squared"].to_list() == [None]


def test_apply_validation_derived_summaries_replaces_stale_and_skips_missing() -> None:
    stale = pl.DataFrame(
        {
            "id": [999],
            "facility_type": ["All"],
            "period": ["Day"],
            "observed_volume": [999.0],
            "modeled_volume": [999.0],
        }
    )
    summary_run = create_summary_run(
        label="Run",
        run_key="run",
        summaries_by_mode={
            "weighted": {
                "count_location_counts_validation_summary": _counts(),
                "count_location_volumes_validation_summary": _volumes(),
                COUNT_LOCATION_SCATTER_ID: stale,
            },
            "unweighted": {
                "count_location_counts_validation_summary": _counts(),
                COUNT_LOCATION_SCATTER_ID: stale,
            },
        },
    )

    result = apply_validation_derived_summaries([summary_run])[0]

    weighted = result.summaries_by_mode["weighted"]
    assert weighted[COUNT_LOCATION_SCATTER_ID]["id"].max() == 3
    assert COUNT_LOCATION_FIT_ID in weighted
    assert COUNT_LOCATION_SCATTER_ID not in result.summaries_by_mode["unweighted"]
    assert COUNT_LOCATION_FIT_ID not in result.summaries_by_mode["unweighted"]


def test_summary_table_map_run_builds_and_caches_count_location_validation_derived_tables(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    counts_path = tmp_path / "counts.csv"
    volumes_path = tmp_path / "volumes.csv"
    _counts().write_csv(counts_path)
    _volumes().write_csv(volumes_path)

    validation_run = load_summary_table_map(
        summary_table_map={
            "count_location_counts_validation_summary": str(counts_path),
            "count_location_volumes_validation_summary": str(volumes_path),
        },
        label="Mapped",
        run_key="mapped",
        config=config,
    )
    merged = merge_summary_table_map_run([], validation_run)

    assert COUNT_LOCATION_SCATTER_ID in merged[0].summaries_by_mode["weighted"]
    assert COUNT_LOCATION_FIT_ID in merged[0].summaries_by_mode["weighted"]

    cache_dir = write_summary_run_cache(merged[0], config)
    loaded = load_summary_run_cache(
        cache_dir,
        config,
        expected_modes=config.weighting_modes,
        expected_summary_ids=[
            "count_location_counts_validation_summary",
            "count_location_volumes_validation_summary",
            COUNT_LOCATION_SCATTER_ID,
            COUNT_LOCATION_FIT_ID,
        ],
        expected_summary_config_digest=config.summary_config_digest,
        expected_label="Mapped",
        expected_run_key="mapped",
    )

    assert loaded.summaries_by_mode["weighted"][COUNT_LOCATION_SCATTER_ID].height == 12
    assert (
        loaded.summary_metadata_by_mode["weighted"][COUNT_LOCATION_FIT_ID]["state"]
        == "available"
    )


def test_validation_demo_fixture_generator_writes_distinct_run_tables(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_dir = tmp_path / "source"
    output_dir = source_dir / "estimated_fixtures"
    source_dir.mkdir()
    pl.DataFrame(
        {
            "id": [1],
            "FACTYPE": [3],
            "am_vol": [100.0],
            "md_vol": [200.0],
            "pm_vol": [150.0],
            "day_vol": [500.0],
        }
    ).write_csv(source_dir / "countLocCounts.csv")
    pl.DataFrame(
        {
            "id": [1],
            "From_Node": [10],
            "To_Node": [20],
            "FACTYPE": [3],
            "am_vol": [100.0],
            "md_vol": [200.0],
            "pm_vol": [150.0],
            "day_vol": [500.0],
        }
    ).write_csv(source_dir / "allLinkSummary.csv")
    for filename in ("cvm_summary.csv", "cvm_vmt_summary.csv"):
        pl.DataFrame(
            {"tod": ["AM"], "car": [10.0], "mu": [3.0], "su": [5.0], "Total": [18.0]}
        ).write_csv(source_dir / filename)
    external = {
        "tod": ["AM"],
        "hbcoll": [1.0],
        "hbo": [2.0],
        "hbr": [3.0],
        "hbs": [4.0],
        "hbsch": [5.0],
        "hbw": [6.0],
        "nhbnw": [7.0],
        "nhbw": [8.0],
        "truck": [9.0],
        "Total": [45.0],
    }
    for filename in ("ext_summary.csv", "ext_vmt_summary.csv"):
        pl.DataFrame(external).write_csv(source_dir / filename)
    flow_matrix = pl.DataFrame(
        {"": ["A", "Total"], "A": [10.0, 10.0], "Total": [10.0, 10.0]}
    )
    flow_matrix.write_csv(source_dir / "countyFlows.csv")
    flow_matrix.write_csv(source_dir / "countyFlows_JoJa.csv")

    monkeypatch.setattr(fixture_generator, "SOURCE_DIR", source_dir)
    monkeypatch.setattr(fixture_generator, "OUTPUT_DIR", output_dir)
    fixture_generator.generate()

    day_values = []
    for run in fixture_generator.RUNS:
        run_dir = output_dir / run
        assert len(list(run_dir.glob("*.csv"))) == 11
        day_values.append(
            pl.read_csv(run_dir / "count_location_volumes_validation_summary.csv")[
                "day_vol"
            ][0]
        )
        assert not pl.read_csv(run_dir / "screenline_flow_comparisons.csv").is_empty()
        assert set(pl.read_csv(run_dir / "commuting_flows.csv")[
            "origin_geography_type"
        ]) == {"district", "county"}
        commercial = pl.read_csv(
            run_dir / "commercial_vehicle_validation_summary.csv"
        )
        assert commercial["Total"][0] == commercial.select(
            pl.sum_horizontal("car", "mu", "su")
        ).item()

    assert len(set(day_values)) == 4
    assert len(list((output_dir / "observed").glob("*.csv"))) == 3
