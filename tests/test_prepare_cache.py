from __future__ import annotations

from pathlib import Path
import sys

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from processor.models import RunData, TableAvailabilityMetadata
from processor.prepare.availability import (
    attach_table_availability,
    has_usable_loaded_tables,
    table_availability,
    table_diagnostics,
    table_failure_reasons,
    table_unavailable_reasons,
)
from processor.prepare.cache import (
    PreparedCacheError,
    build_run_fingerprint,
    load_custom_prepared_tables,
    load_prepared_run_cache,
    prepared_root,
    write_prepared_run_cache,
)
from processor.prepare.enrichment.pipeline import prepare_data
from processor.prepare.validation import validate_prepared_relationships
from runtime.config import Config


def _write_config(
    tmp_path: Path,
    *,
    visualizer_lines: list[str] | None = None,
    column_lines: list[str] | None = None,
    extra_lines: list[str] | None = None,
) -> Config:
    tmp_path.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "config.yaml"
    lines = [
        'name: "Prepared Cache Test"',
        "runs: []",
        "processor:",
        "  root: summary_cache",
        "  summaries:",
        "    weighting_modes:",
        "      - weighted",
        "      - unweighted",
        "visualizer:",
        '  dashboard_title: "Prepared Cache Test"',
    ]
    if visualizer_lines:
        lines.extend(f"  {line}" for line in visualizer_lines)
    if column_lines:
        lines.append("columns:")
        lines.extend(f"  {line}" for line in column_lines)
    if extra_lines:
        lines.extend(extra_lines)
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


def test_legacy_summaries_processor_keys_warn_but_still_load(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Legacy Processor Config"',
                "runs: []",
                "summaries:",
                "  root: summary_cache",
                "  weighting_modes:",
                "    - weighted",
                "visualizer:",
                '  dashboard_title: "Legacy Processor Config"',
            ]
        ),
        encoding="utf-8",
    )

    config = Config.from_yaml(config_path)

    assert config.summary_root.endswith("summary_cache")
    assert config.weighting_modes == ["weighted"]
    assert "summaries.root" in caplog.text
    assert "summaries.weighting_modes" in caplog.text


def _prepared_run(config: Config) -> RunData:
    return prepare_data(_raw_run(), config)


def _write_custom_prepared_tables(
    root: Path,
    *,
    file_format: str = "parquet",
) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    tables = {
        "households": pl.DataFrame({"household_id": [1], "finalweight": [1.0]}),
        "persons": pl.DataFrame({"person_id": [10], "household_id": [1], "finalweight": [1.0]}),
        "tours": pl.DataFrame({"tour_id": [100], "person_id": [10], "household_id": [1], "finalweight": [1.0]}),
        "trips": pl.DataFrame({"trip_id": [1000], "tour_id": [100], "person_id": [10], "finalweight": [1.0]}),
        "joint_tour_participants": pl.DataFrame({"tour_id": [], "person_id": []}),
        "land_use": pl.DataFrame({"zone_id": [1], "TAZ": [1]}),
    }
    paths: dict[str, str] = {}
    for table_id, table in tables.items():
        path = root / f"{table_id}.{file_format}"
        if file_format == "parquet":
            table.write_parquet(path)
        else:
            table.write_csv(path)
        paths[table_id] = str(path.resolve())
    return paths


def _prepared_run_with_orphan_trip() -> RunData:
    return RunData(
        label="Filtered Prepared",
        run_dir="C:/prepared/filtered",
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1], "finalweight": [1.0]}),
        per=pl.DataFrame(
            {"person_id": [10], "household_id": [1], "finalweight": [1.0]}
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [100],
                "person_id": [10],
                "household_id": [1],
                "finalweight": [1.0],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_id": [1000, 1001],
                "tour_id": [100, 999],
                "person_id": [10, 999],
                "household_id": [1, 999],
                "finalweight": [1.0, 1.0],
            }
        ),
        joint_participants=pl.DataFrame(
            {"tour_id": [], "person_id": []},
            schema={"tour_id": pl.Int64, "person_id": pl.Int64},
        ),
        land_use=pl.DataFrame({"zone_id": [1], "TAZ": [1]}),
        skim_matrix=None,
        skim_zone_map=None,
    )


