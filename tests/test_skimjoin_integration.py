from __future__ import annotations

import math
import json
from pathlib import Path
import sys

import numpy as np
import openmatrix as omx
import polars as pl
import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import runtime.workflows as runtime_workflows
from processor.models import RunData
from processor.prepare.cache import load_prepared_run_cache, write_prepared_run_cache
from processor.skimjoin.annotate.tours import annotate_tours
from processor.skimjoin.annotate.trips import annotate_trips
from processor.skimjoin.config.validation import ConfigValidationError, load_config, validate_config
from processor.skimjoin.hypothetical_sidecars import (
    TOUR_HYPOTHETICAL_SIDECAR_SCHEMA,
    TRIP_HYPOTHETICAL_SIDECAR_SCHEMA,
    build_hypothetical_sidecars,
)
from processor.skimjoin.inventory import inventory_skim_files
from processor.skimjoin.pipeline import apply_skimjoin
from processor.skimjoin.runtime_execution import _validate_runtime_inventory
from processor.skimjoin.skimstore.omx import OmxSkimStore
from processor.summarize import cache_types as summary_cache_types
from processor.summarize import builder as summary_builder
from processor.summarize.contracts import empty_summary_frame
from processor.summarize.summaries import skimjoin as skimjoin_summaries
from runtime.config import Config, config_for_run


def _write_main_config(
    tmp_path: Path,
    *,
    run_dir: Path | None = None,
    skimjoin_enabled: bool = True,
    skimjoin_config_name: str | None = "skimjoin.yaml",
    run_skimjoin_lines: list[str] | None = None,
    use_maz: bool = False,
) -> Config:
    config_path = tmp_path / "config.yaml"
    run_dir = run_dir or (tmp_path / "run")
    lines = [
        'name: "Skimjoin Integration Test"',
        "root: summary_cache",
        "dashboard:",
        '  title: "Skimjoin Integration Test"',
        "pipeline:",
        (
            "  steps: [prepare, skimjoin, summarize, dashboard]"
            if skimjoin_enabled
            else "  steps: [summarize, dashboard]"
        ),
        "zones:",
        f"  use_maz: {'true' if use_maz else 'false'}",
        "runs:",
        f'  - dir: "{run_dir.as_posix()}"',
        '    label: "Run A"',
    ]
    if run_skimjoin_lines:
        lines.append("    skimjoin:")
        lines.extend(f"      {line}" for line in run_skimjoin_lines)
    lines.append("skimjoin:")
    if skimjoin_config_name is not None:
        lines.extend(
            [
                "  defaults:",
                f"    config_path: {skimjoin_config_name}",
            ]
        )
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return Config.from_yaml(config_path)


def _write_skimjoin_config(
    tmp_path: Path,
    *,
    skim_file: Path | None = None,
    skim_files: list[Path] | None = None,
    trip_id_column: str = "trip_id",
    trip_dimension_source_column: str = "depart",
    outbound_tour_dimension_source_column: str = "start",
    inbound_tour_dimension_source_column: str = "first_inbound_trip_depart",
    zone_mapping_extra_lines: list[str] | None = None,
    extra_lines: list[str] | None = None,
    include_default_mode: bool = True,
) -> Path:
    config_path = tmp_path / "skimjoin.yaml"
    resolved_skim_files = list(skim_files or ([] if skim_file is None else [skim_file]))
    lines = [
        "project:",
        f"  skim_files:",
    ]
    lines.extend(f"    - {path.name}" for path in resolved_skim_files)
    lines.extend(
        [
            "  trips_table: ignored_trips.parquet",
            "  tours_table: ignored_tours.parquet",
            "activitysim:",
            "  trip_mode_column: trip_mode",
            "  tour_mode_column: tour_mode",
            f"  trip_id_column: {trip_id_column}",
            "  tour_id_column: tour_id",
            "  outbound_column: outbound",
            "defaults:",
            "  origin: OTAZ",
            "  destination: DTAZ",
            "  output_prefix: skim_",
            "zone_mapping:",
            "  lookup_name: taz",
        ]
    )
    if zone_mapping_extra_lines:
        lines.extend(zone_mapping_extra_lines)
    lines.extend(
        [
            "dimensions:",
            "  PERIOD:",
            "    source_columns:",
            f"      trip_source_column: {trip_dimension_source_column}",
            f"      outbound_tour_source_column: {outbound_tour_dimension_source_column}",
            f"      inbound_tour_source_column: {inbound_tour_dimension_source_column}",
        ]
    )
    if include_default_mode:
        lines.extend(
            [
                "modes:",
                "  SOV:",
                "    time:",
                "      matrix: SOV_TIME",
            ]
        )
    if extra_lines:
        lines.extend(extra_lines)
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return config_path


def _write_prepare_run_inputs(
    run_dir: Path,
    *,
    include_income_segment: bool = False,
    include_origin_parking_zone: bool = False,
    include_o_maz: bool = False,
    trip_id_column_name: str = "trip_id",
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)

    hh = {
        "household_id": [1],
        "home_zone_id": [101],
        "auto_ownership": [1],
        "hhsize": [2],
        "num_workers": [1],
        "num_adults": [1],
    }
    if include_income_segment:
        hh["income_segment"] = [1]

    trips = {
        "tour_id": [1001],
        "person_id": [101],
        "household_id": [1],
        "trip_mode": ["SOV"],
        "purpose": ["shop"],
        "depart": [8],
        "outbound": [True],
        "trip_num": [1],
        "origin": [101],
        "destination": [102],
    }
    trips[trip_id_column_name] = [5001]
    if include_origin_parking_zone:
        trips["origin_parking_zone"] = [101]
    if include_o_maz:
        trips["o_maz"] = [101]

    pl.DataFrame(hh).write_parquet(run_dir / "final_households.parquet")
    pl.DataFrame(
        {
            "person_id": [101],
            "household_id": [1],
            "ptype": [1],
            "home_zone_id": [101],
        }
    ).write_parquet(run_dir / "final_persons.parquet")
    pl.DataFrame(
        {
            "tour_id": [1001],
            "person_id": [101],
            "household_id": [1],
            "primary_purpose": ["shop"],
            "tour_type": ["shopping"],
            "tour_mode": ["SOV"],
            "tour_category": ["non-mandatory"],
            "start": [8],
            "end": [10],
            "duration": [2],
            "origin": [101],
            "destination": [102],
        }
    ).write_parquet(run_dir / "final_tours.parquet")
    pl.DataFrame(trips).write_parquet(run_dir / "final_trips.parquet")
    pl.DataFrame(
        {"tour_id": [], "person_id": []},
        schema={"tour_id": pl.Int64, "person_id": pl.Int64},
    ).write_parquet(run_dir / "final_joint_tour_participants.parquet")
    pl.DataFrame({"zone_id": [101, 102], "TAZ": [101, 102]}).write_parquet(
        run_dir / "final_land_use.parquet"
    )


def _write_omx(path: Path, *, matrix_name: str = "SOV_TIME") -> None:
    handle = omx.open_file(str(path), "w")
    handle[matrix_name] = np.array([[1.0, 2.0], [3.0, 4.0]])
    handle.create_mapping("taz", np.array([101, 102], dtype=np.uint32))
    handle.close()


def _write_omx_with_lookup(
    path: Path,
    *,
    matrix_name: str,
    lookup_name: str,
    values: np.ndarray | None = None,
) -> None:
    handle = omx.open_file(str(path), "w")
    handle[matrix_name] = (
        values if values is not None else np.array([[1.0, 2.0], [3.0, 4.0]])
    )
    handle.create_mapping(lookup_name, np.array([101, 102], dtype=np.uint32))
    handle.close()


def _write_csv_skim(
    path: Path,
    *,
    rows: list[dict[str, object]] | None = None,
) -> None:
    pl.DataFrame(
        rows
        or [
            {"maz": 101, "walk_dist_local_bus": 0.25, "walk_dist_premium_transit": 0.5},
            {"maz": 102, "walk_dist_local_bus": 0.75, "walk_dist_premium_transit": 1.0},
        ]
    ).write_csv(path)


def _write_csv_od_skim(
    path: Path,
    *,
    rows: list[dict[str, object]] | None = None,
) -> None:
    pl.DataFrame(
        rows
        or [
            {"OMAZ": 101, "DMAZ": 101, "DISTWALK": 0.0, "actual": 0.0},
            {"OMAZ": 101, "DMAZ": 102, "DISTWALK": 0.5, "actual": 10.0},
            {"OMAZ": 102, "DMAZ": 101, "DISTWALK": 0.75, "actual": 15.0},
            {"OMAZ": 102, "DMAZ": 102, "DISTWALK": 0.0, "actual": 0.0},
        ]
    ).write_csv(path)


def _write_network_los(
    path: Path,
    *,
    periods: list[int] | None = None,
    labels: list[str] | None = None,
) -> None:
    periods = periods or [0, 6, 12]
    labels = labels or ["EA", "AM"]
    path.write_text(
        "\n".join(
            [
                "skim_time_periods:",
                "  periods:",
                *[f"    - {value}" for value in periods],
                "  labels:",
                *[f"    - {value}" for value in labels],
            ]
        ),
        encoding="utf-8",
    )


def test_config_loads_separate_skimjoin_config_and_digest(tmp_path: Path) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)

    config = _write_main_config(tmp_path, skimjoin_enabled=True)

    assert config.skimjoin_step_enabled() is True
    assert config.skimjoin.config_path == str((tmp_path / "skimjoin.yaml").resolve())
    assert config.skimjoin.config_digest
    assert "skimjoin_trip_component_stats" in summary_builder.DEFAULT_SUMMARY_IDS


def test_config_loads_integrated_skimjoin_without_activitysim_table_paths(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path, matrix_name="SOV_TIME")
    config_path = tmp_path / "skimjoin.yaml"
    lines = [
        "project:",
        "  skim_files:",
        f"    - {skim_path.name}",
        "activitysim:",
        "  trip_mode_column: trip_mode",
        "  trip_id_column: trip_id",
        "  tour_id_column: tour_id",
        "  outbound_column: outbound",
        "defaults:",
        "  origin: OTAZ",
        "  destination: DTAZ",
        "modes:",
        "  SOV:",
        "    time:",
        "      matrix: SOV_TIME",
    ]
    config_path.write_text("\n".join(lines), encoding="utf-8")

    config = _write_main_config(tmp_path, skimjoin_enabled=True)

    assert config.skimjoin_step_enabled() is True
    assert config.skimjoin.normalized_config is not None


def test_skimjoin_config_rejects_removed_mode_column_field() -> None:
    with pytest.raises(Exception, match="mode_column"):
        load_config(
            {
                "skim_files": ["dummy.omx"],
                "activitysim": {
                    "mode_column": "trip_mode",
                },
                "modes": {"SOV": {"time": {"matrix": "SOV_TIME"}}},
            },
            require_activitysim_tables=False,
        )


def test_skimjoin_config_rejects_blank_explicit_source_columns() -> None:
    with pytest.raises(Exception, match="cannot be blank"):
        load_config(
            {
                "skim_files": ["dummy.omx"],
                "activitysim": {"trip_mode_column": "trip_mode"},
                "dimensions": {
                    "TOD": {
                        "source_columns": {
                            "trip_source_column": "   ",
                            "outbound_tour_source_column": "start_hour",
                            "inbound_tour_source_column": "first_inbound_trip_depart",
                        }
                    }
                },
                "modes": {"SOV": {"time": {"matrix": "SOV_TIME"}}},
            },
            require_activitysim_tables=False,
        )


