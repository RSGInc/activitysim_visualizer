from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.config import (
    Config,
    CsvLookupSegmentationSource,
    ExportDashboardSettings,
    ExportHTMLSettings,
    ExportSelectorRequest,
    PreparedColumnSegmentationSource,
    SegmentationDefinition,
    StudentTypeConfig,
    config_for_run,
    resolve_run_skimjoin_settings,
)
from processor.skimjoin.config.io import (
    load_config_file as load_skimjoin_config_file,
)
from processor.skimjoin.config.normalize import normalize_config as normalize_skimjoin
from processor.skimjoin.config.validation import (
    load_config as validate_skimjoin_config,
)


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_config_public_import_surface_and_package_resolution(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Package Surface Test"',
                "runs: []",
                "root: summary_cache",
                "dashboard:",
                '  title: "Package Surface Test"',
            ]
        ),
        encoding="utf-8",
    )

    config = Config.from_yaml(config_path)

    assert "runtime\\config\\__init__.py".lower() in sys.modules["runtime.config"].__file__.lower()
    assert isinstance(config, Config)
    assert isinstance(config.export_html, ExportHTMLSettings)
    assert isinstance(config.export_html.dashboard, ExportDashboardSettings)
    assert isinstance(config.export_html.default_selector_request, ExportSelectorRequest)
    assert callable(config_for_run)
    assert callable(resolve_run_skimjoin_settings)
    assert StudentTypeConfig is not None
    assert PreparedColumnSegmentationSource is not None
    assert CsvLookupSegmentationSource is not None
    assert SegmentationDefinition is not None


def test_repository_example_configs_match_current_schemas() -> None:
    config = Config.from_yaml(ROOT / "config.yaml")

    assert config.pipeline.steps == ("summarize", "dashboard")
    assert config.pipeline.dashboard_mode == "live"
    assert config.skimjoin.enabled is False
    assert config.skimjoin.config_path == str(
        (ROOT / "example_skimjoin_config.yaml").resolve()
    )
    assert config.include_notes is True
    assert config.missing_data_display == "card"

    skimjoin_raw = load_skimjoin_config_file(
        ROOT / "example_skimjoin_config.yaml"
    )
    # The example intentionally points at a placeholder network_los.yaml.
    # Supply a small explicit period map in memory so every mode/component can
    # still pass the full normalizer without requiring user data.
    skimjoin_raw["dimensions"]["PERIOD"]["values_from_network_los"] = False
    skimjoin_raw["dimensions"]["PERIOD"]["values"] = {"1": "EA"}
    skimjoin = validate_skimjoin_config(
        skimjoin_raw,
        require_activitysim_tables=False,
    )
    normalized_skimjoin = normalize_skimjoin(skimjoin)

    assert tuple(skimjoin.modes) == (
        "SOV",
        "HOV2",
        "HOV3",
        "WALK",
        "WALK_TRANSIT",
        "PNR_TRANSIT",
    )
    assert normalized_skimjoin.trip_lookups
    assert normalized_skimjoin.tour_lookups
