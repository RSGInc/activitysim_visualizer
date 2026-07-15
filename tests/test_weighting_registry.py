from __future__ import annotations

from pathlib import Path
import sys
import types

import polars as pl
import pytest

from dashboard import DashboardState
from dashboard.data_access import DashboardPreparedRunProvider
from processor.models import RunData, map_run_data_tables
from processor.summarize.builder import build_mode_summaries
from processor.summarize.cache import (
    load_summary_run_cache,
    write_summary_run_cache,
)
from processor.summarize.cache_types import create_summary_run
from processor.summarize.external import load_summary_table_map
from runtime.config import Config
from runtime.weighting import (
    WeightingModeDefinition,
    WeightingModeRegistry,
    load_weighting_mode_extensions,
)


def _run() -> RunData:
    return RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame({"finalweight": [2.0]}),
        per=pl.DataFrame({"finalweight": [3.0]}),
        tours=pl.DataFrame({"finalweight": [4.0]}),
        trips=pl.DataFrame({"finalweight": [5.0], "stops": [1]}),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
    )


def _install_tripled_module(monkeypatch: pytest.MonkeyPatch) -> str:
    module_name = "test_project_weighting_extension"
    module = types.ModuleType(module_name)

    def tripled(run: RunData, config: Config | None) -> RunData:
        assert config is not None
        factor = float(config.extension_settings["tripled"]["factor"])
        return map_run_data_tables(
            run,
            lambda _table_name, frame: (
                frame.with_columns(
                    (pl.col("finalweight") * factor).alias("finalweight")
                )
                if "finalweight" in frame.columns
                else frame
            ),
        )

    def register_weighting_modes(registry: WeightingModeRegistry) -> None:
        registry.register(
            WeightingModeDefinition(
                mode_id="tripled_test",
                label="Tripled Test",
                transform=tripled,
                version="2026.1",
                required_columns={
                    "hh": ("finalweight",),
                    "per": ("finalweight",),
                    "tours": ("finalweight",),
                    "trips": ("finalweight",),
                },
                external_summary_policy="reject",
            )
        )

    module.register_weighting_modes = register_weighting_modes
    monkeypatch.setitem(sys.modules, module_name, module)
    return module_name


def _plugin_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Config:
    module_name = _install_tripled_module(monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "extensions:",
                "  modules:",
                f"    - {module_name}",
                "  settings:",
                "    tripled:",
                "      factor: 3",
                "summarize:",
                "  weighting_modes: [weighted, tripled_test]",
                "dashboard:",
                "  export:",
                "    dashboard:",
                "      weighting: all",
                "runs: []",
            ]
        ),
        encoding="utf-8",
    )
    return Config.from_yaml(config_path)


def test_registry_validates_ids_labels_and_mode_order() -> None:
    registry = WeightingModeRegistry()
    registry.register(
        WeightingModeDefinition(
            mode_id="first",
            label="First",
            transform=lambda run, config: run,
            version="1",
            default_enabled=True,
        )
    )
    registry.register(
        WeightingModeDefinition(
            mode_id="second",
            label="Second",
            transform=lambda run, config: run,
            version="2",
        )
    )

    assert registry.normalize(None) == ["first"]
    assert registry.normalize(["second", "first", "second"]) == [
        "second",
        "first",
    ]
    with pytest.raises(ValueError, match="Duplicate weighting mode id"):
        registry.register(
            WeightingModeDefinition(
                mode_id="first",
                label="Another",
                transform=lambda run, config: run,
                version="1",
            )
        )
    with pytest.raises(ValueError, match="already used"):
        registry.register(
            WeightingModeDefinition(
                mode_id="another",
                label="SECOND",
                transform=lambda run, config: run,
                version="1",
            )
        )