def test_config_allows_run_level_skimjoin_config_without_global_path(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "run_level.omx"
    _write_omx(skim_path, matrix_name="RUN_LEVEL_TIME")
    run_config_path = tmp_path / "run_level.yaml"
    run_config_path.write_text(
        "\n".join(
            [
                "project:",
                "  skim_files:",
                f"    - {skim_path.name}",
                "activitysim:",
                "  trip_mode_column: trip_mode",
                "  trip_id_column: trip_id",
                "  tour_id_column: tour_id",
                "  outbound_column: outbound",
                "defaults:",
                "  origin: OTAZ",
                "  destination: DTAZ",
                "modes:",
                "  SOV:",
                "    time:",
                "      matrix: RUN_LEVEL_TIME",
            ]
        ),
        encoding="utf-8",
    )

    config = _write_main_config(
        tmp_path,
        skimjoin_enabled=True,
        skimjoin_config_name=None,
        run_skimjoin_lines=[f"config_path: {run_config_path.name}"],
    )

    assert config.skimjoin_step_enabled() is True
    assert config.skimjoin.config_path is None
    resolved = config_for_run(config, config.runs[0])
    assert resolved.skimjoin.config_path == str(run_config_path.resolve())
    assert resolved.skimjoin.normalized_config is not None
    assert resolved.skimjoin.normalized_config.trip_lookups[0].matrix == "RUN_LEVEL_TIME"


def test_run_level_skimjoin_config_path_overrides_global_config_path(
    tmp_path: Path,
) -> None:
    global_skim_path = tmp_path / "global.omx"
    run_skim_path = tmp_path / "run_level.omx"
    _write_omx(global_skim_path, matrix_name="GLOBAL_TIME")
    _write_omx(run_skim_path, matrix_name="RUN_TIME")
    (tmp_path / "skimjoin.yaml").write_text(
        "\n".join(
            [
                "project:",
                "  skim_files:",
                f"    - {global_skim_path.name}",
                "activitysim:",
                "  trip_mode_column: trip_mode",
                "  trip_id_column: trip_id",
                "  tour_id_column: tour_id",
                "  outbound_column: outbound",
                "defaults:",
                "  origin: OTAZ",
                "  destination: DTAZ",
                "modes:",
                "  SOV:",
                "    time:",
                "      matrix: GLOBAL_TIME",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "run_override.yaml").write_text(
        "\n".join(
            [
                "project:",
                "  skim_files:",
                f"    - {run_skim_path.name}",
                "activitysim:",
                "  trip_mode_column: trip_mode",
                "  trip_id_column: trip_id",
                "  tour_id_column: tour_id",
                "  outbound_column: outbound",
                "defaults:",
                "  origin: OTAZ",
                "  destination: DTAZ",
                "modes:",
                "  SOV:",
                "    time:",
                "      matrix: RUN_TIME",
            ]
        ),
        encoding="utf-8",
    )

    config = _write_main_config(
        tmp_path,
        skimjoin_enabled=True,
        skimjoin_config_name="skimjoin.yaml",
        run_skimjoin_lines=["config_path: run_override.yaml"],
    )

    assert config.skimjoin.normalized_config is not None
    assert config.skimjoin.normalized_config.trip_lookups[0].matrix == "GLOBAL_TIME"
    resolved = config_for_run(config, config.runs[0])
    assert resolved.skimjoin.normalized_config is not None
    assert resolved.skimjoin.normalized_config.trip_lookups[0].matrix == "RUN_TIME"


def test_run_level_skim_files_override_config_level_project_skim_files(
    tmp_path: Path,
) -> None:
    global_skim_path = tmp_path / "global.omx"
    override_skim_path = tmp_path / "override.omx"
    _write_omx(global_skim_path, matrix_name="SOV_TIME")
    _write_omx(override_skim_path, matrix_name="SOV_TIME")
    _write_skimjoin_config(tmp_path, skim_file=global_skim_path)

    config = _write_main_config(
        tmp_path,
        skimjoin_enabled=True,
        run_skimjoin_lines=[
            "skim_files:",
            f'  - "{override_skim_path.resolve().as_posix()}"',
        ],
    )

    resolved = config_for_run(config, config.runs[0])
    assert resolved.skimjoin.resolved_skim_files == (str(override_skim_path.resolve()),)
    assert resolved.skimjoin.normalized_config is not None
    assert resolved.skimjoin.normalized_config.skim_files == [
        str(override_skim_path.resolve())
    ]


def test_run_level_network_los_file_overrides_config_level_project_network_los_file(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path, matrix_name="SOV_TIME__EA")
    handle = omx.open_file(str(skim_path), "a")
    handle["SOV_TIME__AM"] = np.array([[5.0, 6.0], [7.0, 8.0]])
    handle.close()
    global_network_los = tmp_path / "global_network_los.yaml"
    override_network_los = tmp_path / "override_network_los.yaml"
    _write_network_los(global_network_los, periods=[0, 12, 24], labels=["EA", "MD"])
    _write_network_los(override_network_los, periods=[0, 6, 12], labels=["EA", "AM"])
    (tmp_path / "skimjoin.yaml").write_text(
        "\n".join(
            [
                "project:",
                "  skim_files:",
                f"    - {skim_path.name}",
                f"  network_los_file: {global_network_los.name}",
                "activitysim:",
                "  trip_mode_column: trip_mode",
                "  trip_id_column: trip_id",
                "  tour_id_column: tour_id",
                "  outbound_column: outbound",
                "dimensions:",
                "  PERIOD:",
                "    source_columns:",
                "      trip_source_column: depart",
                "      outbound_tour_source_column: start",
                "      inbound_tour_source_column: first_inbound_trip_depart",
                "    values_from_network_los: true",
                "modes:",
                "  SOV:",
                "    time:",
                "      matrix: SOV_TIME__{PERIOD}",
            ]
        ),
        encoding="utf-8",
    )

    config = _write_main_config(
        tmp_path,
        skimjoin_enabled=True,
        run_skimjoin_lines=[f"network_los_file: {override_network_los.name}"],
    )

    resolved = config_for_run(config, config.runs[0])
    assert resolved.skimjoin.resolved_network_los_file == str(
        override_network_los.resolve()
    )
    normalized = resolved.skimjoin.normalized_config
    assert normalized is not None
    assert normalized.trip_lookups[0].dimensions["PERIOD"].values["1"] == "EA"
    assert normalized.trip_lookups[0].dimensions["PERIOD"].values["7"] == "AM"


def test_run_level_skimjoin_requires_resolvable_config_path_when_enabled(
    tmp_path: Path,
) -> None:
    config = _write_main_config(
        tmp_path,
        skimjoin_enabled=True,
        skimjoin_config_name=None,
    )

    with pytest.raises(ValueError, match="no skimjoin config_path could be resolved"):
        config_for_run(config, config.runs[0])


def test_run_level_skimjoin_can_be_disabled_without_a_config_path(
    tmp_path: Path,
) -> None:
    config = _write_main_config(
        tmp_path,
        skimjoin_enabled=True,
        skimjoin_config_name=None,
        run_skimjoin_lines=["enabled: false"],
    )

    resolved = config_for_run(config, config.runs[0])

    assert config.skimjoin_step_enabled() is True
    assert resolved.skimjoin.enabled is False
    assert resolved.skimjoin_step_enabled() is False


def test_run_level_skimjoin_enabled_cannot_override_the_global_pipeline(
    tmp_path: Path,
) -> None:
    config = _write_main_config(
        tmp_path,
        skimjoin_enabled=False,
        skimjoin_config_name=None,
        run_skimjoin_lines=["enabled: true"],
    )

    resolved = config_for_run(config, config.runs[0])

    assert resolved.skimjoin_step_enabled() is False


def test_run_level_skimjoin_enabled_rejects_non_boolean_values(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match=r"runs\[0\]\.skimjoin\.enabled must be true or false",
    ):
        _write_main_config(
            tmp_path,
            skimjoin_enabled=True,
            skimjoin_config_name=None,
            run_skimjoin_lines=["enabled: sometimes"],
        )


def test_run_level_skimjoin_missing_config_file_raises_clear_error(
    tmp_path: Path,
) -> None:
    config = _write_main_config(
        tmp_path,
        skimjoin_enabled=True,
        skimjoin_config_name=None,
        run_skimjoin_lines=["config_path: missing_run_skimjoin.yaml"],
    )

    with pytest.raises(ValueError, match="skimjoin.config_path does not exist"):
        config_for_run(config, config.runs[0])


def test_run_level_skimjoin_invalid_yaml_raises(
    tmp_path: Path,
) -> None:
    bad_config = tmp_path / "bad_skimjoin.yaml"
    bad_config.write_text("project:\n  skim_files: [\n", encoding="utf-8")
    config = _write_main_config(
        tmp_path,
        skimjoin_enabled=True,
        skimjoin_config_name=None,
        run_skimjoin_lines=[f"config_path: {bad_config.name}"],
    )

    with pytest.raises(Exception, match="while parsing"):
        config_for_run(config, config.runs[0])


def test_run_level_skimjoin_requires_skim_files_after_override_and_config_fallback(
    tmp_path: Path,
) -> None:
    empty_config = tmp_path / "skimjoin_empty_files.yaml"
    empty_config.write_text(
        "\n".join(
            [
                "skim_files: []",
                "activitysim:",
                "  trip_mode_column: trip_mode",
                "  trip_id_column: trip_id",
                "  tour_id_column: tour_id",
                "  outbound_column: outbound",
                "defaults:",
                "  origin: OTAZ",
                "  destination: DTAZ",
                "modes:",
                "  SOV:",
                "    time:",
                "      matrix: SOV_TIME",
            ]
        ),
        encoding="utf-8",
    )
    config = _write_main_config(
        tmp_path,
        skimjoin_enabled=True,
        skimjoin_config_name=None,
        run_skimjoin_lines=[f"config_path: {empty_config.name}"],
    )

    with pytest.raises(ValueError, match="requires at least one skim file"):
        config_for_run(config, config.runs[0])


def test_run_level_skimjoin_requires_period_mapping_when_period_placeholder_needs_mapping(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "period.omx"
    _write_omx(skim_path, matrix_name="SOV_TIME__AM")
    period_config = tmp_path / "period_missing_mapping.yaml"
    period_config.write_text(
        "\n".join(
            [
                "project:",
                "  skim_files:",
                f"    - {skim_path.name}",
                "activitysim:",
                "  trip_mode_column: trip_mode",
                "  trip_id_column: trip_id",
                "  tour_id_column: tour_id",
                "  outbound_column: outbound",
                "dimensions:",
                "  PERIOD:",
                "    source_columns:",
                "      trip_source_column: depart",
                "      outbound_tour_source_column: start",
                "      inbound_tour_source_column: first_inbound_trip_depart",
                "    values_from_network_los: true",
                "modes:",
                "  SOV:",
                "    time:",
                "      matrix: SOV_TIME__{PERIOD}",
            ]
        ),
        encoding="utf-8",
    )
    config = _write_main_config(
        tmp_path,
        skimjoin_enabled=True,
        skimjoin_config_name=None,
        run_skimjoin_lines=[f"config_path: {period_config.name}"],
    )

    with pytest.raises(
        ValueError,
        match="dimensions\\.PERIOD\\.values_from_network_los requires project\\.network_los_file",
    ):
        config_for_run(config, config.runs[0])


def test_load_config_requires_dimension_source_columns(tmp_path: Path) -> None:
    skim_path = tmp_path / "period.omx"
    _write_omx(skim_path, matrix_name="SOV_TIME__AM")

    with pytest.raises(ValidationError, match="source_columns"):
        load_config(
            {
                "project": {"skim_files": [str(skim_path)]},
                "activitysim": {
                    "trip_mode_column": "trip_mode",
                    "trip_id_column": "trip_id",
                    "tour_id_column": "tour_id",
                    "outbound_column": "outbound",
                },
                "dimensions": {
                    "PERIOD": {
                        "values": {"8": "AM"},
                    }
                },
                "modes": {"SOV": {"time": {"matrix": "SOV_TIME__{PERIOD}"}}},
            }
        )


def test_load_config_rejects_removed_dimension_source_column_field(tmp_path: Path) -> None:
    skim_path = tmp_path / "period.omx"
    _write_omx(skim_path, matrix_name="SOV_TIME__AM")

    with pytest.raises(ValidationError, match="source_column"):
        load_config(
            {
                "project": {"skim_files": [str(skim_path)]},
                "activitysim": {
                    "trip_mode_column": "trip_mode",
                    "trip_id_column": "trip_id",
                    "tour_id_column": "tour_id",
                    "outbound_column": "outbound",
                },
                "dimensions": {
                    "PERIOD": {
                        "source_column": "depart",
                        "values": {"8": "AM"},
                    }
                },
                "modes": {"SOV": {"time": {"matrix": "SOV_TIME__{PERIOD}"}}},
            }
        )


def test_period_dimension_explicit_values_override_loaded_network_los_labels(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "period.omx"
    _write_omx(skim_path, matrix_name="SOV_TIME__AM")
    network_los = tmp_path / "network_los.yaml"
    _write_network_los(network_los, periods=[0, 6, 12], labels=["EA", "AM"])
    config_path = tmp_path / "skimjoin.yaml"
    config_path.write_text(
        "\n".join(
            [
                "project:",
                "  skim_files:",
                f"    - {skim_path.name}",
                f"  network_los_file: {network_los.name}",
                "activitysim:",
                "  trip_mode_column: trip_mode",
                "  trip_id_column: trip_id",
                "  tour_id_column: tour_id",
                "  outbound_column: outbound",
                "dimensions:",
                "  PERIOD:",
                "    source_columns:",
                "      trip_source_column: depart",
                "      outbound_tour_source_column: start",
                "      inbound_tour_source_column: first_inbound_trip_depart",
                "    values_from_network_los: true",
                "    values:",
                "      1: CUSTOM_EA",
                "modes:",
                "  SOV:",
                "    time:",
                "      matrix: SOV_TIME__{PERIOD}",
            ]
        ),
        encoding="utf-8",
    )

    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None
    assert normalized.trip_lookups[0].dimensions["PERIOD"].values["1"] == "CUSTOM_EA"
    assert normalized.trip_lookups[0].dimensions["PERIOD"].values["7"] == "AM"


def test_prepare_workflow_supports_two_runs_with_different_skimjoin_config_files(
    tmp_path: Path,
) -> None:
    run_a_dir = tmp_path / "run_a"
    run_b_dir = tmp_path / "run_b"
    _write_prepare_run_inputs(run_a_dir)
    _write_prepare_run_inputs(run_b_dir)

    skim_a = tmp_path / "run_a.omx"
    skim_b = tmp_path / "run_b.omx"
    _write_omx_with_lookup(
        skim_a,
        matrix_name="RUN_A_TIME",
        lookup_name="taz",
        values=np.array([[1.0, 11.0], [21.0, 31.0]]),
    )
    _write_omx_with_lookup(
        skim_b,
        matrix_name="RUN_B_TIME",
        lookup_name="taz",
        values=np.array([[1.0, 101.0], [201.0, 301.0]]),
    )
    (tmp_path / "skimjoin_a.yaml").write_text(
        "\n".join(
            [
                "project:",
                "  skim_files:",
                f"    - {skim_a.name}",
                "activitysim:",
                "  trip_mode_column: trip_mode",
                "  trip_id_column: trip_id",
                "  tour_id_column: tour_id",
                "  outbound_column: outbound",
                "zone_mapping:",
                "  lookup_name: taz",
                "defaults:",
                "  origin: OTAZ",
                "  destination: DTAZ",
                "modes:",
                "  SOV:",
                "    time:",
                "      matrix: RUN_A_TIME",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "skimjoin_b.yaml").write_text(
        "\n".join(
            [
                "project:",
                "  skim_files:",
                f"    - {skim_b.name}",
                "activitysim:",
                "  trip_mode_column: trip_mode",
                "  trip_id_column: trip_id",
                "  tour_id_column: tour_id",
                "  outbound_column: outbound",
                "zone_mapping:",
                "  lookup_name: taz",
                "defaults:",
                "  origin: OTAZ",
                "  destination: DTAZ",
                "modes:",
                "  SOV:",
                "    time:",
                "      matrix: RUN_B_TIME",
            ]
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Two Run Skimjoin Test"',
                "root: summary_cache",
                "dashboard:",
                '  title: "Two Run Skimjoin Test"',
                "zones:",
                "  use_maz: false",
                "runs:",
                f'  - dir: "{run_a_dir.as_posix()}"',
                '    label: "Run A"',
                "    skimjoin:",
                "      config_path: skimjoin_a.yaml",
                f'  - dir: "{run_b_dir.as_posix()}"',
                '    label: "Run B"',
                "    skimjoin:",
                "      config_path: skimjoin_b.yaml",
                "skimjoin:",
                "  defaults: {}",
                "pipeline:",
                "  steps: [prepare, skimjoin]",
            ]
        ),
        encoding="utf-8",
    )
    config = Config.from_yaml(config_path)

    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
    )

    outputs = {label: prepared for label, prepared in result.runs}
    assert outputs["Run A"].trips["skim_time"].to_list() == [11.0]
    assert outputs["Run B"].trips["skim_time"].to_list() == [101.0]


def test_prepare_workflow_can_skip_skimjoin_for_one_run(
    tmp_path: Path,
) -> None:
    run_a_dir = tmp_path / "run_a"
    run_b_dir = tmp_path / "run_b"
    _write_prepare_run_inputs(run_a_dir)
    _write_prepare_run_inputs(run_b_dir)

    skim_path = tmp_path / "shared.omx"
    _write_omx_with_lookup(
        skim_path,
        matrix_name="SOV_TIME",
        lookup_name="taz",
        values=np.array([[1.0, 12.0], [22.0, 32.0]]),
    )
    _write_skimjoin_config(tmp_path, skim_file=skim_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Mixed Skimjoin Test"',
                "root: summary_cache",
                "dashboard:",
                '  title: "Mixed Skimjoin Test"',
                "zones:",
                "  use_maz: false",
                "runs:",
                f'  - dir: "{run_a_dir.as_posix()}"',
                '    label: "Run A"',
                "    skimjoin:",
                "      enabled: false",
                f'  - dir: "{run_b_dir.as_posix()}"',
                '    label: "Run B"',
                "skimjoin:",
                "  defaults:",
                "    config_path: skimjoin.yaml",
                "pipeline:",
                "  steps: [prepare, skimjoin]",
            ]
        ),
        encoding="utf-8",
    )
    config = Config.from_yaml(config_path)

    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
    )

    outputs = {label: prepared for label, prepared in result.runs}
    assert "skim_time" not in outputs["Run A"].trips.columns
    assert outputs["Run B"].trips["skim_time"].to_list() == [12.0]
    assert result.fingerprints_by_key["run-a"]["skimjoin"] is None
    assert result.fingerprints_by_key["run-b"]["skimjoin"]["enabled"] is True


def test_prepare_workflow_supports_two_runs_sharing_one_skimjoin_config_with_different_skim_files(
    tmp_path: Path,
) -> None:
    run_a_dir = tmp_path / "run_a"
    run_b_dir = tmp_path / "run_b"
    _write_prepare_run_inputs(run_a_dir)
    _write_prepare_run_inputs(run_b_dir)

    skim_a = tmp_path / "shared_a.omx"
    skim_b = tmp_path / "shared_b.omx"
    _write_omx_with_lookup(
        skim_a,
        matrix_name="SOV_TIME",
        lookup_name="taz",
        values=np.array([[1.0, 12.0], [22.0, 32.0]]),
    )
    _write_omx_with_lookup(
        skim_b,
        matrix_name="SOV_TIME",
        lookup_name="taz",
        values=np.array([[1.0, 102.0], [202.0, 302.0]]),
    )
    _write_skimjoin_config(tmp_path, skim_file=skim_a)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Shared Config Different Skims"',
                "root: summary_cache",
                "dashboard:",
                '  title: "Shared Config Different Skims"',
                "zones:",
                "  use_maz: false",
                "runs:",
                f'  - dir: "{run_a_dir.as_posix()}"',
                '    label: "Run A"',
                "    skimjoin:",
                "      skim_files:",
                f'        - "{skim_a.resolve().as_posix()}"',
                f'  - dir: "{run_b_dir.as_posix()}"',
                '    label: "Run B"',
                "    skimjoin:",
                "      skim_files:",
                f'        - "{skim_b.resolve().as_posix()}"',
                "skimjoin:",
                "  defaults:",
                "    config_path: skimjoin.yaml",
                "pipeline:",
                "  steps: [prepare, skimjoin]",
            ]
        ),
        encoding="utf-8",
    )
    config = Config.from_yaml(config_path)

    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
    )

    outputs = {label: prepared for label, prepared in result.runs}
    assert outputs["Run A"].trips["skim_time"].to_list() == [12.0]
    assert outputs["Run B"].trips["skim_time"].to_list() == [102.0]


