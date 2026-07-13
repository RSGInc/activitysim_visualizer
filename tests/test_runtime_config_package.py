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