def test_entry_point_registration_uses_the_same_registry_contract(monkeypatch) -> None:
    registry = WeightingModeRegistry()

    class FakeEntryPoint:
        name = "sample"
        value = "sample.plugin:register"

        @staticmethod
        def load():
            def register(target: WeightingModeRegistry) -> None:
                target.register(
                    WeightingModeDefinition(
                        mode_id="sample",
                        label="Sample",
                        transform=lambda run, config: run,
                        version="1",
                    )
                )

            return register

    class FakeEntryPoints(list):
        def select(self, *, group: str):
            assert group == "activitysim_visualizer.weighting_modes"
            return self

    monkeypatch.setattr(
        "runtime.weighting.metadata.entry_points",
        lambda: FakeEntryPoints([FakeEntryPoint()]),
    )

    load_weighting_mode_extensions((), registry=registry)

    assert registry.get("sample").label == "Sample"


def test_custom_mode_flows_through_config_summary_dashboard_and_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _plugin_config(tmp_path, monkeypatch)

    assert config.weighting_modes == ["weighted", "tripled_test"]
    assert config.weighting_mode_label("tripled_test") == "Tripled Test"
    assert config.export_html.panel_weighting_values() == [
        "Weighted",
        "Tripled Test",
    ]
    assert config.summary_signature_payload()["weighting_modes"][1]["version"] == (
        "2026.1"
    )
    assert config.summary_signature_payload()["extension_settings"] == {
        "tripled": {"factor": 3}
    }

    summaries = build_mode_summaries(
        _run(),
        config,
        summary_ids=["population_totals"],
    )
    assert summaries["weighted"]["population_totals"]["person_count"][0] == 3.0
    assert summaries["tripled_test"]["population_totals"]["person_count"][0] == 9.0

    cache_dir = write_summary_run_cache(
        create_summary_run(
            label="Base",
            run_key="base",
            summaries_by_mode=summaries,
        ),
        config,
        output_root=tmp_path / "summary_cache",
    )
    loaded = load_summary_run_cache(
        cache_dir,
        config,
        expected_modes=config.weighting_modes,
        expected_summary_ids=["population_totals"],
        expected_summary_config_digest=config.summary_config_digest,
    )
    assert list(loaded.summaries_by_mode) == ["weighted", "tripled_test"]

    state = DashboardState(
        weighting_modes=config.weighting_modes,
        weighting_definitions=config.weighting_mode_definitions,
        config=config,
        prepared_run_provider=DashboardPreparedRunProvider.loaded([("Base", _run())]),
    )
    assert list(state.param.weight_mode.objects) == ["Weighted", "Tripled Test"]
    state.weight_mode = "Tripled Test"
    prepared = state.get_prepared_runs_if_loaded()
    prepared_again = state.get_prepared_runs_if_loaded()
    assert state.weighting_key() == "tripled_test"
    assert prepared is not None
    assert prepared_again is not None
    assert prepared[0][1].trips["finalweight"][0] == 15.0
    assert prepared_again[0][1] is prepared[0][1]


def test_custom_mode_must_explicitly_accept_mode_independent_outside_summaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _plugin_config(tmp_path, monkeypatch)
    summary_path = tmp_path / "population_totals.csv"
    pl.DataFrame(
        {
            "person_count": [1.0],
            "household_count": [1.0],
            "tour_count": [1.0],
            "trip_count": [1.0],
            "stop_count": [0.0],
        }
    ).write_csv(summary_path)

    with pytest.raises(ValueError, match="tripled_test"):
        load_summary_table_map(
            summary_table_map={"population_totals": str(summary_path)},
            label="Base",
            run_key="base",
            config=config,
        )


def test_registered_mode_reports_missing_required_columns() -> None:
    definition = WeightingModeDefinition(
        mode_id="needs_calibration",
        label="Needs Calibration",
        transform=lambda run, config: run,
        version="1",
        required_columns={"hh": ("calibrated_weight",)},
    )

    with pytest.raises(
        ValueError,
        match="requires columns on 'hh': calibrated_weight",
    ):
        definition.apply(_run(), None)
