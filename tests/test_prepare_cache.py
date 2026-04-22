from __future__ import annotations

from pathlib import Path
import sys

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processor.models import RunData
from processor.prepare import (
    PreparedCacheError,
    build_run_fingerprint,
    load_prepared_run_cache,
    prepare_data,
    prepared_root,
    write_prepared_run_cache,
)
from runtime.config import Config


def _write_config(
    tmp_path: Path,
    *,
    visualizer_lines: list[str] | None = None,
    column_lines: list[str] | None = None,
) -> Config:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "config.yaml"
    lines = [
        'name: "Prepared Cache Test"',
        "runs: []",
        "summaries:",
        "  root: summary_cache",
        "  weighting_modes:",
        "    - weighted",
        "    - unweighted",
        "visualizer:",
        '  dashboard_title: "Prepared Cache Test"',
    ]
    if visualizer_lines:
        lines.extend(f"  {line}" for line in visualizer_lines)
    if column_lines:
        lines.append("columns:")
        lines.extend(f"  {line}" for line in column_lines)
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return Config.from_yaml(config_path)


def _raw_run() -> RunData:
    return RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file="C:/runs/base/skims.omx",
        hh=pl.DataFrame(
            {
                "household_id": [1],
                "home_zone_id": [10],
                "auto_ownership": [2],
                "hhsize": [3],
                "num_workers": [1],
                "num_adults": [2],
            }
        ),
        per=pl.DataFrame(
            {
                "person_id": [101],
                "household_id": [1],
                "ptype": [1],
                "home_zone_id": [10],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [1001],
                "person_id": [101],
                "household_id": [1],
                "primary_purpose": [1],
                "tour_type": ["eatout"],
                "tour_mode": ["DRIVE"],
                "tour_category": ["non-mandatory"],
                "start": [8],
                "end": [10],
                "duration": [2],
                "origin": [10],
                "destination": [20],
                "stop_frequency": ["1out_0in"],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_id": [5001],
                "tour_id": [1001],
                "person_id": [101],
                "household_id": [1],
                "trip_mode": ["DRIVEALONE"],
                "purpose": ["shop"],
                "depart": [8],
                "outbound": [True],
                "trip_num": [1],
                "origin": [10],
                "destination": [20],
            }
        ),
        joint_participants=pl.DataFrame(
            {"tour_id": [], "person_id": []},
            schema={"tour_id": pl.Int64, "person_id": pl.Int64},
        ),
        land_use=pl.DataFrame(
            {"zone_id": [10, 20], "TAZ": [10, 20], "EMPLOY_TOT": [7, 8]}
        ),
        skim_matrix=None,
        skim_zone_map=None,
        hh_weight_col="hh_weight",
        person_weight_col="person_weight",
        trip_weight_col="trip_weight",
    )


def _prepared_run(config: Config) -> RunData:
    return prepare_data(_raw_run(), config)