def test_normalize_config_preserves_trip_lookups_and_adds_tour_lookup_metadata(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path, matrix_name="WTW_ACC__AM")
    config_path = tmp_path / "skimjoin.yaml"
    config_path.write_text(
        "\n".join(
            [
                "project:",
                "  skim_files:",
                f"    - {skim_path.name}",
                "activitysim:",
                "  trip_mode_column: trip_mode",
                "  tour_mode_column: tour_mode",
                "  trip_id_column: trip_id",
                "  tour_id_column: tour_id",
                "  outbound_column: outbound",
                "dimensions:",
                "  PERIOD:",
                "    source_columns:",
                "      trip_source_column: depart",
                "      outbound_tour_source_column: period",
                "      inbound_tour_source_column: period",
                "    values:",
                "      AM: AM",
                "modes:",
                "  WALK_TRANSIT:",
                "    walk_time:",
                "      output: skim_walk_time",
                "      combine: sum",
                "      matrix: WTW_ACC__{PERIOD}",
                "      fallbacks:",
                "        - matrix: WTW_ACC__MD",
            ]
        ),
        encoding="utf-8",
    )

    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None

    assert normalized.lookups == normalized.trip_lookups
    assert [rule.name for rule in normalized.trip_lookups] == [
        "WALK_TRANSIT.walk_time",
        "WALK_TRANSIT.walk_time.fallback_1",
    ]
    assert [rule.lookup_step_index for rule in normalized.trip_lookups] == [0, 1]
    assert [rule.lookup_role for rule in normalized.trip_lookups] == [
        "primary",
        "fallback",
    ]
    assert [rule.combine_method for rule in normalized.trip_lookups] == ["sum", "sum"]
    assert normalized.trip_lookups[0].lookup_chain_id == "WALK_TRANSIT.walk_time"
    assert normalized.trip_lookups[1].lookup_chain_id == "WALK_TRANSIT.walk_time"

    assert [rule.target_table for rule in normalized.tour_lookups] == [
        "tours",
        "tours",
        "tours",
        "tours",
    ]
    assert [rule.direction for rule in normalized.tour_lookups] == [
        "outbound",
        "outbound",
        "inbound",
        "inbound",
    ]
    assert normalized.tour_lookups[0].origin == "origin"
    assert normalized.tour_lookups[0].destination == "destination"
    assert normalized.tour_lookups[2].origin == "origin"
    assert normalized.tour_lookups[2].destination == "destination"
    assert normalized.tour_lookups[0].when["__skimjoin_tour_direction"] == "outbound"
    assert normalized.tour_lookups[2].when["__skimjoin_tour_direction"] == "inbound"
    assert normalized.tour_lookups[0].output == "skim_walk_time_outbound"
    assert normalized.tour_lookups[2].output == "skim_walk_time_inbound"


def test_normalize_config_respects_apply_to_targets(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path, matrix_name="SOV_TIME")
    _write_skimjoin_config(
        tmp_path,
        skim_file=skim_path,
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  SOV:",
            "    trip_only_time:",
            "      apply_to: trips",
            "      matrix: SOV_TIME",
            "    tour_only_time:",
            "      apply_to: tours",
            "      matrix: SOV_TIME",
        ],
    )

    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None

    assert [rule.component for rule in normalized.trip_lookups] == ["trip_only_time"]
    assert [rule.component for rule in normalized.tour_lookups] == [
        "tour_only_time",
        "tour_only_time",
    ]


def test_inventory_supports_csv_keyed_columns(tmp_path: Path) -> None:
    csv_path = tmp_path / "maz_stop_walk.csv"
    _write_csv_skim(csv_path)

    inventory = inventory_skim_files([csv_path])

    assert inventory["matrix_name"].to_list() == [
        "maz_stop_walk__walk_dist_local_bus",
        "maz_stop_walk__walk_dist_premium_transit",
    ]
    assert inventory["source_kind"].unique().to_list() == ["keyed_column"]
    assert inventory["key_column_name"].unique().to_list() == ["maz"]
    assert inventory["value_column_name"].to_list() == [
        "walk_dist_local_bus",
        "walk_dist_premium_transit",
    ]


def test_inventory_supports_csv_od_columns(tmp_path: Path) -> None:
    csv_path = tmp_path / "maz_maz_walk.csv"
    _write_csv_od_skim(csv_path)

    inventory = inventory_skim_files([csv_path])

    assert inventory["matrix_name"].to_list() == [
        "maz_maz_walk__DISTWALK",
        "maz_maz_walk__actual",
    ]
    assert inventory["source_kind"].unique().to_list() == ["od_table"]
    assert inventory["origin_column_name"].unique().to_list() == ["OMAZ"]
    assert inventory["destination_column_name"].unique().to_list() == ["DMAZ"]
    assert inventory["value_column_name"].to_list() == ["DISTWALK", "actual"]


def test_config_accepts_mixed_omx_and_csv_skim_inputs(tmp_path: Path) -> None:
    skim_path = tmp_path / "skims.omx"
    csv_path = tmp_path / "maz_stop_walk.csv"
    _write_omx(skim_path)
    _write_csv_skim(csv_path)
    _write_skimjoin_config(
        tmp_path,
        skim_files=[skim_path, csv_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  WALK_TRANSIT:",
            "    maz_stop_walk:",
            "      lookup: key",
            "      key_column: o_maz",
            "      matrix: maz_stop_walk__walk_dist_local_bus",
        ],
    )

    config = _write_main_config(tmp_path, skimjoin_enabled=True)

    assert config.skimjoin.normalized_config is not None


