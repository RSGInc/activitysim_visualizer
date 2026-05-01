from __future__ import annotations

import json
from pathlib import Path
import sys

import panel as pn
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.export.payload import temporary_widget_values
from dashboard.export.runtime_assets import build_export_html_shell, load_export_runtime_js
from dashboard.export.types import EXPORT_SCHEMA_VERSION
from test_export_html import _full_summary_run, _write_config
from dashboard.export.html import build_export_html_document


FIXTURE_DIR = Path(__file__).with_name("fixtures")
REQUIRED_TOP_LEVEL_FIELDS = {
    "schema_version",
    "title",
    "runs_loaded",
    "chrome",
    "dashboard_controls",
    "default_state",
    "pages",
    "states",
    "page_export_support",
    "client_runtime",
}


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _assert_valid_runtime_fixture(payload: dict) -> None:
    # The implementation plan called this field `initial_state`, but the
    # repository's current contract uses `default_state`. This assertion locks in
    # the real payload shape rather than inventing a new API.
    assert REQUIRED_TOP_LEVEL_FIELDS <= set(payload)
    assert payload["schema_version"] == EXPORT_SCHEMA_VERSION
    assert isinstance(payload["pages"], list)
    assert isinstance(payload["states"], dict)
    assert isinstance(payload["default_state"], dict)
    assert isinstance(payload["page_export_support"], dict)


def test_runtime_contract_fixtures_match_expected_top_level_shape() -> None:
    for fixture_name in [
        "minimal_payload.json",
        "grouped_pages_payload.json",
        "selector_region_payload.json",
        "plot_payload.json",
    ]:
        _assert_valid_runtime_fixture(_load_fixture(fixture_name))


def test_malformed_runtime_fixture_is_missing_required_contract_fields() -> None:
    payload = _load_fixture("malformed_payload.json")

    assert "default_state" not in payload
    assert "states" not in payload
    assert REQUIRED_TOP_LEVEL_FIELDS - set(payload)


def test_runtime_asset_replaces_schema_placeholder() -> None:
    runtime_js = load_export_runtime_js()

    assert "__EXPORT_SCHEMA_VERSION__" not in runtime_js
    assert EXPORT_SCHEMA_VERSION in runtime_js


def test_html_shell_embeds_schema_version_payload_runtime_and_css() -> None:
    shell = build_export_html_shell(
        title="Contract Test",
        payload_json='{"schema_version":"%s"}' % EXPORT_SCHEMA_VERSION,
        plotly_js="window.Plotly = {};",
    )

    assert "<style>" in shell
    assert '<script id="activitysim-export-data" type="application/json">' in shell
    assert "window.Plotly = {};" in shell
    assert EXPORT_SCHEMA_VERSION in shell
    assert "__EXPORT_SCHEMA_VERSION__" not in shell


def test_generated_export_html_contains_no_raw_nan_or_infinity(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    start_token = '<script id="activitysim-export-data" type="application/json">'
    start = html.index(start_token) + len(start_token)
    end = html.index("</script>", start)
    payload_json = html[start:end]

    assert "NaN" not in payload_json
    assert "Infinity" not in payload_json


def test_temporary_widget_values_restores_original_values_after_success() -> None:
    widgets = {
        "tour_purpose": pn.widgets.Select(
            name="Tour Purpose",
            options=["All", "eatout"],
            value="All",
        ),
        "tour_mode": pn.widgets.Select(
            name="Tour Mode",
            options=["Drive", "Walk"],
            value="Drive",
        ),
    }

    with temporary_widget_values(
        widgets,
        {"tour_purpose": "eatout", "tour_mode": "Walk"},
    ):
        assert widgets["tour_purpose"].value == "eatout"
        assert widgets["tour_mode"].value == "Walk"

    assert widgets["tour_purpose"].value == "All"
    assert widgets["tour_mode"].value == "Drive"


def test_temporary_widget_values_restores_original_values_after_exception() -> None:
    widgets = {
        "tour_purpose": pn.widgets.Select(
            name="Tour Purpose",
            options=["All", "eatout"],
            value="All",
        ),
        "missing_safe": None,
    }

    with pytest.raises(RuntimeError, match="boom"):
        with temporary_widget_values(
            widgets,
            {"tour_purpose": "eatout", "missing_safe": "ignored"},
        ):
            assert widgets["tour_purpose"].value == "eatout"
            raise RuntimeError("boom")

    assert widgets["tour_purpose"].value == "All"