def test_prepared_cache_round_trip_creates_default_layout(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    prepared = _prepared_run(config)
    fingerprint = build_run_fingerprint(
        label=prepared.label,
        run_dir=prepared.run_dir,
        skim_file=prepared.skim_file,
        hh_weight_col=prepared.hh_weight_col,
        person_weight_col=prepared.person_weight_col,
        trip_weight_col=prepared.trip_weight_col,
    )

    entry = write_prepared_run_cache(
        prepared,
        config,
        run_key="base",
        run_fingerprint=fingerprint,
    )

    expected_root = Path(config.summary_root).parent / "prepared_cache"
    assert prepared_root(config) == expected_root
    assert entry.cache_dir == expected_root / "base"
    assert (entry.cache_dir / "manifest.json").exists()
    assert (entry.cache_dir / "households.parquet").exists()
    assert (entry.cache_dir / "persons.parquet").exists()
    assert (entry.cache_dir / "joint_tour_participants.parquet").exists()

    loaded = load_prepared_run_cache(
        entry.cache_dir,
        config,
        expected_prepare_config_digest=config.prepare_config_digest,
        expected_run_fingerprint=fingerprint,
        expected_label="Base",
        expected_run_key="base",
    )

    assert loaded.label == "Base"
    assert loaded.run_dir == "C:/runs/base"
    assert loaded.skim_file == "C:/runs/base/skims.omx"
    assert loaded.tours["tour_purpose"].to_list() == ["eatout"]
    assert loaded.trips["trip_purpose"].to_list() == ["shop"]
    assert loaded.land_use["EMPLOYMENT"].to_list() == [7, 8]
    assert loaded.hh_weight_col == "hh_weight"
    assert loaded.person_weight_col == "person_weight"
    assert loaded.trip_weight_col == "trip_weight"


def test_prepare_config_digest_ignores_presentation_only_changes(
    tmp_path: Path,
) -> None:
    config_a = _write_config(
        tmp_path / "a",
        visualizer_lines=[
            'dashboard_title: "Dashboard A"',
            "dashboard_pages:",
            "  - overview",
            "export_html:",
            "  dashboard:",
            "    values: all",
        ],
    )
    config_b = _write_config(
        tmp_path / "b",
        visualizer_lines=[
            'dashboard_title: "Dashboard B"',
            "dashboard_pages:",
            "  - destination",
            "export_html:",
            "  dashboard:",
            "    weighting: all",
        ],
    )

    assert config_a.prepare_config_digest == config_b.prepare_config_digest


def test_prepared_cache_invalidates_when_prepare_affecting_config_changes(
    tmp_path: Path,
) -> None:
    config_a = _write_config(tmp_path / "a")
    config_b = _write_config(
        tmp_path / "b",
        column_lines=["trip_purpose: [trip_purpose, stop_purpose]"],
    )
    prepared = _prepared_run(config_a)

    entry = write_prepared_run_cache(
        prepared,
        config_a,
        run_key="base",
    )

    assert config_a.prepare_config_digest != config_b.prepare_config_digest
    with pytest.raises(PreparedCacheError, match="config digest mismatch"):
        load_prepared_run_cache(
            entry.cache_dir,
            config_b,
            expected_prepare_config_digest=config_b.prepare_config_digest,
            expected_label="Base",
            expected_run_key="base",
        )


def test_prepared_cache_detects_missing_table_file(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    prepared = _prepared_run(config)
    entry = write_prepared_run_cache(prepared, config, run_key="base")

    (entry.cache_dir / "trips.parquet").unlink()

    with pytest.raises(PreparedCacheError, match="Missing prepared table file"):
        load_prepared_run_cache(
            entry.cache_dir,
            config,
            expected_prepare_config_digest=config.prepare_config_digest,
            expected_label="Base",
            expected_run_key="base",
        )


def test_prepared_cache_detects_run_fingerprint_mismatch(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    prepared = _prepared_run(config)
    entry = write_prepared_run_cache(
        prepared,
        config,
        run_key="base",
        run_fingerprint=build_run_fingerprint(
            label="Base",
            run_dir="C:/runs/base",
            skim_file="C:/runs/base/skims.omx",
            hh_weight_col="hh_weight",
            person_weight_col="person_weight",
            trip_weight_col="trip_weight",
        ),
    )

    with pytest.raises(PreparedCacheError, match="run fingerprint mismatch"):
        load_prepared_run_cache(
            entry.cache_dir,
            config,
            expected_prepare_config_digest=config.prepare_config_digest,
            expected_run_fingerprint=build_run_fingerprint(
                label="Base",
                run_dir="C:/runs/other",
                skim_file="C:/runs/other/skims.omx",
                hh_weight_col="hh_weight",
                person_weight_col="person_weight",
                trip_weight_col="trip_weight",
            ),
            expected_label="Base",
            expected_run_key="base",
        )