def test_validate_config_rejects_ambiguous_unqualified_matrix_reference(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "auto.omx"
    csv_path = tmp_path / "auto.csv"
    _write_omx(skim_path, matrix_name="auto__time")
    pl.DataFrame({"id": [101], "time": [1.0]}).write_csv(csv_path)
    _write_prepare_run_inputs(tmp_path / "run", include_o_maz=True)
    _write_skimjoin_config(
        tmp_path,
        skim_files=[skim_path, csv_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  WALK_TRANSIT:",
            "    test_lookup:",
            "      lookup: key",
            "      key_column: o_maz",
            "      matrix: auto__time",
        ],
    )
    config_data = {
        "project": {
            "skim_files": [str(skim_path), str(csv_path)],
            "trips_table": "run/final_trips.parquet",
            "tours_table": "run/final_tours.parquet",
        },
        "activitysim": {
            "trips_table": "run/final_trips.parquet",
            "tours_table": "run/final_tours.parquet",
            "trip_mode_column": "trip_mode",
            "trip_id_column": "trip_id",
            "tour_id_column": "tour_id",
            "outbound_column": "outbound",
        },
        "defaults": {
            "origin": "OTAZ",
            "destination": "DTAZ",
            "output_prefix": "skim_",
        },
        "modes": {
            "WALK_TRANSIT": {
                "test_lookup": {
                    "lookup": "key",
                    "key_column": "o_maz",
                    "matrix": "auto__time",
                }
            }
        },
    }
    inventory = inventory_skim_files([skim_path, csv_path])
    trips = pl.read_parquet(tmp_path / "run" / "final_trips.parquet").with_columns(
        pl.lit("WALK_TRANSIT").alias("trip_mode")
    )
    tours = pl.read_parquet(tmp_path / "run" / "final_tours.parquet").with_columns(
        pl.lit("WALK_TRANSIT").alias("tour_mode"),
        pl.lit(101).alias("o_maz"),
        pl.lit(102).alias("d_maz"),
    )

    with pytest.raises(ConfigValidationError, match="ambiguous matrix reference 'auto__time'"):
        validate_config(config_data, inventory, trips, tours=tours)


def test_qualified_matrix_references_select_duplicate_names_by_file(
    tmp_path: Path,
) -> None:
    commute_path = tmp_path / "bike_commute.omx"
    noncommute_path = tmp_path / "bike_noncommute.omx"
    _write_omx_with_lookup(
        commute_path,
        matrix_name="distance",
        lookup_name="taz",
        values=np.array([[1.0, 2.0], [3.0, 4.0]]),
    )
    _write_omx_with_lookup(
        noncommute_path,
        matrix_name="distance",
        lookup_name="taz",
        values=np.array([[10.0, 20.0], [30.0, 40.0]]),
    )
    _write_skimjoin_config(
        tmp_path,
        skim_files=[commute_path, noncommute_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  BIKE:",
            "    commute_distance:",
            "      output: skim_bike_commute_distance",
            '      matrix: "bike_commute.omx::distance"',
            "    noncommute_distance:",
            "      output: skim_bike_noncommute_distance",
            '      matrix: "bike_noncommute.omx::distance"',
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None
    inventory = inventory_skim_files(normalized.skim_files)
    _validate_runtime_inventory(inventory)

    trips = pl.DataFrame(
        {
            "trip_id": [1],
            "trip_mode": ["BIKE"],
            "OTAZ": [101],
            "DTAZ": [102],
        }
    )
    annotated, lookup_summary, missing = annotate_trips(
        trips,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
    )

    assert annotated["skim_bike_commute_distance"].to_list() == [2.0]
    assert annotated["skim_bike_noncommute_distance"].to_list() == [20.0]
    assert sorted(lookup_summary["matrix_name"].to_list()) == [
        "bike_commute.omx::distance",
        "bike_noncommute.omx::distance",
    ]
    assert missing.is_empty()


def test_annotate_trips_rejects_ambiguous_unqualified_matrix_reference(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "first.omx"
    second_path = tmp_path / "second.omx"
    _write_omx(first_path, matrix_name="distance")
    _write_omx(second_path, matrix_name="distance")
    _write_skimjoin_config(
        tmp_path,
        skim_files=[first_path, second_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  BIKE:",
            "    distance:",
            "      matrix: distance",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None
    inventory = inventory_skim_files(normalized.skim_files)
    trips = pl.DataFrame(
        {
            "trip_id": [1],
            "trip_mode": ["BIKE"],
            "OTAZ": [101],
            "DTAZ": [102],
        }
    )

    with pytest.raises(ValueError, match="Ambiguous matrix reference 'distance'"):
        annotate_trips(
            trips,
            normalized,
            inventory,
            skim_store=OmxSkimStore(),
        )


def test_validate_config_allows_summed_output_overlap_but_rejects_replace_overlap(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx_with_lookup(
        skim_path,
        matrix_name="WTW_ACC",
        lookup_name="taz",
        values=np.array([[1.0, 2.0], [3.0, 4.0]]),
    )
    handle = omx.open_file(str(skim_path), "a")
    handle["WTW_EGR"] = np.array([[10.0, 20.0], [30.0, 40.0]])
    handle.close()

    trips = pl.DataFrame(
        {
            "trip_id": [1],
            "tour_id": [1001],
            "trip_mode": ["WALK_TRANSIT"],
            "OTAZ": [1],
            "DTAZ": [2],
            "outbound": [True],
        }
    )
    tours = pl.DataFrame(
        {
            "tour_id": [1001],
            "tour_mode": ["WALK_TRANSIT"],
            "origin": [1],
            "destination": [2],
            "OTAZ": [1],
            "DTAZ": [2],
        }
    )
    inventory = inventory_skim_files([skim_path])

    summed_config = {
        "project": {"skim_files": [str(skim_path)]},
        "activitysim": {
            "trips_table": "ignored_trips.parquet",
            "tours_table": "ignored_tours.parquet",
            "trip_mode_column": "trip_mode",
            "tour_mode_column": "tour_mode",
            "trip_id_column": "trip_id",
            "tour_id_column": "tour_id",
            "outbound_column": "outbound",
        },
        "defaults": {"origin": "OTAZ", "destination": "DTAZ"},
        "modes": {
            "WALK_TRANSIT": {
                "walk_access": {
                    "output": "skim_walk_time",
                    "combine": "sum",
                    "matrix": "WTW_ACC",
                },
                "walk_egress": {
                    "output": "skim_walk_time",
                    "combine": "sum",
                    "matrix": "WTW_EGR",
                },
            }
        },
    }
    artifacts = validate_config(
        summed_config,
        inventory,
        trips,
        tours=tours,
        strict=True,
    )
    assert [rule.output for rule in artifacts.normalized.lookups] == [
        "skim_walk_time",
        "skim_walk_time",
    ]

    replace_config = {
        **summed_config,
        "modes": {
            "WALK_TRANSIT": {
                "walk_access": {
                    "output": "skim_walk_time",
                    "matrix": "WTW_ACC",
                },
                "walk_egress": {
                    "output": "skim_walk_time",
                    "matrix": "WTW_EGR",
                },
            }
        },
    }
    with pytest.raises(ConfigValidationError, match="Output collision"):
        validate_config(
            replace_config,
            inventory,
            trips,
            tours=tours,
            strict=True,
        )


def test_validate_config_allows_missing_trip_maz_column_when_fallback_is_usable(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    csv_path = tmp_path / "maz_stop_walk.csv"
    _write_omx(skim_path, matrix_name="SOV_TIME")
    _write_csv_skim(csv_path)
    inventory = inventory_skim_files([skim_path, csv_path])
    trips = pl.DataFrame(
        {
            "trip_id": [1],
            "tour_id": [1001],
            "trip_mode": ["SOV"],
            "OTAZ": [1],
            "DTAZ": [2],
            "outbound": [True],
        }
    )
    tours = pl.DataFrame(
        {
            "tour_id": [1001],
            "tour_mode": ["SOV"],
            "origin": [1],
            "destination": [2],
            "OTAZ": [1],
            "DTAZ": [2],
        }
    )
    config_data = {
        "project": {"skim_files": [str(skim_path), str(csv_path)]},
        "activitysim": {
            "trips_table": "ignored_trips.parquet",
            "trip_mode_column": "trip_mode",
            "tour_mode_column": "tour_mode",
            "trip_id_column": "trip_id",
            "tour_id_column": "tour_id",
            "outbound_column": "outbound",
        },
        "defaults": {"origin": "OTAZ", "destination": "DTAZ"},
        "modes": {
            "SOV": {
                "time": {
                    "lookup": "key",
                    "key_column": "o_maz",
                    "matrix": "maz_stop_walk__walk_dist_local_bus",
                    "fallbacks": [{"matrix": "SOV_TIME"}],
                    "apply_to": "trips",
                }
            }
        },
    }

    artifacts = validate_config(
        config_data,
        inventory,
        trips,
        tours=tours,
        strict=True,
    )

    assert artifacts.normalized.failures == []


def test_validate_config_allows_missing_tour_maz_column_when_fallback_is_usable(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    csv_path = tmp_path / "maz_stop_walk.csv"
    _write_omx(skim_path, matrix_name="SOV_TIME")
    _write_csv_skim(csv_path)
    inventory = inventory_skim_files([skim_path, csv_path])
    trips = pl.DataFrame(
        {
            "trip_id": [1],
            "tour_id": [1001],
            "trip_mode": ["SOV"],
            "OTAZ": [1],
            "DTAZ": [2],
            "outbound": [True],
        }
    )
    tours = pl.DataFrame(
        {
            "tour_id": [1001],
            "tour_mode": ["SOV"],
            "origin": [1],
            "destination": [2],
            "OTAZ": [1],
            "DTAZ": [2],
        }
    )
    config_data = {
        "project": {"skim_files": [str(skim_path), str(csv_path)]},
        "activitysim": {
            "trips_table": "ignored_trips.parquet",
            "trip_mode_column": "trip_mode",
            "tour_mode_column": "tour_mode",
            "trip_id_column": "trip_id",
            "tour_id_column": "tour_id",
            "outbound_column": "outbound",
        },
        "defaults": {"origin": "OTAZ", "destination": "DTAZ"},
        "modes": {
            "SOV": {
                "time": {
                    "lookup": "key",
                    "key_column": "origin_parking_zone",
                    "matrix": "maz_stop_walk__walk_dist_local_bus",
                    "fallbacks": [{"matrix": "SOV_TIME"}],
                    "apply_to": "tours",
                }
            }
        },
    }

    artifacts = validate_config(
        config_data,
        inventory,
        trips,
        tours=tours,
        strict=True,
    )

    assert artifacts.normalized.failures == []


def test_validate_config_rejects_tour_lookup_when_no_usable_step_remains(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    csv_path = tmp_path / "maz_stop_walk.csv"
    _write_omx(skim_path, matrix_name="SOV_TIME")
    _write_csv_skim(csv_path)
    inventory = inventory_skim_files([skim_path, csv_path])
    trips = pl.DataFrame(
        {
            "trip_id": [1],
            "tour_id": [1001],
            "trip_mode": ["SOV"],
            "OTAZ": [101],
            "DTAZ": [102],
            "outbound": [True],
        }
    )
    tours = pl.DataFrame(
        {
            "tour_id": [1001],
            "tour_mode": ["SOV"],
            "origin": [101],
            "destination": [102],
        }
    )
    config_data = {
        "project": {"skim_files": [str(skim_path), str(csv_path)]},
        "activitysim": {
            "trips_table": "ignored_trips.parquet",
            "trip_mode_column": "trip_mode",
            "tour_mode_column": "tour_mode",
            "trip_id_column": "trip_id",
            "tour_id_column": "tour_id",
            "outbound_column": "outbound",
        },
        "defaults": {"origin": "OTAZ", "destination": "DTAZ"},
        "modes": {
            "SOV": {
                "time": {
                    "lookup": "key",
                    "key_column": "origin_parking_zone",
                    "matrix": "maz_stop_walk__walk_dist_local_bus",
                    "apply_to": "tours",
                }
            }
        },
    }

    with pytest.raises(
        ConfigValidationError,
        match="no usable tours lookup step remains",
    ):
        validate_config(
            config_data,
            inventory,
            trips,
            tours=tours,
            strict=True,
        )


def test_run_prepare_workflow_applies_mapping_aware_skimjoin(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_prepare_run_inputs(run_dir)
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)
    config = _write_main_config(tmp_path, run_dir=run_dir, skimjoin_enabled=True)

    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=True,
    )

    prepared = result.runs[0][1]
    assert prepared.trips["skim_time"].to_list() == [2.0]
    assert prepared.tours["skim_time_outbound"].to_list() == [2.0]
    assert prepared.tours["skim_time_inbound"].to_list() == [3.0]
    assert prepared.skimjoin_manifest["skimjoin_status"] == "applied"
    manifest = json.loads(
        (prepared_root / "run-a" / "prepared_tables" / "manifest.json").read_text()
    )
    assert manifest["skimjoin_enabled"] is True

    summaries = summary_builder.build_summaries(
        prepared,
        config,
        summary_ids=[
            "skimjoin_trip_component_stats",
            "skimjoin_tour_component_stats",
        ],
    )
    trip_stats = summaries["skimjoin_trip_component_stats"]
    tour_stats = summaries["skimjoin_tour_component_stats"]

    assert trip_stats.to_dicts() == [
        {
            "skim_scenario": "chosen_mode",
            "trip_mode": "All Modes",
            "component": "skim_time",
            "n_total": 1.0,
            "n_valid": 1.0,
            "mean": 2.0,
            "mean_nonzero": 2.0,
            "std": 0.0,
            "min": 2.0,
            "max": 2.0,
            "median": 2.0,
            "mode": 2.0,
            "zero_share": 0.0,
            "missing_share": 0.0,
        },
        {
            "skim_scenario": "chosen_mode",
            "trip_mode": "SOV",
            "component": "skim_time",
            "n_total": 1.0,
            "n_valid": 1.0,
            "mean": 2.0,
            "mean_nonzero": 2.0,
            "std": 0.0,
            "min": 2.0,
            "max": 2.0,
            "median": 2.0,
            "mode": 2.0,
            "zero_share": 0.0,
            "missing_share": 0.0,
        },
    ]
    assert tour_stats.to_dicts() == [
        {
            "skim_scenario": "chosen_mode",
            "tour_mode": "All Modes",
            "component": "skim_time_inbound",
            "n_total": 1.0,
            "n_valid": 1.0,
            "mean": 3.0,
            "mean_nonzero": 3.0,
            "std": 0.0,
            "min": 3.0,
            "max": 3.0,
            "median": 3.0,
            "mode": 3.0,
            "zero_share": 0.0,
            "missing_share": 0.0,
        },
        {
            "skim_scenario": "chosen_mode",
            "tour_mode": "All Modes",
            "component": "skim_time_outbound",
            "n_total": 1.0,
            "n_valid": 1.0,
            "mean": 2.0,
            "mean_nonzero": 2.0,
            "std": 0.0,
            "min": 2.0,
            "max": 2.0,
            "median": 2.0,
            "mode": 2.0,
            "zero_share": 0.0,
            "missing_share": 0.0,
        },
        {
            "skim_scenario": "chosen_mode",
            "tour_mode": "SOV",
            "component": "skim_time_inbound",
            "n_total": 1.0,
            "n_valid": 1.0,
            "mean": 3.0,
            "mean_nonzero": 3.0,
            "std": 0.0,
            "min": 3.0,
            "max": 3.0,
            "median": 3.0,
            "mode": 3.0,
            "zero_share": 0.0,
            "missing_share": 0.0,
        },
        {
            "skim_scenario": "chosen_mode",
            "tour_mode": "SOV",
            "component": "skim_time_outbound",
            "n_total": 1.0,
            "n_valid": 1.0,
            "mean": 2.0,
            "mean_nonzero": 2.0,
            "std": 0.0,
            "min": 2.0,
            "max": 2.0,
            "median": 2.0,
            "mode": 2.0,
            "zero_share": 0.0,
            "missing_share": 0.0,
        },
    ]


def test_run_prepare_workflow_supports_file_specific_zone_lookup_overrides(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_prepare_run_inputs(run_dir)
    auto_path = tmp_path / "auto.omx"
    fare_path = tmp_path / "fares.omx"
    _write_omx(auto_path)
    _write_omx_with_lookup(
        fare_path,
        matrix_name="FARE",
        lookup_name="zone_number",
        values=np.array([[5.0, 7.5], [8.5, 9.0]]),
    )
    _write_skimjoin_config(
        tmp_path,
        skim_files=[auto_path, fare_path],
        include_default_mode=False,
        zone_mapping_extra_lines=[
            "  file_lookup_names:",
            "    fares.omx: zone_number",
        ],
        extra_lines=[
            "modes:",
            "  SOV:",
            "    fare:",
            "      matrix: FARE",
        ],
    )
    config = _write_main_config(tmp_path, run_dir=run_dir, skimjoin_enabled=True)

    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
    )

    prepared = result.runs[0][1]
    assert prepared.skimjoin_manifest["skimjoin_status"] == "applied"
    assert prepared.trips["skim_fare"].to_list() == [7.5]
    assert prepared.tours["skim_fare_outbound"].to_list() == [7.5]
    assert prepared.tours["skim_fare_inbound"].to_list() == [8.5]


def test_apply_skimjoin_skips_missing_prepare_columns_gracefully(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_prepare_run_inputs(run_dir, include_income_segment=False)
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path, matrix_name="SOV_L_TIME")
    _write_skimjoin_config(
        tmp_path,
        skim_file=skim_path,
        include_default_mode=False,
        extra_lines=[
            "dimensions:",
            "  VOT:",
            "    source_columns:",
            "      trip_source_column: income_segment",
            "      outbound_tour_source_column: income_segment",
            "      inbound_tour_source_column: income_segment",
            "    values:",
            "      1: L",
            "modes:",
            "  SOV:",
            "    time:",
            "      matrix: SOV_{VOT}_TIME",
        ],
    )
    config = _write_main_config(tmp_path, run_dir=run_dir, skimjoin_enabled=True)

    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
    )

    prepared = result.runs[0][1]
    skipped = prepared.skimjoin_reports["skipped_rule_report"]
    assert "skim_time" not in prepared.trips.columns
    assert prepared.skimjoin_manifest["skimjoin_status"] == "no_outputs"
    assert skipped["reason"].to_list() == ["missing_trip_column:income_segment"]
    assert skipped["rule_name"].to_list() == ["SOV.time"]


def test_run_prepare_workflow_handles_trips_without_canonical_trip_id(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_prepare_run_inputs(run_dir, trip_id_column_name="linked_trip_id")
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(
        tmp_path,
        skim_file=skim_path,
        trip_id_column="linked_trip_id",
    )
    config = _write_main_config(tmp_path, run_dir=run_dir, skimjoin_enabled=True)

    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
    )

    prepared = result.runs[0][1]
    assert "trip_id" not in prepared.trips.columns
    assert prepared.trips["skim_time"].to_list() == [2.0]
    assert prepared.tours["skim_time_outbound"].to_list() == [2.0]
    assert prepared.tours["skim_time_inbound"].to_list() == [3.0]
    assert prepared.skimjoin_manifest["skimjoin_status"] == "applied"


def test_annotate_trips_supports_keyed_csv_lookup(tmp_path: Path) -> None:
    csv_path = tmp_path / "maz_stop_walk.csv"
    _write_csv_skim(csv_path)
    _write_skimjoin_config(
        tmp_path,
        skim_files=[csv_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  WALK_TRANSIT:",
            "    maz_stop_walk:",
            "      output: skim_transit_maz_stop_walk",
            "      lookup: key",
            "      key_column: o_maz",
            "      matrix: maz_stop_walk__walk_dist_local_bus",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None

    trips = pl.DataFrame(
        {
            "trip_id": [1, 2, 3],
            "trip_mode": ["WALK_TRANSIT", "WALK_TRANSIT", "WALK_TRANSIT"],
            "o_maz": [101, 102, 999],
            "OTAZ": [101, 101, 101],
            "DTAZ": [102, 102, 102],
        }
    )
    inventory = inventory_skim_files(normalized.skim_files)

    annotated, lookup_summary, missing = annotate_trips(
        trips,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
    )

    assert annotated["skim_transit_maz_stop_walk"].to_list() == [0.25, 0.75, None]
    assert lookup_summary["matrix_name"].to_list() == ["maz_stop_walk__walk_dist_local_bus"]
    assert lookup_summary["origin_column"].to_list() == ["o_maz"]
    assert lookup_summary["destination_column"].null_count() == 1
    assert missing["reason"].to_list() == ["missing_od"]
    assert missing["origin"].to_list() == [999]


def test_annotate_trips_uses_fallback_after_missing_keyed_lookup(tmp_path: Path) -> None:
    skim_path = tmp_path / "skims.omx"
    csv_path = tmp_path / "maz_stop_walk.csv"
    _write_omx(skim_path, matrix_name="WALK_FALLBACK")
    _write_csv_skim(
        csv_path,
        rows=[
            {
                "maz": 101,
                "walk_dist_local_bus": 0.25,
                "walk_dist_premium_transit": 0.5,
            }
        ],
    )
    _write_skimjoin_config(
        tmp_path,
        skim_files=[skim_path, csv_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  WALK_TRANSIT:",
            "    maz_stop_walk:",
            "      output: skim_transit_maz_stop_walk",
            "      lookup: key",
            "      key_column: o_maz",
            "      matrix: maz_stop_walk__walk_dist_local_bus",
            "      fallbacks:",
            "        - matrix: WALK_FALLBACK",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None

    trips = pl.DataFrame(
        {
            "trip_id": [1, 2],
            "trip_mode": ["WALK_TRANSIT", "WALK_TRANSIT"],
            "o_maz": [101, 999],
            "OTAZ": [101, 101],
            "DTAZ": [102, 102],
        }
    )
    inventory = inventory_skim_files(normalized.skim_files)

    annotated, lookup_summary, missing = annotate_trips(
        trips,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
    )

    assert annotated["skim_transit_maz_stop_walk"].to_list() == [0.25, 2.0]
    assert lookup_summary.sort("matrix_name")["matrix_name"].to_list() == [
        "WALK_FALLBACK",
        "maz_stop_walk__walk_dist_local_bus",
    ]
    assert lookup_summary.sort("matrix_name")["n_missing"].to_list() == [0, 1]
    assert missing.is_empty()


def test_annotate_trips_uses_fallback_when_primary_key_column_is_missing(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    csv_path = tmp_path / "maz_stop_walk.csv"
    _write_omx(skim_path, matrix_name="WALK_FALLBACK")
    _write_csv_skim(csv_path)
    _write_skimjoin_config(
        tmp_path,
        skim_files=[skim_path, csv_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  WALK_TRANSIT:",
            "    maz_stop_walk:",
            "      output: skim_transit_maz_stop_walk",
            "      lookup: key",
            "      key_column: o_maz",
            "      matrix: maz_stop_walk__walk_dist_local_bus",
            "      fallbacks:",
            "        - matrix: WALK_FALLBACK",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None

    trips = pl.DataFrame(
        {
            "trip_id": [1],
            "trip_mode": ["WALK_TRANSIT"],
            "OTAZ": [101],
            "DTAZ": [102],
        }
    )
    inventory = inventory_skim_files(normalized.skim_files)

    annotated, lookup_summary, missing = annotate_trips(
        trips,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
    )

    assert annotated["skim_transit_maz_stop_walk"].to_list() == [2.0]
    assert lookup_summary["matrix_name"].to_list() == ["WALK_FALLBACK"]
    assert missing.is_empty()


def test_annotate_trips_uses_fallback_after_primary_sentinel_value(tmp_path: Path) -> None:
    skim_path = tmp_path / "skims.omx"
    csv_path = tmp_path / "maz_stop_walk.csv"
    _write_omx(skim_path, matrix_name="WALK_FALLBACK")
    _write_csv_skim(
        csv_path,
        rows=[
            {
                "maz": 101,
                "walk_dist_local_bus": 999999.0,
                "walk_dist_premium_transit": 0.5,
            }
        ],
    )
    _write_skimjoin_config(
        tmp_path,
        skim_files=[skim_path, csv_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  WALK_TRANSIT:",
            "    maz_stop_walk:",
            "      output: skim_transit_maz_stop_walk",
            "      lookup: key",
            "      key_column: o_maz",
            "      matrix: maz_stop_walk__walk_dist_local_bus",
            "      sentinel_values:",
            "        - 999999",
            "      fallbacks:",
            "        - matrix: WALK_FALLBACK",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None

    trips = pl.DataFrame(
        {
            "trip_id": [1],
            "trip_mode": ["WALK_TRANSIT"],
            "o_maz": [101],
            "OTAZ": [101],
            "DTAZ": [102],
        }
    )
    inventory = inventory_skim_files(normalized.skim_files)

    annotated, lookup_summary, missing = annotate_trips(
        trips,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
    )

    assert annotated["skim_transit_maz_stop_walk"].to_list() == [2.0]
    assert lookup_summary.sort("matrix_name")["n_missing"].to_list() == [0, 1]
    assert missing.is_empty()


def test_annotate_trips_can_return_fallback_lookup_report(tmp_path: Path) -> None:
    skim_path = tmp_path / "skims.omx"
    csv_path = tmp_path / "maz_stop_walk.csv"
    _write_omx(skim_path, matrix_name="WALK_FALLBACK")
    _write_csv_skim(
        csv_path,
        rows=[
            {
                "maz": 101,
                "walk_dist_local_bus": 0.25,
                "walk_dist_premium_transit": 0.5,
            }
        ],
    )
    _write_skimjoin_config(
        tmp_path,
        skim_files=[skim_path, csv_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  WALK_TRANSIT:",
            "    maz_stop_walk:",
            "      output: skim_transit_maz_stop_walk",
            "      lookup: key",
            "      key_column: o_maz",
            "      matrix: maz_stop_walk__walk_dist_local_bus",
            "      fallbacks:",
            "        - matrix: WALK_FALLBACK",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None

    trips = pl.DataFrame(
        {
            "trip_id": [1, 2],
            "trip_mode": ["WALK_TRANSIT", "WALK_TRANSIT"],
            "o_maz": [101, 999],
            "OTAZ": [101, 101],
            "DTAZ": [102, 102],
        }
    )
    inventory = inventory_skim_files(normalized.skim_files)

    annotated, lookup_summary, missing, fallback_report = annotate_trips(
        trips,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
        include_fallback_report=True,
    )

    assert annotated["skim_transit_maz_stop_walk"].to_list() == [0.25, 2.0]
    assert lookup_summary.height == 2
    assert missing.is_empty()
    assert fallback_report.to_dicts() == [
        {
            "table_name": "trips",
            "rule_name": "WALK_TRANSIT.maz_stop_walk.fallback_1",
            "output": "skim_transit_maz_stop_walk",
            "logical_id": 2,
            "direction": None,
            "primary_matrix_name": "maz_stop_walk__walk_dist_local_bus",
            "fallback_matrix_name": "WALK_FALLBACK",
            "fallback_step_index": 1,
            "fallback_reason": "missing_od",
            "fallback_eligible": True,
            "fallback_attempted": True,
            "fallback_succeeded": True,
            "fallback_exhausted": False,
        }
    ]

    fast_annotated, fast_lookup_summary, fast_missing = annotate_trips(
        trips,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
        collect_reports=False,
    )
    assert fast_annotated.to_dicts() == annotated.to_dicts()
    assert fast_lookup_summary.is_empty()
    assert fast_missing.is_empty()


def test_annotate_trips_can_skip_discarded_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None
    trips = pl.DataFrame(
        {
            "trip_id": [1],
            "trip_mode": ["SOV"],
            "OTAZ": [101],
            "DTAZ": [102],
        }
    )
    inventory = inventory_skim_files(normalized.skim_files)

    def _unexpected_report(*args, **kwargs):
        raise AssertionError("report builder should not run")

    monkeypatch.setattr(
        "processor.skimjoin.annotate.engine._build_lookup_summary_frame",
        _unexpected_report,
    )
    monkeypatch.setattr(
        "processor.skimjoin.annotate.engine._concat_missing_frames",
        _unexpected_report,
    )
    monkeypatch.setattr(
        "processor.skimjoin.annotate.engine._build_fallback_lookup_report",
        _unexpected_report,
    )

    annotated, lookup_summary, missing = annotate_trips(
        trips,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
        collect_reports=False,
    )

    assert annotated["skim_time"].to_list() == [2.0]
    assert lookup_summary.is_empty()
    assert missing.is_empty()


def test_hypothetical_sidecars_use_mode_specific_long_lookup_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(
        tmp_path,
        skim_file=skim_path,
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  SOV:",
            "    time: SOV_TIME",
            "  WALK:",
            "    time: SOV_TIME",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None
    inventory = inventory_skim_files(normalized.skim_files)
    calls: list[tuple[str, str, set[str]]] = []

    def _lookup_values(frame, _normalized, _inventory, **kwargs):
        mode_column = "trip_mode" if "trip_mode" in frame.columns else "tour_mode"
        table_name = "trips" if mode_column == "trip_mode" else "tours"
        mode = str(frame.item(0, mode_column))
        rules = kwargs["rules"]
        calls.append(
            (
                table_name,
                mode,
                {str(rule.mode) for rule in rules},
            )
        )
        outputs = sorted({str(rule.output) for rule in rules})
        return pl.DataFrame(
            [
                {"_row_id": row_id, "output": output, "value": float(index + 1)}
                for index, output in enumerate(outputs)
                for row_id in range(frame.height)
            ]
        )

    monkeypatch.setattr(
        "processor.skimjoin.hypothetical_sidecars.lookup_trip_output_values",
        _lookup_values,
    )
    monkeypatch.setattr(
        "processor.skimjoin.hypothetical_sidecars.lookup_tour_output_values",
        _lookup_values,
    )

    trip_sidecar, tour_sidecar = build_hypothetical_sidecars(
        trips=pl.DataFrame(
            {
                "trip_id": [1],
                "trip_mode": ["SOV"],
                "finalweight": [2.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [10],
                "tour_mode": ["WALK"],
                "finalweight": [3.0],
            }
        ),
        normalized=normalized,
        inventory=inventory,
    )

    assert not trip_sidecar.is_empty()
    assert not tour_sidecar.is_empty()
    assert calls == [
        ("trips", "SOV", {"SOV"}),
        ("trips", "WALK", {"WALK"}),
        ("tours", "SOV", {"SOV"}),
        ("tours", "WALK", {"WALK"}),
    ]


def test_hypothetical_sidecars_preserve_values_nulls_and_schema(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None

    trip_sidecar, tour_sidecar = build_hypothetical_sidecars(
        trips=pl.DataFrame(
            {
                "trip_id": [1, 2],
                "trip_mode": ["WALK", "SOV"],
                "OTAZ": [101, 999],
                "DTAZ": [102, 102],
                "finalweight": [2.0, 4.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [10],
                "tour_mode": ["WALK"],
                "OTAZ": [101],
                "DTAZ": [102],
                "finalweight": [3.0],
            }
        ),
        normalized=normalized,
        inventory=inventory_skim_files(normalized.skim_files),
        skim_store=OmxSkimStore(),
    )

    assert trip_sidecar.schema == TRIP_HYPOTHETICAL_SIDECAR_SCHEMA
    assert trip_sidecar.sort("trip_id").to_dicts() == [
        {
            "trip_id": 1,
            "observed_mode": "WALK",
            "hypothetical_mode": "SOV",
            "component": "skim_time",
            "value": 2.0,
            "finalweight": 2.0,
        },
        {
            "trip_id": 2,
            "observed_mode": "SOV",
            "hypothetical_mode": "SOV",
            "component": "skim_time",
            "value": None,
            "finalweight": 4.0,
        },
    ]
    assert tour_sidecar.schema == TOUR_HYPOTHETICAL_SIDECAR_SCHEMA
    assert tour_sidecar.sort("component").to_dicts() == [
        {
            "tour_id": 10,
            "observed_mode": "WALK",
            "hypothetical_mode": "SOV",
            "direction": "inbound",
            "component": "skim_time_inbound",
            "value": 3.0,
            "finalweight": 3.0,
        },
        {
            "tour_id": 10,
            "observed_mode": "WALK",
            "hypothetical_mode": "SOV",
            "direction": "outbound",
            "component": "skim_time_outbound",
            "value": 2.0,
            "finalweight": 3.0,
        },
    ]


def test_hypothetical_sidecars_filter_csv_cache_to_required_od_pairs(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "maz_maz_walk.csv"
    _write_csv_od_skim(
        csv_path,
        rows=[
            {"OMAZ": 101, "DMAZ": 102, "DISTWALK": 0.5, "actual": 10.0},
            {"OMAZ": 101, "DMAZ": 102, "DISTWALK": 0.6, "actual": 11.0},
            {"OMAZ": 102, "DMAZ": 101, "DISTWALK": 0.75, "actual": 15.0},
            {"OMAZ": 999, "DMAZ": 999, "DISTWALK": 9.0, "actual": 99.0},
        ],
    )
    _write_skimjoin_config(
        tmp_path,
        skim_files=[csv_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  WALK:",
            "    distance:",
            "      output: skim_walk_distance",
            "      origin: o_maz",
            "      destination: d_maz",
            "      matrix: maz_maz_walk__DISTWALK",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None
    inventory = inventory_skim_files(normalized.skim_files)
    skim_store = OmxSkimStore()

    trip_sidecar, tour_sidecar = build_hypothetical_sidecars(
        trips=pl.DataFrame(
            {
                "trip_id": [1],
                "trip_mode": ["SOV"],
                "o_maz": [101],
                "d_maz": [102],
                "OTAZ": [101],
                "DTAZ": [102],
                "finalweight": [2.0],
            }
        ),
        tours=pl.DataFrame(
            {
                "tour_id": [10],
                "tour_mode": ["SOV"],
                "o_maz": [101],
                "d_maz": [102],
                "OTAZ": [101],
                "DTAZ": [102],
                "finalweight": [3.0],
            }
        ),
        normalized=normalized,
        inventory=inventory,
        skim_store=skim_store,
    )

    assert trip_sidecar["value"].to_list() == [0.6]
    assert tour_sidecar.sort("direction")["value"].to_list() == [0.75, 0.6]
    cached = next(iter(skim_store._od_csv_cache.values()))
    assert cached.height == 2
    assert cached.select("__lookup_origin", "__lookup_destination").sort(
        "__lookup_origin"
    ).rows() == [(101.0, 102.0), (102.0, 101.0)]


def test_annotate_trips_primary_lookup_success_does_not_emit_fallback_report(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    csv_path = tmp_path / "maz_stop_walk.csv"
    _write_omx(skim_path, matrix_name="WALK_FALLBACK")
    _write_csv_skim(csv_path)
    _write_skimjoin_config(
        tmp_path,
        skim_files=[skim_path, csv_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  WALK_TRANSIT:",
            "    maz_stop_walk:",
            "      output: skim_transit_maz_stop_walk",
            "      lookup: key",
            "      key_column: o_maz",
            "      matrix: maz_stop_walk__walk_dist_local_bus",
            "      fallbacks:",
            "        - matrix: WALK_FALLBACK",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None

    trips = pl.DataFrame(
        {
            "trip_id": [1],
            "trip_mode": ["WALK_TRANSIT"],
            "o_maz": [101],
            "OTAZ": [101],
            "DTAZ": [102],
        }
    )
    inventory = inventory_skim_files(normalized.skim_files)

    annotated, lookup_summary, missing, fallback_report = annotate_trips(
        trips,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
        include_fallback_report=True,
    )

    assert annotated["skim_transit_maz_stop_walk"].to_list() == [0.25]
    assert lookup_summary.height == 1
    assert missing.is_empty()
    assert fallback_report.is_empty()


def test_annotate_trips_reports_missing_when_primary_and_fallback_both_fail(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    csv_path = tmp_path / "maz_stop_walk.csv"
    _write_omx(skim_path, matrix_name="WALK_FALLBACK")
    _write_csv_skim(
        csv_path,
        rows=[
            {
                "maz": 101,
                "walk_dist_local_bus": 0.25,
                "walk_dist_premium_transit": 0.5,
            }
        ],
    )
    _write_skimjoin_config(
        tmp_path,
        skim_files=[skim_path, csv_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  WALK_TRANSIT:",
            "    maz_stop_walk:",
            "      output: skim_transit_maz_stop_walk",
            "      lookup: key",
            "      key_column: o_maz",
            "      matrix: maz_stop_walk__walk_dist_local_bus",
            "      fallbacks:",
            "        - matrix: WALK_FALLBACK",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None

    trips = pl.DataFrame(
        {
            "trip_id": [1],
            "trip_mode": ["WALK_TRANSIT"],
            "o_maz": [999],
            "OTAZ": [999],
            "DTAZ": [999],
        }
    )
    inventory = inventory_skim_files(normalized.skim_files)

    annotated, lookup_summary, missing, fallback_report = annotate_trips(
        trips,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
        include_fallback_report=True,
    )

    assert "skim_transit_maz_stop_walk" not in annotated.columns
    assert lookup_summary.sort("matrix_name")["n_missing"].to_list() == [1, 1]
    assert missing.to_dicts() == [
        {
            "rule_name": "WALK_TRANSIT.maz_stop_walk.fallback_1",
            "trip_id": 1,
            "origin": 999,
            "destination": 999,
            "matrix_name": "WALK_FALLBACK",
            "reason": "missing_od",
        }
    ]
    assert fallback_report.to_dicts() == [
        {
            "table_name": "trips",
            "rule_name": "WALK_TRANSIT.maz_stop_walk.fallback_1",
            "output": "skim_transit_maz_stop_walk",
            "logical_id": 1,
            "direction": None,
            "primary_matrix_name": "maz_stop_walk__walk_dist_local_bus",
            "fallback_matrix_name": "WALK_FALLBACK",
            "fallback_step_index": 1,
            "fallback_reason": "missing_od",
            "fallback_eligible": True,
            "fallback_attempted": True,
            "fallback_succeeded": False,
            "fallback_exhausted": True,
        }
    ]


def test_annotate_trips_supports_csv_od_lookup(tmp_path: Path) -> None:
    csv_path = tmp_path / "maz_maz_walk.csv"
    _write_csv_od_skim(csv_path)
    _write_skimjoin_config(
        tmp_path,
        skim_files=[csv_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  WALK:",
            "    maz_walk_distance:",
            "      output: skim_walk_maz_distance",
            "      origin: o_maz",
            "      destination: d_maz",
            "      matrix: maz_maz_walk__DISTWALK",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None

    trips = pl.DataFrame(
        {
            "trip_id": [1, 2, 3],
            "trip_mode": ["WALK", "WALK", "WALK"],
            "o_maz": [101, 102, 999],
            "d_maz": [102, 101, 101],
            "OTAZ": [101, 102, 999],
            "DTAZ": [102, 101, 101],
        }
    )
    inventory = inventory_skim_files(normalized.skim_files)

    annotated, lookup_summary, missing = annotate_trips(
        trips,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
    )

    assert annotated["skim_walk_maz_distance"].to_list() == [0.5, 0.75, None]
    assert lookup_summary["matrix_name"].to_list() == ["maz_maz_walk__DISTWALK"]
    assert lookup_summary["origin_column"].to_list() == ["o_maz"]
    assert lookup_summary["destination_column"].to_list() == ["d_maz"]
    assert missing["reason"].to_list() == ["missing_od"]
    assert missing["origin"].to_list() == [999]
    assert missing["destination"].to_list() == [101]


def test_annotate_trips_scans_each_multi_value_csv_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keyed_path = tmp_path / "maz_stop_walk.csv"
    _write_csv_skim(
        keyed_path,
        rows=[
            {
                "maz": 101,
                "walk_dist_local_bus": 0.25,
                "walk_dist_premium_transit": None,
                "unused": 100.0,
            },
            {
                "maz": 101,
                "walk_dist_local_bus": None,
                "walk_dist_premium_transit": 0.6,
                "unused": 200.0,
            },
        ],
    )
    od_path = tmp_path / "maz_maz_walk.csv"
    _write_csv_od_skim(
        od_path,
        rows=[
            {
                "OMAZ": 101,
                "DMAZ": 102,
                "DISTWALK": 0.5,
                "actual": None,
                "unused": 100.0,
            },
            {
                "OMAZ": 101,
                "DMAZ": 102,
                "DISTWALK": None,
                "actual": 10.0,
                "unused": 200.0,
            },
        ],
    )
    _write_skimjoin_config(
        tmp_path,
        skim_files=[keyed_path, od_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  WALK:",
            "    local_stop:",
            "      output: skim_local_stop",
            "      lookup: key",
            "      key_column: o_maz",
            "      matrix: maz_stop_walk__walk_dist_local_bus",
            "    premium_stop:",
            "      output: skim_premium_stop",
            "      lookup: key",
            "      key_column: o_maz",
            "      matrix: maz_stop_walk__walk_dist_premium_transit",
            "    walk_distance:",
            "      output: skim_walk_distance",
            "      origin: o_maz",
            "      destination: d_maz",
            "      matrix: maz_maz_walk__DISTWALK",
            "    walk_actual:",
            "      output: skim_walk_actual",
            "      origin: o_maz",
            "      destination: d_maz",
            "      matrix: maz_maz_walk__actual",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None
    inventory = inventory_skim_files(normalized.skim_files)

    scan_calls: list[Path] = []
    original_scan_csv = pl.scan_csv

    def tracked_scan_csv(source, *args, **kwargs):
        scan_calls.append(Path(source))
        return original_scan_csv(source, *args, **kwargs)

    monkeypatch.setattr(pl, "scan_csv", tracked_scan_csv)
    skim_store = OmxSkimStore()
    annotated, _, missing = annotate_trips(
        pl.DataFrame(
            {
                "trip_id": [1],
                "trip_mode": ["WALK"],
                "o_maz": [101],
                "d_maz": [102],
                "OTAZ": [101],
                "DTAZ": [102],
            }
        ),
        normalized,
        inventory,
        skim_store=skim_store,
    )

    assert annotated.select(
        "skim_local_stop",
        "skim_premium_stop",
        "skim_walk_distance",
        "skim_walk_actual",
    ).row(0) == (0.25, 0.6, 0.5, 10.0)
    assert missing.is_empty()
    assert scan_calls.count(keyed_path) == 1
    assert scan_calls.count(od_path) == 1
    assert "unused" not in next(iter(skim_store._keyed_csv_cache.values())).columns
    assert "unused" not in next(iter(skim_store._od_csv_cache.values())).columns


def test_annotate_trips_resolves_placeholders_into_multiple_matrix_groups(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    handle = omx.open_file(str(skim_path), "w")
    handle["SOV_L_TIME"] = np.array([[1.0, 2.0], [3.0, 4.0]])
    handle["SOV_H_TIME"] = np.array([[10.0, 20.0], [30.0, 40.0]])
    handle.create_mapping("taz", np.array([101, 102], dtype=np.uint32))
    handle.close()

    _write_skimjoin_config(
        tmp_path,
        skim_file=skim_path,
        include_default_mode=False,
        extra_lines=[
            "dimensions:",
            "  VOT:",
            "    source_columns:",
            "      trip_source_column: income_segment",
            "      outbound_tour_source_column: income_segment",
            "      inbound_tour_source_column: income_segment",
            "    values:",
            "      1: L",
            "      2: H",
            "modes:",
            "  SOV:",
            "    time:",
            "      matrix: SOV_{VOT}_TIME",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None

    trips = pl.DataFrame(
        {
            "trip_id": [1, 2, 3],
            "trip_mode": ["SOV", "SOV", "SOV"],
            "OTAZ": [101, 101, 101],
            "DTAZ": [102, 102, 102],
            "income_segment": [1, 2, 999],
        }
    )
    inventory = inventory_skim_files(normalized.skim_files)

    annotated, lookup_summary, missing = annotate_trips(
        trips,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
    )

    assert annotated["skim_time"].to_list() == [2.0, 20.0, None]
    assert lookup_summary.sort("matrix_name")["matrix_name"].to_list() == [
        "SOV_H_TIME",
        "SOV_L_TIME",
    ]
    assert lookup_summary.sort("matrix_name")["n_trips"].to_list() == [1, 1]
    assert missing["reason"].to_list() == ["missing_dimension_value:VOT"]
    assert missing["trip_id"].to_list() == [3]


def test_annotate_trips_supports_multiple_outputs_in_one_pass(tmp_path: Path) -> None:
    skim_path = tmp_path / "skims.omx"
    csv_path = tmp_path / "maz_stop_walk.csv"
    _write_omx(skim_path, matrix_name="SOV_TIME")
    _write_csv_skim(csv_path)
    _write_skimjoin_config(
        tmp_path,
        skim_files=[skim_path, csv_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  SOV:",
            "    time:",
            "      output: skim_time",
            "      matrix: SOV_TIME",
            "  WALK_TRANSIT:",
            "    maz_stop_walk:",
            "      output: skim_transit_maz_stop_walk",
            "      lookup: key",
            "      key_column: o_maz",
            "      matrix: maz_stop_walk__walk_dist_local_bus",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None

    trips = pl.DataFrame(
        {
            "trip_id": [1, 2, 3],
            "trip_mode": ["SOV", "WALK_TRANSIT", "WALK_TRANSIT"],
            "OTAZ": [101, 101, 101],
            "DTAZ": [102, 102, 102],
            "o_maz": [101, 101, 999],
        }
    )
    inventory = inventory_skim_files(normalized.skim_files)

    annotated, lookup_summary, missing = annotate_trips(
        trips,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
    )

    assert annotated["skim_time"].to_list() == [2.0, None, None]
    assert annotated["skim_transit_maz_stop_walk"].to_list() == [None, 0.25, None]
    assert lookup_summary.sort("output")["output"].to_list() == [
        "skim_time",
        "skim_transit_maz_stop_walk",
    ]
    assert missing["reason"].to_list() == ["missing_od"]
    assert missing["trip_id"].to_list() == [3]


def test_annotate_trips_sums_multiple_rules_into_one_output(tmp_path: Path) -> None:
    skim_path = tmp_path / "skims.omx"
    handle = omx.open_file(str(skim_path), "w")
    handle["WTW_ACC"] = np.array([[1.0, 2.0], [3.0, 4.0]])
    handle["WTW_EGR"] = np.array([[10.0, 20.0], [30.0, 40.0]])
    handle.create_mapping("taz", np.array([101, 102], dtype=np.uint32))
    handle.close()

    _write_skimjoin_config(
        tmp_path,
        skim_file=skim_path,
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  WALK_TRANSIT:",
            "    walk_access:",
            "      output: skim_walk_time",
            "      combine: sum",
            "      matrix: WTW_ACC",
            "    walk_egress:",
            "      output: skim_walk_time",
            "      combine: sum",
            "      matrix: WTW_EGR",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None

    trips = pl.DataFrame(
        {
            "trip_id": [1, 2],
            "trip_mode": ["WALK_TRANSIT", "WALK_TRANSIT"],
            "OTAZ": [101, 102],
            "DTAZ": [102, 101],
        }
    )
    inventory = inventory_skim_files(normalized.skim_files)

    annotated, lookup_summary, missing = annotate_trips(
        trips,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
    )

    assert annotated["skim_walk_time"].to_list() == [22.0, 33.0]
    assert lookup_summary.sort("matrix_name")["matrix_name"].to_list() == [
        "WTW_ACC",
        "WTW_EGR",
    ]
    assert missing.is_empty()


def test_annotate_tours_produces_directional_outputs_and_reuses_segmentation(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    handle = omx.open_file(str(skim_path), "w")
    handle["OUTBOUND_TIME"] = np.array([[1.0, 2.0], [3.0, 4.0]])
    handle["INBOUND_TIME"] = np.array([[10.0, 20.0], [30.0, 40.0]])
    handle.create_mapping("taz", np.array([101, 102], dtype=np.uint32))
    handle.close()

    config_path = tmp_path / "skimjoin.yaml"
    config_path.write_text(
        "\n".join(
            [
                "project:",
                "  skim_files:",
                f"    - {skim_path.name}",
                "activitysim:",
                "  trip_mode_column: trip_mode",
                "  tour_mode_column: tour_mode",
                "  trip_id_column: trip_id",
                "  tour_id_column: tour_id",
                "  outbound_column: outbound",
                "defaults:",
                "  origin: OTAZ",
                "  destination: DTAZ",
                "zone_mapping:",
                "  lookup_name: taz",
                "modes:",
                "  TEST_TRANSIT:",
                "    segment_on: outbound",
                "    segments:",
                "      true:",
                "        time:",
                "          matrix: OUTBOUND_TIME",
                "      false:",
                "        time:",
                "          matrix: INBOUND_TIME",
            ]
        ),
        encoding="utf-8",
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None
    inventory = inventory_skim_files(normalized.skim_files)

    tours = pl.DataFrame(
        {
            "tour_id": [1],
            "tour_mode": ["TEST_TRANSIT"],
            "origin": [101],
            "destination": [102],
            "OTAZ": [101],
            "DTAZ": [102],
        }
    )

    annotated, lookup_summary, missing = annotate_tours(
        tours,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
    )

    assert annotated["skim_time_outbound"].to_list() == [2.0]
    assert annotated["skim_time_inbound"].to_list() == [30.0]
    assert lookup_summary.sort("output")["output"].to_list() == [
        "skim_time_inbound",
        "skim_time_outbound",
    ]
    assert missing.is_empty()

    fast_annotated, fast_lookup_summary, fast_missing = annotate_tours(
        tours,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
        collect_reports=False,
    )
    assert fast_annotated.to_dicts() == annotated.to_dicts()
    assert fast_lookup_summary.is_empty()
    assert fast_missing.is_empty()


def test_annotate_tours_runs_without_any_trip_inputs_or_trip_skim_columns(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    handle = omx.open_file(str(skim_path), "w")
    handle["SOV_TIME"] = np.array([[1.0, 2.0], [3.0, 4.0]])
    handle.create_mapping("taz", np.array([101, 102], dtype=np.uint32))
    handle.close()

    config_path = tmp_path / "skimjoin.yaml"
    config_path.write_text(
        "\n".join(
            [
                "project:",
                "  skim_files:",
                f"    - {skim_path.name}",
                "activitysim:",
                "  trip_mode_column: trip_mode",
                "  tour_mode_column: tour_mode",
                "  trip_id_column: trip_id",
                "  tour_id_column: tour_id",
                "  outbound_column: outbound",
                "defaults:",
                "  origin: OTAZ",
                "  destination: DTAZ",
                "zone_mapping:",
                "  lookup_name: taz",
                "modes:",
                "  SOV:",
                "    time:",
                "      matrix: SOV_TIME",
                "      apply_to: tours",
            ]
        ),
        encoding="utf-8",
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None
    inventory = inventory_skim_files(normalized.skim_files)

    tours = pl.DataFrame(
        {
            "tour_id": [1],
            "tour_mode": ["SOV"],
            "origin": [101],
            "destination": [102],
            "OTAZ": [101],
            "DTAZ": [102],
        }
    )

    annotated, lookup_summary, missing = annotate_tours(
        tours,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
    )

    assert annotated["skim_time_outbound"].to_list() == [2.0]
    assert annotated["skim_time_inbound"].to_list() == [3.0]
    assert lookup_summary.sort("output")["output"].to_list() == [
        "skim_time_inbound",
        "skim_time_outbound",
    ]
    assert missing.is_empty()


def test_run_prepare_workflow_supports_keyed_csv_skims_in_integrated_runtime(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_prepare_run_inputs(run_dir, include_o_maz=True)
    skim_path = tmp_path / "skims.omx"
    csv_path = tmp_path / "maz_stop_walk.csv"
    _write_omx(skim_path)
    _write_csv_skim(csv_path)
    _write_skimjoin_config(
        tmp_path,
        skim_files=[skim_path, csv_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  SOV:",
            "    time:",
            "      matrix: SOV_TIME",
            "    maz_stop_walk:",
            "      output: skim_transit_maz_stop_walk",
            "      lookup: key",
            "      key_column: o_maz",
            "      matrix: maz_stop_walk__walk_dist_local_bus",
        ],
    )

    config = _write_main_config(tmp_path, run_dir=run_dir, skimjoin_enabled=True, use_maz=True)

    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
    )

    prepared = result.runs[0][1]
    assert prepared.skimjoin_manifest["skimjoin_status"] == "applied"
    assert prepared.trips["skim_transit_maz_stop_walk"].to_list() == [0.25]
    assert prepared.tours["skim_transit_maz_stop_walk_outbound"].to_list() == [0.25]
    assert prepared.tours["skim_transit_maz_stop_walk_inbound"].to_list() == [0.75]


def test_run_prepare_workflow_records_fallback_manifest_and_report(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_prepare_run_inputs(run_dir)
    skim_path = tmp_path / "skims.omx"
    csv_path = tmp_path / "maz_stop_walk.csv"
    _write_omx(skim_path, matrix_name="SOV_TIME")
    _write_csv_skim(csv_path)
    _write_skimjoin_config(
        tmp_path,
        skim_files=[skim_path, csv_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  SOV:",
            "    time:",
            "      apply_to: trips",
            "      output: skim_time",
            "      lookup: key",
            "      key_column: o_maz",
            "      matrix: maz_stop_walk__walk_dist_local_bus",
            "      fallbacks:",
            "        - matrix: SOV_TIME",
        ],
    )

    config = _write_main_config(tmp_path, run_dir=run_dir, skimjoin_enabled=True)
    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=True,
    )

    prepared = result.runs[0][1]
    assert prepared.trips["skim_time"].to_list() == [2.0]
    assert prepared.skimjoin_manifest["skimjoin_fallback_count"] == 1
    assert prepared.skimjoin_manifest["skimjoin_fallback_outputs"] == ["skim_time"]
    assert prepared.skimjoin_reports["fallback_lookup_report"].to_dicts() == [
        {
            "table_name": "trips",
            "rule_name": "SOV.time.fallback_1",
            "output": "skim_time",
            "logical_id": 5001,
            "direction": None,
            "primary_matrix_name": None,
            "fallback_matrix_name": "SOV_TIME",
            "fallback_step_index": 1,
            "fallback_reason": "missing_trip_column:o_maz",
            "fallback_eligible": True,
            "fallback_attempted": True,
            "fallback_succeeded": True,
            "fallback_exhausted": False,
        }
    ]
    assert (
        prepared_root
        / "run-a"
        / "prepared_tables"
        / "skimjoin"
        / "fallback_lookup_report.csv"
    ).exists()


def test_run_prepare_workflow_supports_csv_od_skims_in_integrated_runtime(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _write_prepare_run_inputs(run_dir, include_o_maz=True)
    trips_path = run_dir / "final_trips.parquet"
    trips = pl.read_parquet(trips_path).with_columns(
        pl.lit("WALK").alias("trip_mode"),
        pl.lit(102).alias("d_maz"),
    )
    trips.write_parquet(trips_path)
    tours_path = run_dir / "final_tours.parquet"
    tours = pl.read_parquet(tours_path).with_columns(pl.lit("WALK").alias("tour_mode"))
    tours.write_parquet(tours_path)

    csv_path = tmp_path / "maz_maz_walk.csv"
    _write_csv_od_skim(csv_path)
    _write_skimjoin_config(
        tmp_path,
        skim_files=[csv_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  WALK:",
            "    maz_walk_distance:",
            "      output: skim_walk_maz_distance",
            "      origin: o_maz",
            "      destination: d_maz",
            "      matrix: maz_maz_walk__DISTWALK",
        ],
    )

    config = _write_main_config(tmp_path, run_dir=run_dir, skimjoin_enabled=True, use_maz=True)

    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
    )

    prepared = result.runs[0][1]
    assert prepared.skimjoin_manifest["skimjoin_status"] == "applied"
    assert prepared.trips["skim_walk_maz_distance"].to_list() == [0.5]
    assert prepared.tours["skim_walk_maz_distance_outbound"].to_list() == [0.5]
    assert prepared.tours["skim_walk_maz_distance_inbound"].to_list() == [0.75]


def test_annotate_trips_nullifies_configured_omx_sentinel_values(tmp_path: Path) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx_with_lookup(
        skim_path,
        matrix_name="SOV_TIME",
        lookup_name="taz",
        values=np.array([[1.0, 9999.0], [3.0, 4.0]]),
    )
    _write_skimjoin_config(
        tmp_path,
        skim_file=skim_path,
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  SOV:",
            "    time:",
            "      matrix: SOV_TIME",
            "      sentinel_values:",
            "        - 9999",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None
    trips = pl.DataFrame(
        {
            "trip_id": [1, 2],
            "trip_mode": ["SOV", "SOV"],
            "OTAZ": [101, 102],
            "DTAZ": [102, 102],
        }
    )
    inventory = inventory_skim_files(normalized.skim_files)

    annotated, lookup_summary, missing = annotate_trips(
        trips,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
    )

    assert annotated["skim_time"].to_list() == [None, 4.0]
    assert lookup_summary["n_missing"].to_list() == [1]
    assert missing["reason"].to_list() == ["sentinel_value"]


def test_annotate_trips_nullifies_configured_keyed_csv_sentinel_values(tmp_path: Path) -> None:
    csv_path = tmp_path / "maz_stop_walk.csv"
    _write_csv_skim(
        csv_path,
        rows=[
            {"maz": 101, "walk_dist_local_bus": 999999.0, "walk_dist_premium_transit": 0.5},
            {"maz": 102, "walk_dist_local_bus": 0.75, "walk_dist_premium_transit": 1.0},
        ],
    )
    _write_skimjoin_config(
        tmp_path,
        skim_files=[csv_path],
        include_default_mode=False,
        extra_lines=[
            "modes:",
            "  WALK_TRANSIT:",
            "    maz_stop_walk:",
            "      output: skim_transit_maz_stop_walk",
            "      lookup: key",
            "      key_column: o_maz",
            "      matrix: maz_stop_walk__walk_dist_local_bus",
            "      sentinel_values:",
            "        - 999999",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None
    trips = pl.DataFrame(
        {
            "trip_id": [1, 2],
            "trip_mode": ["WALK_TRANSIT", "WALK_TRANSIT"],
            "o_maz": [101, 102],
            "OTAZ": [101, 102],
            "DTAZ": [102, 101],
        }
    )
    inventory = inventory_skim_files(normalized.skim_files)

    annotated, lookup_summary, missing = annotate_trips(trips, normalized, inventory)

    assert annotated["skim_transit_maz_stop_walk"].to_list() == [None, 0.75]
    assert lookup_summary["n_missing"].to_list() == [1]
    assert missing["reason"].to_list() == ["sentinel_value"]


def test_annotate_trips_uses_prepared_trip_period_dimension(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path, matrix_name="SOV_TIME__EA")
    handle = omx.open_file(str(skim_path), "a")
    handle["SOV_TIME__AM"] = np.array([[5.0, 6.0], [7.0, 8.0]])
    handle.close()
    (tmp_path / "skimjoin.yaml").write_text(
        "\n".join(
            [
                "project:",
                "  skim_files:",
                f"    - {skim_path.name}",
                "activitysim:",
                "  trip_mode_column: trip_mode",
                "  trip_id_column: trip_id",
                "  tour_id_column: tour_id",
                "  outbound_column: outbound",
                "defaults:",
                "  origin: OTAZ",
                "  destination: DTAZ",
                "zone_mapping:",
                "  lookup_name: taz",
                "dimensions:",
                "  PERIOD:",
                "    source_columns:",
                "      trip_source_column: trip_period",
                "      outbound_tour_source_column: start_period",
                "      inbound_tour_source_column: first_inbound_trip_period",
                "modes:",
                "  SOV:",
                "    time: SOV_TIME__{PERIOD}",
            ]
        ),
        encoding="utf-8",
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None
    trips = pl.DataFrame(
        {
            "trip_id": [1, 2],
            "trip_mode": ["SOV", "SOV"],
            "OTAZ": [101, 101],
            "DTAZ": [102, 102],
            "trip_period": ["EA", "AM"],
        }
    )
    inventory = inventory_skim_files(normalized.skim_files)

    annotated, lookup_summary, missing = annotate_trips(
        trips,
        normalized,
        inventory,
        skim_store=OmxSkimStore(),
    )

    assert annotated["trip_period"].to_list() == ["EA", "AM"]
    assert annotated["skim_time"].to_list() == [2.0, 6.0]
    assert lookup_summary.height == 2
    assert missing.is_empty()


def test_annotate_trips_handles_late_matrix_names_in_missing_report_without_schema_failure(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path, matrix_name="OTHER_MATRIX")
    _write_skimjoin_config(
        tmp_path,
        skim_file=skim_path,
        include_default_mode=False,
        extra_lines=[
            "dimensions:",
            "  TOD:",
            "    source_columns:",
            "      trip_source_column: time_period",
            "      outbound_tour_source_column: time_period",
            "      inbound_tour_source_column: time_period",
            "    values:",
            "      1: MD",
            "modes:",
            "  SOV:",
            "    time:",
            "      matrix: SOV_L_TIME__{TOD}",
        ],
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None

    trips = pl.DataFrame(
        {
            "trip_id": list(range(1, 123)),
            "trip_mode": ["SOV"] * 122,
            "OTAZ": [101] * 122,
            "DTAZ": [102] * 122,
            "time_period": [None] * 121 + [1],
        }
    )
    inventory = inventory_skim_files(normalized.skim_files)

    annotated, lookup_summary, missing = annotate_trips(trips, normalized, inventory)

    assert annotated.height == 122
    assert lookup_summary.is_empty()
    assert missing.height == 122
    assert missing.schema["matrix_name"] == pl.String
    assert missing.filter(pl.col("reason") == "missing_matrix")["matrix_name"].to_list() == [
        "SOV_L_TIME__MD"
    ]
    assert (
        missing.filter(
            pl.col("reason") == "missing_dimension_value:TOD"
        )["matrix_name"].null_count()
        == 121
    )


def test_apply_skimjoin_records_failure_and_keeps_base_tables_when_annotation_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    prepared = _skimjoin_ready_run_data()
    original_trips = prepared.trips.clone()
    original_tours = prepared.tours.clone()

    def _boom(*args, **kwargs):
        raise ValueError("annotation exploded")

    monkeypatch.setattr("processor.skimjoin.pipeline.annotate_trips", _boom)

    result = apply_skimjoin(prepared, config)

    assert result.trips.to_dicts() == original_trips.to_dicts()
    assert result.tours.to_dicts() == original_tours.to_dicts()
    assert result.skimjoin_manifest["skimjoin_status"] == "failed"
    assert "annotation exploded" in str(result.skimjoin_manifest["skimjoin_failure_detail"])
    assert result.skimjoin_manifest["skimjoin_applied_outputs"] == []
    assert result.skimjoin_manifest["skimjoin_skipped_rules"] == []
    assert result.skimjoin_manifest["skimjoin_warning_count"] == 0
    assert result.skimjoin_manifest["skimjoin_fallback_count"] == 0
    assert result.skimjoin_manifest["skimjoin_fallback_outputs"] == []
    assert set(result.skimjoin_reports) == {
        "fallback_lookup_report",
        "skim_lookup_summary",
        "missing_lookup_report",
        "skipped_rule_report",
        "tour_aggregation_summary",
        "failure_report",
    }
    assert result.skimjoin_reports["fallback_lookup_report"].is_empty()
    assert result.skimjoin_reports["skim_lookup_summary"].is_empty()
    assert result.skimjoin_reports["missing_lookup_report"].is_empty()
    assert result.skimjoin_reports["skipped_rule_report"].is_empty()
    assert result.skimjoin_reports["tour_aggregation_summary"].is_empty()
    assert result.skimjoin_reports["failure_report"]["stage"].to_list() == [
        "integrated_skimjoin"
    ]


def test_apply_skimjoin_can_fail_fast_when_annotation_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "pipeline:",
                "  steps: [prepare, skimjoin]",
                "skimjoin:",
                "  failure_policy: error",
                "  defaults:",
                "    config_path: skimjoin.yaml",
            ]
        ),
        encoding="utf-8",
    )
    config = Config.from_yaml(config_path)

    def _boom(*args, **kwargs):
        raise ValueError("annotation exploded")

    monkeypatch.setattr("processor.skimjoin.pipeline.annotate_trips", _boom)

    with pytest.raises(ValueError, match="annotation exploded"):
        apply_skimjoin(_skimjoin_ready_run_data(), config)


def test_apply_skimjoin_disabled_resets_manifest_and_reports(tmp_path: Path) -> None:
    config = _write_main_config(tmp_path, skimjoin_enabled=False)
    prepared = _skimjoin_ready_run_data()
    prepared.skimjoin_manifest = {"skimjoin_status": "applied"}
    prepared.skimjoin_reports = {
        "failure_report": pl.DataFrame(
            {"stage": ["old"], "error_type": ["ValueError"], "detail": ["old"]}
        )
    }

    result = apply_skimjoin(prepared, config)

    assert result.skimjoin_manifest == {
        "skimjoin_enabled": False,
        "skimjoin_status": "disabled",
        "skimjoin_config_digest": None,
        "skimjoin_resolved_network_los_file": None,
        "skimjoin_applied_outputs": [],
        "skimjoin_skipped_rules": [],
        "skimjoin_warning_count": 0,
        "skimjoin_fallback_count": 0,
        "skimjoin_fallback_outputs": [],
        "skimjoin_hypothetical_sidecars_enabled": False,
        "skimjoin_trip_hypothetical_rows": 0,
        "skimjoin_tour_hypothetical_rows": 0,
        "skimjoin_failure_detail": None,
    }
    assert result.skimjoin_reports == {}
    assert result.skimjoin_artifacts.manifest == result.skimjoin_manifest
    assert result.skimjoin_artifacts.reports == result.skimjoin_reports


def test_apply_skimjoin_records_failure_and_keeps_base_tables_when_tour_annotation_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    prepared = _skimjoin_ready_run_data()
    original_trips = prepared.trips.clone()
    original_tours = prepared.tours.clone()

    def _boom(*args, **kwargs):
        raise RuntimeError("tour annotation exploded")

    monkeypatch.setattr("processor.skimjoin.pipeline.annotate_tours", _boom)

    result = apply_skimjoin(prepared, config)

    assert result.trips.to_dicts() == original_trips.to_dicts()
    assert result.tours.to_dicts() == original_tours.to_dicts()
    assert result.skimjoin_manifest["skimjoin_status"] == "failed"
    assert "tour annotation exploded" in str(
        result.skimjoin_manifest["skimjoin_failure_detail"]
    )
    assert result.skimjoin_reports["failure_report"]["error_type"].to_list() == [
        "RuntimeError"
    ]


def test_prepared_cache_round_trip_preserves_skimjoin_failure_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    prepared = _skimjoin_ready_run_data()

    def _boom(*args, **kwargs):
        raise ValueError("annotation exploded")

    monkeypatch.setattr("processor.skimjoin.pipeline.annotate_trips", _boom)
    prepared = apply_skimjoin(prepared, config)

    cache_entry = write_prepared_run_cache(
        prepared,
        config,
        run_key="run-a",
        output_root=tmp_path / "prepared_cache",
    )
    loaded = load_prepared_run_cache(
        cache_entry.cache_dir,
        config,
        expected_prepare_config_digest=config.prepare_config_digest,
        expected_label=prepared.label,
        expected_run_key="run-a",
    )

    assert loaded.skimjoin_manifest["skimjoin_status"] == "failed"
    assert loaded.skimjoin_manifest["skimjoin_failure_detail"] == "ValueError: annotation exploded"


def test_apply_skimjoin_updates_typed_artifacts_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    prepared = _skimjoin_ready_run_data()

    def _boom(*args, **kwargs):
        raise ValueError("annotation exploded")

    monkeypatch.setattr("processor.skimjoin.pipeline.annotate_trips", _boom)

    result = apply_skimjoin(prepared, config)

    assert result.skimjoin_artifacts.manifest == result.skimjoin_manifest
    assert set(result.skimjoin_artifacts.reports) == set(result.skimjoin_reports)
    assert result.skimjoin_artifacts.manifest["skimjoin_status"] == "failed"


def _skimjoin_ready_run_data() -> RunData:
    return RunData(
        label="Skimjoin Ready",
        run_dir="C:/runs/skimjoin-ready",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=pl.DataFrame(
            {
                "tour_id": [1001],
                "tour_mode": ["SOV"],
                "finalweight": [1.0],
            }
        ),
        trips=pl.DataFrame(
            {
                "tour_id": [1001],
                "trip_mode": ["SOV"],
                "outbound": [True],
                "origin": [101],
                "destination": [102],
                "finalweight": [1.0],
            }
        ),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )


def _skim_summary_run_data() -> RunData:
    return RunData(
        label="Skim Summary Test",
        run_dir="C:/runs/skim",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=pl.DataFrame(
            {
                "tour_mode": ["DRIVE", "DRIVE", "DRIVE", "WALK", "WALK"],
                "skim_time": [10.0, 0.0, None, 5.0, 5.0],
                "skim_cost": [2.0, 4.0, 4.0, 1.0, None],
                "finalweight": [2.0, 1.0, 3.0, 1.0, 1.0],
            }
        ),
        trips=pl.DataFrame(
            {
                "trip_mode": ["DRIVE", "DRIVE", "DRIVE", "WALK", "WALK"],
                "skim_time": [10.0, 0.0, None, 5.0, 5.0],
                "skim_cost": [2.0, 4.0, 4.0, 1.0, None],
                "finalweight": [2.0, 1.0, 3.0, 1.0, 1.0],
            }
        ),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )


def test_trip_skim_component_stats_follow_weighted_contract(tmp_path: Path) -> None:
    config = _write_main_config(tmp_path, skimjoin_enabled=False)
    prepared = _skim_summary_run_data()

    weighted_stats = skimjoin_summaries.trip_skim_component_stats(prepared, config)

    drive_time = weighted_stats.filter(
        (pl.col("trip_mode") == "DRIVE") & (pl.col("component") == "skim_time")
    ).to_dicts()[0]
    drive_cost = weighted_stats.filter(
        (pl.col("trip_mode") == "DRIVE") & (pl.col("component") == "skim_cost")
    ).to_dicts()[0]
    all_modes_time = weighted_stats.filter(
        (pl.col("trip_mode") == "All Modes") & (pl.col("component") == "skim_time")
    ).to_dicts()[0]

    assert drive_time == {
        "skim_scenario": "chosen_mode",
        "trip_mode": "DRIVE",
        "component": "skim_time",
        "n_total": 6.0,
        "n_valid": 3.0,
        "mean": pytest.approx(20.0 / 3.0),
        "mean_nonzero": 10.0,
        "std": pytest.approx(math.sqrt(200.0 / 9.0)),
        "min": 0.0,
        "max": 10.0,
        "median": 10.0,
        "mode": 10.0,
        "zero_share": pytest.approx(1.0 / 3.0),
        "missing_share": 0.5,
    }
    assert drive_cost == {
        "skim_scenario": "chosen_mode",
        "trip_mode": "DRIVE",
        "component": "skim_cost",
        "n_total": 6.0,
        "n_valid": 6.0,
        "mean": pytest.approx(20.0 / 6.0),
        "mean_nonzero": pytest.approx(20.0 / 6.0),
        "std": pytest.approx(math.sqrt(8.0 / 9.0)),
        "min": 2.0,
        "max": 4.0,
        "median": 4.0,
        "mode": 4.0,
        "zero_share": 0.0,
        "missing_share": 0.0,
    }
    assert all_modes_time == {
        "skim_scenario": "chosen_mode",
        "trip_mode": "All Modes",
        "component": "skim_time",
        "n_total": 8.0,
        "n_valid": 5.0,
        "mean": 6.0,
        "mean_nonzero": 7.5,
        "std": pytest.approx(math.sqrt(14.0)),
        "min": 0.0,
        "max": 10.0,
        "median": 5.0,
        "mode": 5.0,
        "zero_share": 0.2,
        "missing_share": 0.375,
    }



def test_skimjoin_failure_keeps_non_skim_summaries_available_and_skim_summaries_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    _write_prepare_run_inputs(run_dir)
    skim_path = tmp_path / "skims.omx"
    _write_omx(skim_path)
    _write_skimjoin_config(tmp_path, skim_file=skim_path)
    config = _write_main_config(tmp_path, run_dir=run_dir, skimjoin_enabled=True)

    def _boom(*args, **kwargs):
        raise ValueError("annotation exploded")

    monkeypatch.setattr("processor.skimjoin.pipeline.annotate_trips", _boom)

    prepared_root = runtime_workflows.prepared_cache_root(config, create=True)
    result = runtime_workflows.run_prepare_workflow(
        config=config,
        prepared_root=prepared_root,
        run_entries=config.runs,
        prefer_cache=False,
        write_cache=False,
    )

    prepared = result.runs[0][1]
    summaries = summary_builder.build_summaries(
        prepared,
        config,
        summary_ids=["population_totals", "skimjoin_trip_component_stats"],
    )

    assert prepared.skimjoin_manifest["skimjoin_status"] == "failed"
    assert not summaries["population_totals"].is_empty()
    assert summaries["skimjoin_trip_component_stats"].is_empty()


def test_tour_skim_component_summaries_follow_unweighted_mode(tmp_path: Path) -> None:
    config = _write_main_config(tmp_path, skimjoin_enabled=False)
    prepared = summary_cache_types.strip_weights(_skim_summary_run_data())

    stats = skimjoin_summaries.tour_skim_component_stats(prepared, config)

    drive_time = stats.filter(
        (pl.col("tour_mode") == "DRIVE") & (pl.col("component") == "skim_time")
    ).to_dicts()[0]
    all_modes_time = stats.filter(
        (pl.col("tour_mode") == "All Modes") & (pl.col("component") == "skim_time")
    ).to_dicts()[0]
    assert drive_time["n_total"] == 3.0
    assert drive_time["n_valid"] == 2.0
    assert drive_time["mean"] == 5.0
    assert drive_time["mean_nonzero"] == 10.0
    assert drive_time["mode"] == 0.0
    assert drive_time["zero_share"] == 0.5
    assert drive_time["missing_share"] == pytest.approx(1.0 / 3.0)
    assert all_modes_time["n_total"] == 5.0
    assert all_modes_time["n_valid"] == 4.0
    assert all_modes_time["mean"] == 5.0
    assert all_modes_time["mean_nonzero"] == pytest.approx(20.0 / 3.0)
    assert all_modes_time["mode"] == 5.0
    assert all_modes_time["zero_share"] == 0.25
    assert all_modes_time["missing_share"] == 0.2



def test_all_modes_summary_uses_only_pertinent_modes_for_each_component(tmp_path: Path) -> None:
    config = _write_main_config(tmp_path, skimjoin_enabled=False)
    prepared = RunData(
        label="Pertinent Modes Test",
        run_dir="C:/runs/pertinent-modes",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=pl.DataFrame(),
        trips=pl.DataFrame(
            {
                "trip_mode": ["DRIVE", "DRIVE", "WALK", "WALK"],
                "skim_time": [10.0, None, None, None],
                "skim_walk": [None, None, 5.0, None],
                "finalweight": [2.0, 3.0, 4.0, 5.0],
            }
        ),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    stats = skimjoin_summaries.trip_skim_component_stats(prepared, config)

    all_modes_time = stats.filter(
        (pl.col("trip_mode") == "All Modes") & (pl.col("component") == "skim_time")
    ).to_dicts()[0]
    all_modes_walk = stats.filter(
        (pl.col("trip_mode") == "All Modes") & (pl.col("component") == "skim_walk")
    ).to_dicts()[0]

    assert all_modes_time["n_total"] == 5.0
    assert all_modes_time["n_valid"] == 2.0
    assert all_modes_time["missing_share"] == pytest.approx(3.0 / 5.0)
    assert all_modes_walk["n_total"] == 9.0
    assert all_modes_walk["n_valid"] == 4.0
    assert all_modes_walk["missing_share"] == pytest.approx(5.0 / 9.0)


def test_tour_annotation_uses_directional_period_source_columns(
    tmp_path: Path,
) -> None:
    skim_path = tmp_path / "skims.omx"
    handle = omx.open_file(str(skim_path), "w")
    handle["SOV_TIME__AM"] = np.array([[1.0, 2.0], [3.0, 4.0]])
    handle["SOV_TIME__PM"] = np.array([[10.0, 20.0], [30.0, 40.0]])
    handle.create_mapping("taz", np.array([1, 2], dtype=np.uint32))
    handle.close()
    config_path = tmp_path / "skimjoin.yaml"
    config_path.write_text(
        "\n".join(
            [
                "project:",
                "  skim_files:",
                f"    - {skim_path.name}",
                "activitysim:",
                "  trip_mode_column: trip_mode",
                "  tour_mode_column: tour_mode",
                "  trip_id_column: trip_id",
                "  tour_id_column: tour_id",
                "  outbound_column: outbound",
                "zone_mapping:",
                "  lookup_name: taz",
                "dimensions:",
                "  PERIOD:",
                "    source_columns:",
                "      trip_source_column: trip_period",
                "      outbound_tour_source_column: start_period",
                "      inbound_tour_source_column: first_inbound_trip_period",
                "defaults:",
                "  origin: OTAZ",
                "  destination: DTAZ",
                "modes:",
                "  SOV:",
                "    time: SOV_TIME__{PERIOD}",
            ]
        ),
        encoding="utf-8",
    )
    config = _write_main_config(tmp_path, skimjoin_enabled=True)
    normalized = config.skimjoin.normalized_config
    assert normalized is not None
    inventory = inventory_skim_files(normalized.skim_files)
    tours = pl.DataFrame(
        {
            "tour_id": [1],
            "tour_mode": ["SOV"],
            "origin": [1],
            "destination": [2],
            "start_period": ["AM"],
            "first_inbound_trip_period": ["PM"],
            "OTAZ": [1],
            "DTAZ": [2],
        }
    )

    annotated, _, missing = annotate_tours(tours, normalized, inventory)

    assert missing.is_empty()
    assert annotated["skim_time_outbound"].to_list() == [2.0]
    assert annotated["skim_time_inbound"].to_list() == [30.0]


def test_skim_component_stats_return_typed_empty_frames_without_numeric_skim_columns(
    tmp_path: Path,
) -> None:
    config = _write_main_config(tmp_path, skimjoin_enabled=False)
    prepared = RunData(
        label="Empty",
        run_dir="C:/runs/empty",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=pl.DataFrame({"tour_mode": ["DRIVE"], "skim_label": ["x"], "finalweight": [1.0]}),
        trips=pl.DataFrame({"trip_mode": ["DRIVE"], "skim_label": ["x"], "finalweight": [1.0]}),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    trip_stats = skimjoin_summaries.trip_skim_component_stats(prepared, config)
    tour_stats = skimjoin_summaries.tour_skim_component_stats(prepared, config)

    assert trip_stats.schema == empty_summary_frame(
        skimjoin_summaries.trip_skim_component_stats
    ).schema
    assert tour_stats.schema == empty_summary_frame(
        skimjoin_summaries.tour_skim_component_stats
    ).schema
    assert trip_stats.is_empty()
    assert tour_stats.is_empty()


def test_skim_component_stats_handle_late_float_values_without_schema_inference_failures(
    tmp_path: Path,
) -> None:
    config = _write_main_config(tmp_path, skimjoin_enabled=False)
    prepared = RunData(
        label="Schema Mix",
        run_dir="C:/runs/schema-mix",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=pl.DataFrame(),
        trips=pl.DataFrame(
            {
                "trip_mode": ["DRIVE", "DRIVE"],
                "skim_time": pl.Series("skim_time", [1.0, 15.69609], dtype=pl.Float64),
                "finalweight": [1.0, 1.0],
            }
        ),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )

    stats = skimjoin_summaries.trip_skim_component_stats(prepared, config)

    drive_time = stats.to_dicts()[0]
    assert drive_time["component"] == "skim_time"
    assert drive_time["max"] == pytest.approx(15.69609)