def test_table_availability_infers_states_without_attached_metadata() -> None:
    inferred = RunData(
        label="Inferred",
        run_dir="C:/runs/inferred",
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1]}),
        per=pl.DataFrame(),
        tours=pl.DataFrame(),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    states = table_availability(inferred)

    assert states == {
        "households": "available",
        "persons": "empty",
        "tours": "empty",
        "trips": "empty",
        "joint_tour_participants": "empty",
        "land_use": "empty",
    }
    assert table_unavailable_reasons(inferred) == {}
    assert table_failure_reasons(inferred) == {}
    assert table_diagnostics(inferred) == {}
    assert has_usable_loaded_tables(inferred) is True

    unavailable = attach_table_availability(
        RunData(
            label="Unavailable",
            run_dir="C:/runs/unavailable",
            skim_file=None,
            hh=pl.DataFrame(),
            per=pl.DataFrame(),
            tours=pl.DataFrame(),
            trips=pl.DataFrame(),
            joint_participants=pl.DataFrame(),
            land_use=pl.DataFrame(),
            skim_matrix=None,
            skim_zone_map=None,
        ),
        table_states={
            "households": "unavailable",
            "persons": "failed",
            "tours": "unavailable",
            "trips": "failed",
            "joint_tour_participants": "unavailable",
            "land_use": "failed",
        },
        table_reasons={
            "households": "missing households",
            "persons": "person transform failed",
        },
    )

    assert has_usable_loaded_tables(unavailable) is False


def test_attach_table_availability_sets_explicit_rundata_metadata() -> None:
    run = attach_table_availability(
        RunData(
            label="Metadata",
            run_dir="C:/runs/metadata",
            skim_file=None,
            hh=pl.DataFrame(),
            per=pl.DataFrame(),
            tours=pl.DataFrame(),
            trips=pl.DataFrame(),
            joint_participants=pl.DataFrame(),
            land_use=pl.DataFrame(),
            skim_matrix=None,
            skim_zone_map=None,
        ),
        table_states={"households": "unavailable", "persons": "failed"},
        table_reasons={
            "households": "missing households",
            "persons": "person transform failed",
        },
    )

    assert run.table_availability_metadata == TableAvailabilityMetadata(
        states={"households": "unavailable", "persons": "failed"},
        diagnostics={
            "households": "missing households",
            "persons": "person transform failed",
        },
    )
    assert table_availability(run)["households"] == "unavailable"
    assert table_diagnostics(run)["persons"] == "person transform failed"


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

    expected_root = Path(config.summary_root)
    assert prepared_root(config) == expected_root
    assert entry.cache_dir == expected_root / "base" / "prepared_tables"
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


def test_config_accepts_custom_prepared_table_map_and_csv_prepare_output(
    tmp_path: Path,
) -> None:
    custom_dir = tmp_path / "custom_prepared"
    custom_dir.mkdir(parents=True, exist_ok=True)
    config = _write_config(
        tmp_path,
        extra_lines=[
            "prepare:",
            "  output:",
            "    file_format: csv",
            "runs:",
            '  - label: "Prepared Run"',
            "    prepared_table_map:",
            f"      households: {str(custom_dir / 'households.parquet').replace('\\', '/')}",
            f"      persons: {str(custom_dir / 'persons.csv').replace('\\', '/')}",
        ],
    )

    assert config.prepare_output_file_format == "csv"
    assert config.runs[0]["prepared_table_map"]["households"].endswith(
        "households.parquet"
    )
    assert config.runs[0]["prepared_table_map"]["persons"].endswith("persons.csv")


def test_config_accepts_prepare_relationship_validation_mode(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "prepare:",
            "  validation:",
            "    relationship_checks: error",
        ],
    )

    assert config.prepare_relationship_checks == "error"


def test_config_rejects_invalid_custom_prepared_table_map_and_output_format(
    tmp_path: Path,
) -> None:
    invalid_key_path = tmp_path / "invalid_key.yaml"
    invalid_key_path.write_text(
        "\n".join(
            [
                'name: "Invalid Prepared Config"',
                "runs:",
                '  - label: "Prepared Run"',
                "    prepared_table_map:",
                "      households_alias: households.parquet",
                "summaries:",
                "  root: summary_cache",
                "visualizer:",
                '  dashboard_title: "Invalid Prepared Config"',
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported table ids"):
        Config.from_yaml(invalid_key_path)

    invalid_format_path = tmp_path / "invalid_format.yaml"
    invalid_format_path.write_text(
        "\n".join(
            [
                'name: "Invalid Prepare Format"',
                "runs: []",
                "prepare:",
                "  output:",
                "    file_format: json",
                "summaries:",
                "  root: summary_cache",
                "visualizer:",
                '  dashboard_title: "Invalid Prepare Format"',
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="prepare.output.file_format"):
        Config.from_yaml(invalid_format_path)

    invalid_validation_path = tmp_path / "invalid_validation.yaml"
    invalid_validation_path.write_text(
        "\n".join(
            [
                'name: "Invalid Prepare Validation"',
                "runs: []",
                "prepare:",
                "  validation:",
                "    relationship_checks: maybe",
                "summaries:",
                "  root: summary_cache",
                "visualizer:",
                '  dashboard_title: "Invalid Prepare Validation"',
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="prepare.validation.relationship_checks"):
        Config.from_yaml(invalid_validation_path)


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


def test_prepared_cache_invalidates_when_vot_bin_mapping_changes(
    tmp_path: Path,
) -> None:
    config_a = _write_config(
        tmp_path / "a",
        extra_lines=[
            "prepare:",
            "  vot_bins:",
            "    mappings:",
            "      estimation-output:",
            "        1: L",
            "        2: M",
            "        3: M",
            "        4: H",
        ],
    )
    config_b = _write_config(
        tmp_path / "b",
        extra_lines=[
            "prepare:",
            "  vot_bins:",
            "    mappings:",
            "      estimation-output:",
            "        1: L",
            "        2: L",
            "        3: M",
            "        4: H",
        ],
    )

    assert config_a.prepare_config_digest != config_b.prepare_config_digest


def test_load_custom_prepared_tables_supports_parquet_and_csv(
    tmp_path: Path,
) -> None:
    parquet_map = _write_custom_prepared_tables(tmp_path / "parquet", file_format="parquet")
    csv_map = _write_custom_prepared_tables(tmp_path / "csv", file_format="csv")

    parquet_loaded = load_custom_prepared_tables(
        prepared_table_map=parquet_map,
        label="Parquet Run",
        run_dir="C:/prepared/parquet",
    )
    csv_loaded = load_custom_prepared_tables(
        prepared_table_map=csv_map,
        label="CSV Run",
        run_dir="C:/prepared/csv",
    )

    assert parquet_loaded.hh["household_id"].to_list() == [1]
    assert csv_loaded.per["person_id"].to_list() == [10]
    assert table_availability(parquet_loaded)["households"] == "available"
    assert table_availability(csv_loaded)["trips"] == "available"


def test_load_custom_prepared_tables_retries_csv_with_full_schema_inference(
    tmp_path: Path,
) -> None:
    prepared_map = _write_custom_prepared_tables(tmp_path / "csv_retry", file_format="csv")
    tours_path = Path(prepared_map["tours"])
    rows = ["tour_id,person_id,household_id,finalweight,AWDT"]
    rows.extend(f"{i},{10 + i},{1 + i},1.0,{i}" for i in range(10050))
    rows.append("10050,10060,10051,1.0,\"4,238\"")
    tours_path.write_text("\n".join(rows), encoding="utf-8")

    loaded = load_custom_prepared_tables(
        prepared_table_map=prepared_map,
        label="CSV Retry",
        run_dir="C:/prepared/csv-retry",
    )

    assert loaded.tours.height == 10051
    assert loaded.tours.schema["AWDT"] == pl.String
    assert loaded.tours["AWDT"][-1] == "4,238"


def test_validate_prepared_relationships_reports_orphan_rows() -> None:
    validation = validate_prepared_relationships(_prepared_run_with_orphan_trip())

    failed = {
        (
            check.check.source_table_id,
            check.check.source_key,
            check.check.target_table_id,
            check.check.target_key,
        ): check.orphan_count
        for check in validation.failed_checks
    }

    assert validation.passed is False
    assert failed[("trips", "household_id", "households", "household_id")] == 1
    assert failed[("trips", "person_id", "persons", "person_id")] == 1
    assert failed[("trips", "tour_id", "tours", "tour_id")] == 1


def test_validate_prepared_relationships_skips_unavailable_optional_tables() -> None:
    run = attach_table_availability(
        RunData(
            label="Optional Missing",
            run_dir="C:/prepared",
            skim_file=None,
            hh=pl.DataFrame({"household_id": [1], "finalweight": [1.0]}),
            per=pl.DataFrame(
                {"person_id": [10], "household_id": [1], "finalweight": [1.0]}
            ),
            tours=pl.DataFrame(
                {
                    "tour_id": [100],
                    "person_id": [10],
                    "household_id": [1],
                    "finalweight": [1.0],
                }
            ),
            trips=pl.DataFrame(
                {
                    "trip_id": [1000],
                    "tour_id": [100],
                    "person_id": [10],
                    "household_id": [1],
                    "finalweight": [1.0],
                }
            ),
            joint_participants=pl.DataFrame(),
            land_use=pl.DataFrame(),
            skim_matrix=None,
            skim_zone_map=None,
        ),
        table_states={
            "households": "available",
            "persons": "available",
            "tours": "available",
            "trips": "available",
            "joint_tour_participants": "unavailable",
            "land_use": "unavailable",
        },
    )
    validation = validate_prepared_relationships(run)

    skipped = {
        (
            check.check.source_table_id,
            check.check.source_key,
            check.check.target_table_id,
            check.check.target_key,
        ): check.skip_reason
        for check in validation.checks
        if check.state == "skipped"
    }

    assert skipped[
        (
            "joint_tour_participants",
            "person_id",
            "persons",
            "person_id",
        )
    ] == "source table 'joint_tour_participants' is unavailable"


def test_prepared_cache_write_uses_configured_csv_output_format(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        extra_lines=[
            "prepare:",
            "  output:",
            "    file_format: csv",
        ],
    )
    prepared = _prepared_run(config)
    entry = write_prepared_run_cache(prepared, config, run_key="base")

    assert (entry.cache_dir / "households.csv").exists()
    assert entry.manifest["table_format"] == "csv"

    loaded = load_prepared_run_cache(
        entry.cache_dir,
        config,
        expected_prepare_config_digest=config.prepare_config_digest,
        expected_label="Base",
        expected_run_key="base",
    )
    assert loaded.hh["household_id"].to_list() == [1]


def test_prepared_cache_invalidates_when_student_type_config_changes(
    tmp_path: Path,
) -> None:
    config_a = _write_config(
        tmp_path / "a",
        column_lines=["total_employment: EMP_TOTAL"],
    )
    config_b = _write_config(
        tmp_path / "b",
        column_lines=["total_employment: EMP_TOTAL"],
        visualizer_lines=None,
    )
    config_path = Path(config_b.config_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + "\n"
        + "\n".join(
            [
                "student_types:",
                "  - label: School",
                "    land_use_columns: [ENROLLGRADEKto8, ENROLLGRADE9to12]",
                "  - label: University",
                "    land_use_columns: [COLLEGEENROLL]",
            ]
        ),
        encoding="utf-8",
    )
    config_b = Config.from_yaml(config_path)

    assert config_a.prepare_config_digest != config_b.prepare_config_digest


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


def test_prepared_cache_detects_file_map_only_run_fingerprint_mismatch(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    prepared = _prepared_run(config)
    fingerprint = build_run_fingerprint(
        label="Base",
        run_dir="C:/runs/base",
        skim_file="C:/runs/base/skims.omx",
        file_map={"households": "final_households", "trips": "final_trips"},
        hh_weight_col="hh_weight",
        person_weight_col="person_weight",
        trip_weight_col="trip_weight",
    )
    entry = write_prepared_run_cache(
        prepared,
        config,
        run_key="base",
        run_fingerprint=fingerprint,
    )

    assert entry.manifest["source_file_map"] == {
        "households": "final_households",
        "joint_tour_participants": "final_joint_tour_participants",
        "land_use": "final_land_use",
        "persons": "final_persons",
        "tours": "final_tours",
        "trips": "final_trips",
    }

    with pytest.raises(PreparedCacheError, match="run fingerprint mismatch"):
        load_prepared_run_cache(
            entry.cache_dir,
            config,
            expected_prepare_config_digest=config.prepare_config_digest,
            expected_run_fingerprint=build_run_fingerprint(
                label="Base",
                run_dir="C:/runs/base",
                skim_file="C:/runs/base/skims.omx",
                file_map={"households": "final_hh", "trips": "final_trips"},
                hh_weight_col="hh_weight",
                person_weight_col="person_weight",
                trip_weight_col="trip_weight",
            ),
            expected_label="Base",
            expected_run_key="base",
        )


def test_prepared_cache_detects_skimjoin_only_run_fingerprint_mismatch(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    prepared = _prepared_run(config)
    fingerprint = build_run_fingerprint(
        label="Base",
        run_dir="C:/runs/base",
        skim_file="C:/runs/base/skims.omx",
        skimjoin={
            "enabled": True,
            "config_path": "C:/configs/skimjoin_a.yaml",
            "config_digest": "digest-a",
        },
        hh_weight_col="hh_weight",
        person_weight_col="person_weight",
        trip_weight_col="trip_weight",
    )
    entry = write_prepared_run_cache(
        prepared,
        config,
        run_key="base",
        run_fingerprint=fingerprint,
    )

    with pytest.raises(PreparedCacheError, match="run fingerprint mismatch"):
        load_prepared_run_cache(
            entry.cache_dir,
            config,
            expected_prepare_config_digest=config.prepare_config_digest,
            expected_run_fingerprint=build_run_fingerprint(
                label="Base",
                run_dir="C:/runs/base",
                skim_file="C:/runs/base/skims.omx",
                skimjoin={
                    "enabled": True,
                    "config_path": "C:/configs/skimjoin_b.yaml",
                    "config_digest": "digest-b",
                },
                hh_weight_col="hh_weight",
                person_weight_col="person_weight",
                trip_weight_col="trip_weight",
            ),
            expected_label="Base",
            expected_run_key="base",
        )


def test_prepared_cache_round_trip_preserves_empty_vs_unavailable_table_states(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    prepared = attach_table_availability(
        _prepared_run(config),
        table_states={
            "households": "available",
            "persons": "available",
            "tours": "available",
            "trips": "available",
            "joint_tour_participants": "empty",
            "land_use": "unavailable",
        },
        table_reasons={"land_use": "configured file was missing"},
    )
    prepared = RunData(
        label=prepared.label,
        run_dir=prepared.run_dir,
        skim_file=prepared.skim_file,
        hh=prepared.hh,
        per=prepared.per,
        tours=prepared.tours,
        trips=prepared.trips,
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=prepared.skim_matrix,
        skim_zone_map=prepared.skim_zone_map,
        hh_weight_col=prepared.hh_weight_col,
        person_weight_col=prepared.person_weight_col,
        trip_weight_col=prepared.trip_weight_col,
    )
    prepared = attach_table_availability(
        prepared,
        table_states={
            "households": "available",
            "persons": "available",
            "tours": "available",
            "trips": "available",
            "joint_tour_participants": "empty",
            "land_use": "unavailable",
        },
        table_reasons={"land_use": "configured file was missing"},
    )

    entry = write_prepared_run_cache(prepared, config, run_key="base")
    loaded = load_prepared_run_cache(
        entry.cache_dir,
        config,
        expected_prepare_config_digest=config.prepare_config_digest,
        expected_label="Base",
        expected_run_key="base",
    )

    assert table_availability(loaded)["joint_tour_participants"] == "empty"
    assert table_availability(loaded)["land_use"] == "unavailable"
    assert table_unavailable_reasons(loaded)["land_use"] == "configured file was missing"
    assert loaded.joint_participants.is_empty()
    assert loaded.land_use.is_empty()


def test_prepared_cache_round_trip_preserves_failed_table_state_and_diagnostic(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    prepared = attach_table_availability(
        _prepared_run(config),
        table_states={
            "households": "available",
            "persons": "available",
            "tours": "failed",
            "trips": "available",
            "joint_tour_participants": "available",
            "land_use": "available",
        },
        table_reasons={"tours": "tour enrichment failed: missing required identifier"},
    )
    prepared = RunData(
        label=prepared.label,
        run_dir=prepared.run_dir,
        skim_file=prepared.skim_file,
        hh=prepared.hh,
        per=prepared.per,
        tours=pl.DataFrame(),
        trips=prepared.trips,
        joint_participants=prepared.joint_participants,
        land_use=prepared.land_use,
        skim_matrix=prepared.skim_matrix,
        skim_zone_map=prepared.skim_zone_map,
        hh_weight_col=prepared.hh_weight_col,
        person_weight_col=prepared.person_weight_col,
        trip_weight_col=prepared.trip_weight_col,
    )
    prepared = attach_table_availability(
        prepared,
        table_states={
            "households": "available",
            "persons": "available",
            "tours": "failed",
            "trips": "available",
            "joint_tour_participants": "available",
            "land_use": "available",
        },
        table_reasons={"tours": "tour enrichment failed: missing required identifier"},
    )

    entry = write_prepared_run_cache(prepared, config, run_key="base")
    manifest = entry.manifest
    assert manifest["table_states"]["tours"] == "failed"
    assert manifest["failed_tables"]["tours"] == (
        "tour enrichment failed: missing required identifier"
    )
    assert manifest["table_diagnostics"]["tours"] == (
        "tour enrichment failed: missing required identifier"
    )

    loaded = load_prepared_run_cache(
        entry.cache_dir,
        config,
        expected_prepare_config_digest=config.prepare_config_digest,
        expected_label="Base",
        expected_run_key="base",
    )

    assert table_availability(loaded)["tours"] == "failed"
    assert table_failure_reasons(loaded)["tours"] == (
        "tour enrichment failed: missing required identifier"
    )
    assert loaded.tours.is_empty()


def test_prepared_cache_round_trip_preserves_prepare_diagnostics(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    prepared = _prepared_run(config)
    prepared.prepare_diagnostics = {
        "tours.OTAZ": {
            "total": 10,
            "unresolved": 3,
            "unresolved_share": 0.3,
            "lookup_available": True,
            "source_column": "origin",
        }
    }

    entry = write_prepared_run_cache(prepared, config, run_key="base")

    assert entry.manifest["prepare_diagnostics"] == prepared.prepare_diagnostics

    loaded = load_prepared_run_cache(
        entry.cache_dir,
        config,
        expected_prepare_config_digest=config.prepare_config_digest,
        expected_label="Base",
        expected_run_key="base",
    )

    assert loaded.prepare_diagnostics == prepared.prepare_diagnostics


def test_prepared_cache_writes_sentinel_tables_for_non_available_states(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    prepared = _prepared_run(config)
    prepared = RunData(
        label=prepared.label,
        run_dir=prepared.run_dir,
        skim_file=prepared.skim_file,
        hh=prepared.hh,
        per=prepared.per,
        tours=pl.DataFrame(),
        trips=prepared.trips,
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=prepared.skim_matrix,
        skim_zone_map=prepared.skim_zone_map,
        hh_weight_col=prepared.hh_weight_col,
        person_weight_col=prepared.person_weight_col,
        trip_weight_col=prepared.trip_weight_col,
    )
    prepared = attach_table_availability(
        prepared,
        table_states={
            "households": "available",
            "persons": "available",
            "tours": "failed",
            "trips": "available",
            "joint_tour_participants": "empty",
            "land_use": "unavailable",
        },
        table_reasons={
            "tours": "tour enrichment failed",
            "land_use": "configured file was missing",
        },
    )

    entry = write_prepared_run_cache(prepared, config, run_key="base")

    assert pl.read_parquet(entry.cache_dir / "tours.parquet").columns == ["__empty__"]
    assert pl.read_parquet(
        entry.cache_dir / "joint_tour_participants.parquet"
    ).columns == ["__empty__"]
    assert pl.read_parquet(entry.cache_dir / "land_use.parquet").columns == ["__empty__"]


def test_prepared_cache_loads_schema_version_2_manifest_without_failed_metadata(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    prepared = _prepared_run(config)
    entry = write_prepared_run_cache(prepared, config, run_key="base")
    manifest_path = entry.cache_dir / "manifest.json"
    manifest = manifest_path.read_text(encoding="utf-8")
    manifest = manifest.replace(
        f'"schema_version": {entry.manifest["schema_version"]}', '"schema_version": 2'
    )
    manifest = manifest.replace('\n  "table_diagnostics": {},', "")
    manifest = manifest.replace('\n  "failed_tables": {},', "")
    manifest = manifest.replace('\n  "prepare_diagnostics": {},', "")
    manifest_path.write_text(manifest, encoding="utf-8")

    loaded = load_prepared_run_cache(
        entry.cache_dir,
        config,
        expected_prepare_config_digest=config.prepare_config_digest,
        expected_label="Base",
        expected_run_key="base",
    )

    assert table_availability(loaded)["households"] == "available"


def test_prepared_cache_rejects_old_schema_version(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    prepared = _prepared_run(config)
    entry = write_prepared_run_cache(prepared, config, run_key="base")
    manifest_path = entry.cache_dir / "manifest.json"
    manifest = manifest_path.read_text(encoding="utf-8")
    current_schema_version = entry.manifest["schema_version"]
    manifest_path.write_text(
        manifest.replace(
            f'"schema_version": {current_schema_version}',
            '"schema_version": 1',
        ),
        encoding="utf-8",
    )

    with pytest.raises(PreparedCacheError, match="Unsupported prepared cache schema_version"):
        load_prepared_run_cache(
            entry.cache_dir,
            config,
            expected_prepare_config_digest=config.prepare_config_digest,
            expected_label="Base",
            expected_run_key="base",
        )
