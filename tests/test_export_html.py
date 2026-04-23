from __future__ import annotations

import json
import logging
from pathlib import Path
import sys

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _dashboard_expectations import EXPECTED_DEFAULT_PAGES
from dashboard.export.html import build_export_html_document, write_export_html_document
from dashboard.export.types import EXPORT_CLIENT_RUNTIME, EXPORT_SCHEMA_VERSION
from runtime.config import Config
from runtime.models import RunData
from summarize.cache import create_summary_run


def _write_config(
    tmp_path: Path,
    *,
    dashboard_pages: list[str] | None | object = ...,
    weighting_modes: list[str] | None = None,
    modes_lines: list[str] | None = None,
    geography_lines: list[str] | None = None,
    export_html_lines: list[str] | None = None,
) -> Config:
    weighting_modes = weighting_modes or ["weighted", "unweighted"]
    tmp_path.mkdir(parents=True, exist_ok=True)
    lines = [
        'name: "Test Config"',
        "runs: []",
        "summaries:",
        "  root: summary_cache",
        "  weighting_modes:",
    ]
    lines.extend(f"    - {mode}" for mode in weighting_modes)
    lines.extend(
        [
            "visualizer:",
            '  dashboard_title: "Test Dashboard"',
        ]
    )
    if dashboard_pages is ...:
        dashboard_pages = [page_id for page_id, _ in EXPECTED_DEFAULT_PAGES]
    if dashboard_pages is not None:
        lines.append("  dashboard_pages:")
        lines.extend(f"    - {page_id}" for page_id in dashboard_pages)
    if export_html_lines:
        lines.append("  export_html:")
        lines.extend(f"    {line}" for line in export_html_lines)
    if modes_lines:
        lines.append("modes:")
        lines.extend(f"  {line}" for line in modes_lines)
    else:
        lines.append("modes: {}")
    if geography_lines:
        lines.append("geography:")
        lines.extend(f"  {line}" for line in geography_lines)

    config_path = tmp_path / "config.yaml"
    config_path.write_text("\n".join(lines), encoding="utf-8")
    return Config.from_yaml(config_path)


def _scale_table(df: pl.DataFrame, factor: float) -> pl.DataFrame:
    metric_columns = {
        "person_count",
        "household_count",
        "tour_count",
        "trip_count",
        "stop_count",
        "auto_vmt",
        "worker_count",
        "work_from_home_worker_count",
        "household_percent",
        "joint_tour_count",
    }
    exprs = [
        (pl.col(column) * factor).alias(column)
        for column in df.columns
        if column in metric_columns
        or column.startswith("freq")
        or column.startswith("pct")
        or column.startswith("avg")
        or column.endswith(("_count", "_distance", "_percent"))
    ]
    return df.with_columns(exprs) if exprs else df.clone()


def _full_summary_run():
    weighted = {
        "population_totals": pl.DataFrame(
            {
                "person_count": [100.0],
                "household_count": [40.0],
                "tour_count": [55.0],
                "trip_count": [120.0],
                "stop_count": [35.0],
            }
        ),
        "person_type_distribution": pl.DataFrame(
            {
                "person_type": ["worker", "student"],
                "person_type_label": ["worker", "student"],
                "person_count": [70.0, 30.0],
            }
        ),
        "household_size_distribution": pl.DataFrame(
            {
                "household_size": [1, 2],
                "household_count": [15.0, 25.0],
            }
        ),
        "auto_vmt_totals": pl.DataFrame({"auto_vmt": [180.0]}),
        "auto_ownership_distribution": pl.DataFrame(
            {
                "household_vehicle_count": [0, 1],
                "household_count": [12.0, 18.0],
            }
        ),
        "work_location_distance_distribution_by_geography": pl.DataFrame(
            {
                "distance_bin": [1, 2, 1, 2, 1, 2],
                "geography": [
                    "all_geographies",
                    "all_geographies",
                    "Urban",
                    "Urban",
                    "Suburban",
                    "Suburban",
                ],
                "person_count": [6.0, 4.0, 4.0, 2.5, 2.0, 1.5],
            }
        ),
        "university_location_distance_distribution_by_geography": pl.DataFrame(
            {
                "distance_bin": [1, 2, 1, 2, 1, 2],
                "geography": [
                    "all_geographies",
                    "all_geographies",
                    "Urban",
                    "Urban",
                    "Suburban",
                    "Suburban",
                ],
                "person_count": [3.0, 2.0, 1.5, 1.0, 1.5, 1.0],
            }
        ),
        "school_location_distance_distribution_by_geography": pl.DataFrame(
            {
                "distance_bin": [1, 2, 1, 2, 1, 2],
                "geography": [
                    "all_geographies",
                    "all_geographies",
                    "Urban",
                    "Urban",
                    "Suburban",
                    "Suburban",
                ],
                "person_count": [5.0, 1.0, 3.0, 0.5, 2.0, 0.5],
            }
        ),
        "geo_flows": pl.DataFrame(
            {
                "Home Geography": ["Urban", "Suburban"],
                "Work Geography": ["Urban", "Suburban"],
                "Workers": [7.0, 4.0],
            }
        ),
        "work_from_home_rate_by_geography": pl.DataFrame(
            {
                "geography": ["all_geographies", "Urban", "Suburban"],
                "worker_count": [20.0, 12.0, 8.0],
                "work_from_home_worker_count": [11.0, 7.0, 4.0],
            }
        ),
        "telecommute_frequency_distribution": pl.DataFrame(
            {
                "telecommute_frequency": ["never", "often"],
                "person_count": [7.0, 5.0],
            }
        ),
        "average_mandatory_tour_distance_by_purpose_and_geography": pl.DataFrame(
            {
                "mandatory_tour_purpose": ["work", "work", "work"],
                "geography": ["all_geographies", "Urban", "Suburban"],
                "average_tour_distance": [8.5, 7.5, 9.5],
            }
        ),
        "daily_activity_pattern_by_person_type": pl.DataFrame(
            {
                "person_type": [
                    "all_person_types",
                    "all_person_types",
                    "all_person_types",
                    "worker",
                    "worker",
                ],
                "daily_activity_pattern": ["M", "N", "H", "M", "N"],
                "person_count": [10.0, 8.0, 2.0, 6.0, 4.0],
            }
        ),
        "mandatory_tour_frequency_by_person_type": pl.DataFrame(
            {
                "person_type": [
                    "all_person_types",
                    "all_person_types",
                    "worker",
                    "worker",
                ],
                "mandatory_tour_frequency": [1, 2, 1, 5],
                "person_count": [7.0, 5.0, 4.0, 2.0],
            }
        ),
        "nonmandatory_tour_frequency_by_person_type": pl.DataFrame(
            {
                "person_type": [
                    "all_person_types",
                    "all_person_types",
                    "worker",
                    "worker",
                ],
                "nonmandatory_tour_frequency": ["0", "1", "0", "2"],
                "person_count": [3.0, 9.0, 2.0, 6.0],
            }
        ),
        "jtf_distribution": pl.DataFrame(
            {
                "jtf_code": [1, 2, 3],
                "jtf_label": ["No Joint Tours", "1 Shopping", "1 Maintenance"],
                "household_count": [12.0, 5.0, 3.0],
            }
        ),
        "joint_tour_composition_distribution": pl.DataFrame(
            {
                "tour_composition": ["adults", "mixed", "children"],
                "joint_tour_count": [4.0, 3.0, 1.0],
            }
        ),
        "joint_tour_party_size_distribution": pl.DataFrame(
            {"party_size": [2, 3], "joint_tour_count": [5.0, 3.0]}
        ),
        "household_jtp_by_household_size_and_jtf": pl.DataFrame(
            {
                "household_size": ["2", "2", "3", "3"],
                "jtf": ["0", "1", "0", "2+"],
                "household_percent": [40.0, 60.0, 37.5, 62.5],
            }
        ),
        "destination_distance": pl.DataFrame(
            {
                "purpose": ["All NM", "All NM", "eatout", "eatout", "social", "social"],
                "distbin": [0, 1, 0, 1, 0, 1],
                "freq": [5.0, 7.5, 2.0, 4.0, 3.0, 2.0],
            }
        ),
        "destination_average_distance": pl.DataFrame(
            {
                "purpose": ["eatout", "social"],
                "avg_distance": [3.25, 4.5],
            }
        ),
        "tour_time_of_day_by_tour_purpose": pl.DataFrame(
            {
                "tour_purpose": [
                    "all_tour_purposes",
                    "all_tour_purposes",
                    "work",
                    "work",
                ],
                "time_bin": [1, 2, 1, 2],
                "departure_tour_count": [5.0, 6.0, 3.0, 4.0],
                "arrival_tour_count": [4.0, 5.0, 2.0, 3.0],
                "duration_tour_count": [2.0, 3.0, 1.0, 2.0],
            }
        ),
        "tour_mode_by_tour_purpose_and_auto_sufficiency": pl.DataFrame(
            {
                "tour_purpose": [
                    "all_tour_purposes",
                    "all_tour_purposes",
                    "work",
                    "work",
                ],
                "tour_mode": ["DRIVE", "WALK", "DRIVE", "WALK"],
                "tour_count_all_households": [10.0, 5.0, 7.0, 3.0],
                "tour_count_zero_auto": [2.0, 4.0, 1.0, 2.0],
                "tour_count_auto_deficient": [3.0, 1.0, 2.0, 1.0],
                "tour_count_auto_sufficient": [5.0, 0.0, 4.0, 0.0],
            }
        ),
        "grouped_tour_mode_profile": pl.DataFrame(
            {
                "mode_group": ["Auto", "Active", "Auto", "Active"],
                "purpose": ["Total", "Total", "work", "work"],
                "freq_all": [10.0, 5.0, 7.0, 3.0],
                "freq_as0": [2.0, 4.0, 1.0, 2.0],
                "freq_as1": [3.0, 1.0, 2.0, 1.0],
                "freq_as2": [5.0, 0.0, 4.0, 0.0],
            }
        ),
        "tour_stop_frequency_by_tour_purpose": pl.DataFrame(
            {
                "tour_purpose": [
                    "all_tour_purposes",
                    "all_tour_purposes",
                    "eatout",
                    "eatout",
                    "social",
                ],
                "outbound_stop_count": [0, 1, 0, 1, 0],
                "inbound_stop_count": [0, 1, 0, 0, 1],
                "total_stop_count": [0, 2, 0, 1, 1],
                "tour_count": [18.0, 5.0, 10.0, 5.0, 8.0],
            }
        ),
        "stop_destination_purpose_by_tour_purpose": pl.DataFrame(
            {
                "tour_purpose": [
                    "all_tour_purposes",
                    "all_tour_purposes",
                    "eatout",
                    "eatout",
                    "social",
                ],
                "stop_destination_purpose": ["shop", "eat", "shop", "eat", "visit"],
                "stop_count": [4.0, 14.0, 4.0, 6.0, 8.0],
            }
        ),
        "stop_out_of_direction_distance_by_tour_purpose": pl.DataFrame(
            {
                "tour_purpose": [
                    "all_tour_purposes",
                    "all_tour_purposes",
                    "eatout",
                    "eatout",
                    "social",
                    "social",
                ],
                "distance_bin": [0, 1, 0, 1, 0, 1],
                "stop_count": [13.0, 11.0, 8.0, 4.0, 5.0, 7.0],
            }
        ),
        "trip_departure_time_by_purpose": pl.DataFrame(
            {
                "tour_purpose": [
                    "all_tour_purposes",
                    "all_tour_purposes",
                    "eatout",
                    "eatout",
                    "social",
                    "social",
                ],
                "time_bin": [1, 2, 1, 2, 1, 2],
                "departure_stop_count": [8.0, 10.0, 3.0, 4.0, 5.0, 6.0],
                "departure_trip_count": [6.0, 8.0, 2.0, 3.0, 4.0, 5.0],
            }
        ),
        "trip_mode_by_tour_purpose_and_tour_mode": pl.DataFrame(
            {
                "tour_purpose": [
                    "all_tour_purposes",
                    "all_tour_purposes",
                    "eatout",
                    "eatout",
                    "social",
                    "social",
                    "all_tour_purposes",
                    "eatout",
                    "social",
                ],
                "tour_mode": [
                    "DRIVE",
                    "WALK",
                    "DRIVE",
                    "WALK",
                    "DRIVE",
                    "WALK",
                    "all_tour_modes",
                    "all_tour_modes",
                    "all_tour_modes",
                ],
                "trip_mode": [
                    "DRIVEALONE",
                    "WALK",
                    "DRIVEALONE",
                    "WALK",
                    "SHARED",
                    "WALK",
                    "WALK",
                    "DRIVEALONE",
                    "SHARED",
                ],
                "trip_count": [15.0, 5.0, 10.0, 2.0, 5.0, 3.0, 5.0, 10.0, 5.0],
            }
        ),
    }
    unweighted = {name: _scale_table(df, 0.5) for name, df in weighted.items()}
    return create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": weighted,
            "unweighted": unweighted,
        },
        source_run_dir=str(Path("C:/runs/base")),
    )


def _raw_trip_run() -> RunData:
    return RunData(
        label="Base",
        run_dir="C:/runs/base",
        skim_file=None,
        hh=pl.DataFrame({"household_id": [1], "finalweight": [2.0]}),
        per=pl.DataFrame({"person_id": [1], "household_id": [1], "finalweight": [3.0]}),
        tours=pl.DataFrame({"tour_id": [10], "finalweight": [4.0]}),
        trips=pl.DataFrame(
            {
                "trip_id": [100, 101, 102],
                "tour_id": [10, 10, 10],
                "trip_mode": ["DRIVEALONE", "WALK", "WALK"],
                "finalweight": [5.0, 2.0, 1.0],
            }
        ),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
        skim_zone_map=None,
    )


def test_export_html_config_defaults_to_weighted_percent(tmp_path: Path) -> None:
    config = _write_config(tmp_path)

    assert config.export_html.weighting == ["weighted"]
    assert config.export_html.values == ["percent"]
    assert config.dashboard_pages == [page_id for page_id, _ in EXPECTED_DEFAULT_PAGES]
    assert config.export_html.dashboard.weighting == ["weighted"]
    assert config.export_html.dashboard.values == ["percent"]
    assert config.export_html.pages == {}
    assert config.export_html.panel_weighting_values() == ["Weighted"]
    assert config.export_html.panel_value_values() == ["Percent"]


def test_export_html_config_supports_new_summaries_and_visualizer_sections(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=["overview", "trip_mode"],
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "pages:",
            "  trip_mode:",
            "    tour_mode: all",
            "  overview: {}",
        ],
    )

    assert config.summary_root.endswith("summary_cache")
    assert config.dashboard_pages == ["overview", "trip_mode"]
    assert list(config.export_html.pages) == ["trip_mode", "overview"]
    assert config.export_html.pages_configured is True


def test_export_html_config_resolves_nested_dashboard_and_page_requests(
    tmp_path: Path,
) -> None:
    config_all = _write_config(
        tmp_path / "all",
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
            "pages:",
            "  tour_summary:",
            "    person_type: all",
            "  trip_mode:",
            "    tour_mode:",
            "      - all",
            "      - drive",
        ],
    )
    config_list = _write_config(
        tmp_path / "list",
        export_html_lines=[
            "dashboard:",
            "  weighting:",
            "    - Unweighted",
            "    - weighted",
            "    - UNWEIGHTED",
            "  values:",
            "    - COUNT",
            "    - percent",
            "    - count",
            "pages:",
            "  destination:",
            "    purpose:",
            "      - all nm",
            "      - eatout",
        ],
    )

    assert config_all.export_html.weighting == ["weighted", "unweighted"]
    assert config_all.export_html.values == ["percent", "count"]
    assert (
        config_all.export_html.selector_request("tour_summary", "person_type").mode
        == "all"
    )
    assert (
        config_all.export_html.selector_request("trip_mode", "tour_mode").mode
        == "explicit"
    )
    assert config_all.export_html.selector_request("trip_mode", "tour_mode").values == (
        "all",
        "drive",
    )
    assert config_list.export_html.weighting == ["unweighted", "weighted"]
    assert config_list.export_html.values == ["count", "percent"]
    assert (
        config_list.export_html.selector_request("destination", "purpose").mode
        == "explicit"
    )
    assert config_list.export_html.selector_request(
        "destination", "purpose"
    ).values == (
        "all nm",
        "eatout",
    )


def test_config_allows_missing_dashboard_pages(tmp_path: Path) -> None:
    config = _write_config(tmp_path, dashboard_pages=None)

    assert config.dashboard_pages is None


def test_config_defaults_when_summaries_and_visualizer_sections_are_absent(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Legacy Layout"',
                'dashboard_title: "Ignored Legacy Title"',
                "run_colors:",
                '  - "#111111"',
                "outputs:",
                "  summary_root: ignored_summary_cache",
                "  weighting_modes:",
                "    - weighted",
                "  export_html:",
                "    dashboard:",
                "      weighting: all",
                "dashboard_pages:",
                "  - raw_trip_demo",
                "runs: []",
            ]
        ),
        encoding="utf-8",
    )

    config = Config.from_yaml(config_path)

    assert config.summary_root == str(
        (tmp_path / "artifacts" / "summary_cache").resolve()
    )
    assert config.weighting_modes == ["weighted", "unweighted"]
    assert config.dashboard_title == "Ignored Legacy Title"
    assert config.dashboard_pages is None
    assert config.run_colors == [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
    ]
    assert config.export_html.dashboard.weighting == ["weighted"]
    assert config.export_html.dashboard.values == ["percent"]
    assert config.export_html.pages == {}


def test_config_prefers_visualizer_dashboard_title_over_legacy_top_level_title(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Dashboard Title Precedence"',
                'dashboard_title: "Legacy Dashboard Title"',
                "runs: []",
                "visualizer:",
                '  dashboard_title: "Visualizer Dashboard Title"',
            ]
        ),
        encoding="utf-8",
    )

    config = Config.from_yaml(config_path)

    assert config.dashboard_title == "Visualizer Dashboard Title"


def test_config_ignores_flat_export_html_dashboard_aliases(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Flat Export Legacy"',
                "runs: []",
                "visualizer:",
                "  export_html:",
                "    weighting: all",
                "    values: all",
            ]
        ),
        encoding="utf-8",
    )

    config = Config.from_yaml(config_path)

    assert config.export_html.dashboard.weighting == ["weighted"]
    assert config.export_html.dashboard.values == ["percent"]


def test_export_html_config_rejects_invalid_or_empty_values(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError, match="Unsupported visualizer.export_html.dashboard.weighting"
    ):
        _write_config(
            tmp_path / "invalid",
            export_html_lines=[
                "dashboard:",
                "  weighting:",
                "    - weighted",
                "    - bogus",
            ],
        )


def test_config_rejects_duplicate_dashboard_pages(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError,
        match="visualizer.dashboard_pages contains duplicate page id",
    ):
        _write_config(
            tmp_path,
            dashboard_pages=["overview", "overview"],
        )

    with pytest.raises(
        ValueError,
        match="visualizer.export_html.dashboard.values resolved to no values",
    ):
        _write_config(
            tmp_path / "empty",
            export_html_lines=[
                "dashboard:",
                "  values: []",
            ],
        )

    with pytest.raises(
        ValueError,
        match="visualizer.export_html.pages.destination.purpose resolved to no values",
    ):
        _write_config(
            tmp_path / "empty_page_values",
            export_html_lines=[
                "pages:",
                "  destination:",
                "    purpose: []",
            ],
        )


def _extract_payload(html: str) -> dict:
    start_token = '<script id="activitysim-export-data" type="application/json">'
    start = html.index(start_token) + len(start_token)
    end = html.index("</script>", start)
    return json.loads(html[start:end])


def _walk_nodes(node: dict) -> list[dict]:
    if node.get("kind") == "static_page":
        return _walk_nodes(node["content"])
    if node.get("kind") == "page_variants":
        nodes: list[dict] = [node]
        for variant in node.get("variants", {}).values():
            nodes.extend(_walk_nodes(variant))
        return nodes
    nodes = [node]
    for child in node.get("children", []):
        nodes.extend(_walk_nodes(child))
    for tab in node.get("tabs", []):
        nodes.extend(_walk_nodes(tab["content"]))
    return nodes


def test_build_export_html_document_serializes_dashboard_states_and_pages(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
        ],
    )
    html = build_export_html_document(
        [],
        config,
        summary_runs=[_full_summary_run()],
    )
    payload = _extract_payload(html)

    assert payload["schema_version"] == EXPORT_SCHEMA_VERSION
    assert payload["runs_loaded"] == [{"label": "Base", "color": "#1f77b4"}]
    assert payload["chrome"] == {
        "layout": "left_rail",
        "rail_sections": ["runs_loaded", "display_options"],
        "controls_enabled": {"weighting": True, "values": True},
    }
    assert payload["dashboard_controls"]["weighting"] == ["Weighted", "Unweighted"]
    assert payload["dashboard_controls"]["values"] == ["Percent", "Count"]
    assert payload["default_state"] == {"weighting": "Weighted", "values": "Percent"}
    assert [
        (page["id"], page["title"]) for page in payload["pages"]
    ] == EXPECTED_DEFAULT_PAGES
    assert (
        payload["page_export_support"]["client_side_runtime"]
        == "dashboard-and-page-selectors"
    )
    assert payload["client_runtime"] == EXPORT_CLIENT_RUNTIME
    assert payload["page_export_support"]["enabled_page_selectors"] == [
        {"page_id": "destination", "selector_id": "purpose"},
        {"page_id": "joint_tours", "selector_id": "hh_size"},
        {"page_id": "long_term", "selector_id": "geography"},
        {"page_id": "stop_frequency", "selector_id": "tour_purpose"},
        {"page_id": "stop_location", "selector_id": "purpose"},
        {"page_id": "stop_timing", "selector_id": "purpose"},
        {"page_id": "tour_mode", "selector_id": "purpose"},
        {"page_id": "tour_summary", "selector_id": "person_type"},
        {"page_id": "tour_tod", "selector_id": "purpose"},
        {"page_id": "trip_mode", "selector_id": "tour_mode"},
        {"page_id": "trip_mode", "selector_id": "tour_purpose"},
    ]
    assert sorted(payload["states"]) == [
        "Unweighted||Count",
        "Unweighted||Percent",
        "Weighted||Count",
        "Weighted||Percent",
    ]
    assert "export-layout" in html
    assert "export-rail" in html
    assert "Unsupported export schema version." in html
    assert "Offline export failed to load" in html
    assert "This HTML export encountered a runtime rendering error." in html
    assert "Plotly.react" in html
    assert ">undefined<" not in html

    page_defs = {page["id"]: page for page in payload["pages"]}
    assert page_defs["long_term"]["selectors"] == []
    assert page_defs["tour_summary"]["selectors"][0]["id"] == "person_type"
    assert page_defs["tour_summary"]["selectors"][0]["request_mode"] == "default"
    assert page_defs["tour_summary"]["selectors"][0]["resolved_values"] == ["Total"]
    assert page_defs["tour_summary"]["selectors"][0]["export_enabled"] is True
    assert page_defs["joint_tours"]["selectors"][0]["id"] == "hh_size"
    assert page_defs["joint_tours"]["selectors"][0]["request_mode"] == "default"
    assert page_defs["joint_tours"]["selectors"][0]["resolved_values"] == ["Total"]
    assert page_defs["joint_tours"]["selectors"][0]["export_enabled"] is True
    assert page_defs["destination"]["selectors"][0]["id"] == "purpose"
    assert page_defs["destination"]["selectors"][0]["request_mode"] == "default"
    assert page_defs["destination"]["selectors"][0]["resolved_values"] == ["All NM"]
    assert page_defs["destination"]["selectors"][0]["export_enabled"] is True
    assert page_defs["tour_tod"]["selectors"][0]["id"] == "purpose"
    assert page_defs["tour_tod"]["selectors"][0]["request_mode"] == "default"
    assert page_defs["tour_tod"]["selectors"][0]["resolved_values"] == ["Total"]
    assert page_defs["tour_tod"]["selectors"][0]["export_enabled"] is True
    assert page_defs["tour_mode"]["selectors"][0]["id"] == "purpose"
    assert page_defs["tour_mode"]["selectors"][0]["request_mode"] == "default"
    assert page_defs["tour_mode"]["selectors"][0]["resolved_values"] == ["Total"]
    assert page_defs["tour_mode"]["selectors"][0]["export_enabled"] is True
    assert page_defs["stop_frequency"]["selectors"][0]["id"] == "tour_purpose"
    assert page_defs["stop_frequency"]["selectors"][0]["request_mode"] == "default"
    assert page_defs["stop_frequency"]["selectors"][0]["resolved_values"] == ["Total"]
    assert page_defs["stop_frequency"]["selectors"][0]["export_enabled"] is True
    assert page_defs["stop_timing"]["selectors"][0]["id"] == "purpose"
    assert page_defs["stop_timing"]["selectors"][0]["request_mode"] == "default"
    assert page_defs["stop_timing"]["selectors"][0]["resolved_values"] == ["Total"]
    assert page_defs["stop_timing"]["selectors"][0]["export_enabled"] is True
    assert page_defs["trip_mode"]["selectors"][0]["id"] == "tour_purpose"
    assert page_defs["trip_mode"]["selectors"][0]["request_mode"] == "default"
    assert page_defs["trip_mode"]["selectors"][0]["resolved_values"] == ["Total"]
    assert page_defs["trip_mode"]["selectors"][0]["export_enabled"] is True
    assert page_defs["trip_mode"]["selectors"][1]["id"] == "tour_mode"
    assert page_defs["trip_mode"]["selectors"][1]["request_mode"] == "default"
    assert page_defs["trip_mode"]["selectors"][1]["resolved_values"] == ["All"]
    assert page_defs["trip_mode"]["selectors"][1]["export_enabled"] is True

    weighted_percent = payload["states"]["Weighted||Percent"]
    long_term = weighted_percent["long_term"]
    assert long_term["kind"] == "static_page"
    tour_summary = weighted_percent["tour_summary"]
    assert tour_summary["kind"] == "page_variants"
    assert tour_summary["selector_ids"] == ["person_type"]
    assert tour_summary["default_key"] == '["Total"]'
    assert sorted(tour_summary["variants"]) == ['["Total"]']
    joint_tours = weighted_percent["joint_tours"]
    assert joint_tours["kind"] == "page_variants"
    assert joint_tours["selector_ids"] == ["hh_size"]
    assert joint_tours["default_key"] == '["Total"]'
    assert sorted(joint_tours["variants"]) == ['["Total"]']
    destination = weighted_percent["destination"]
    assert destination["kind"] == "page_variants"
    assert destination["selector_ids"] == ["purpose"]
    assert destination["default_key"] == '["All NM"]'
    assert sorted(destination["variants"]) == ['["All NM"]']
    tour_tod = weighted_percent["tour_tod"]
    assert tour_tod["kind"] == "page_variants"
    assert tour_tod["selector_ids"] == ["purpose"]
    assert tour_tod["default_key"] == '["Total"]'
    assert sorted(tour_tod["variants"]) == ['["Total"]']
    tour_mode = weighted_percent["tour_mode"]
    assert tour_mode["kind"] == "page_variants"
    assert tour_mode["selector_ids"] == ["purpose"]
    assert tour_mode["default_key"] == '["Total"]'
    assert sorted(tour_mode["variants"]) == ['["Total"]']
    stop_frequency = weighted_percent["stop_frequency"]
    assert stop_frequency["kind"] == "page_variants"
    assert stop_frequency["selector_ids"] == ["tour_purpose"]
    assert stop_frequency["default_key"] == '["Total"]'
    assert sorted(stop_frequency["variants"]) == ['["Total"]']
    stop_timing = weighted_percent["stop_timing"]
    assert stop_timing["kind"] == "page_variants"
    assert stop_timing["selector_ids"] == ["purpose"]
    assert stop_timing["default_key"] == '["Total"]'
    assert sorted(stop_timing["variants"]) == ['["Total"]']
    trip_mode = weighted_percent["trip_mode"]
    assert trip_mode["kind"] == "page_variants"
    assert trip_mode["selector_ids"] == ["tour_purpose", "tour_mode"]
    assert trip_mode["default_key"] == '["Total","All"]'
    assert sorted(trip_mode["variants"]) == ['["Total","All"]']
    widget_nodes = [
        node for node in _walk_nodes(tour_summary) if node.get("kind") == "widget"
    ]
    assert widget_nodes
    assert any(
        node.get("selector_id") == "person_type"
        and node.get("export_enabled")
        and not node.get("disabled")
        for node in widget_nodes
    )


def test_build_export_html_document_respects_configured_dashboard_page_subset_and_order(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
            "pages:",
            "  trip_mode: {}",
            "  overview: {}",
            "  destination: {}",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)

    assert [(page["id"], page["title"]) for page in payload["pages"]] == [
        ("trip_mode", "Trip Mode"),
        ("overview", "Overview"),
        ("destination", "Destination"),
    ]
    assert list(payload["states"]["Weighted||Percent"]) == [
        "trip_mode",
        "overview",
        "destination",
    ]


def test_build_export_html_document_defaults_to_registry_order_when_export_pages_are_unset(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        dashboard_pages=["trip_mode", "overview", "destination"],
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)

    assert [
        (page["id"], page["title"]) for page in payload["pages"]
    ] == EXPECTED_DEFAULT_PAGES


def test_build_export_html_document_renders_raw_demo_page_when_raw_runs_are_loaded(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
            "pages:",
            "  raw_trip_demo: {}",
        ],
    )

    html = build_export_html_document([("Base", _raw_trip_run())], config)
    payload = _extract_payload(html)
    raw_demo = payload["states"]["Weighted||Percent"]["raw_trip_demo"]

    assert [(page["id"], page["title"]) for page in payload["pages"]] == [
        ("raw_trip_demo", "Raw Trip Demo")
    ]
    assert raw_demo["kind"] == "static_page"
    variant_nodes = _walk_nodes(raw_demo)
    assert sum(1 for node in variant_nodes if node.get("kind") == "plotly") == 1


def test_build_export_html_document_shows_placeholder_for_raw_demo_without_raw_runs(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  weighting: weighted",
            "  values: percent",
            "pages:",
            "  raw_trip_demo: {}",
        ],
    )
    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    raw_demo = payload["states"]["Weighted||Percent"]["raw_trip_demo"]
    variant_nodes = _walk_nodes(raw_demo)

    assert raw_demo["kind"] == "static_page"
    assert any(
        node.get("kind") == "card" and node.get("title") == "Data Not Available"
        for node in variant_nodes
    )


def test_build_export_html_document_validates_page_selector_requests_against_registry(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
            "pages:",
            "  tour_summary:",
            "    person_type:",
            "      - total",
            "      - worker",
            "  joint_tours:",
            "    hh_size: all",
            "  destination:",
            "    purpose: all",
            "  stop_frequency:",
            "    tour_purpose: all",
            "  stop_timing:",
            "    purpose: all",
            "  tour_tod:",
            "    purpose: all",
            "  tour_mode:",
            "    purpose: all",
            "  trip_mode:",
            "    tour_purpose: all",
            "    tour_mode: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    page_defs = {page["id"]: page for page in payload["pages"]}

    assert page_defs["tour_summary"]["selectors"][0]["request_mode"] == "explicit"
    assert page_defs["tour_summary"]["selectors"][0]["resolved_values"] == [
        "Total",
        "worker",
    ]
    assert page_defs["tour_summary"]["selectors"][0]["export_enabled"] is True
    assert page_defs["joint_tours"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["joint_tours"]["selectors"][0]["resolved_values"] == [
        "Total",
        "2",
        "3",
        "4",
        "5",
    ]
    assert page_defs["joint_tours"]["selectors"][0]["export_enabled"] is True
    assert page_defs["destination"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["destination"]["selectors"][0]["resolved_values"] == [
        "All NM",
        "eatout",
        "social",
    ]
    assert page_defs["destination"]["selectors"][0]["export_enabled"] is True
    assert page_defs["stop_frequency"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["stop_frequency"]["selectors"][0]["resolved_values"] == [
        "Total",
        "eatout",
        "social",
    ]
    assert page_defs["stop_frequency"]["selectors"][0]["export_enabled"] is True
    assert page_defs["stop_timing"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["stop_timing"]["selectors"][0]["resolved_values"] == [
        "Total",
        "eatout",
        "social",
    ]
    assert page_defs["stop_timing"]["selectors"][0]["export_enabled"] is True
    assert page_defs["tour_tod"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["tour_tod"]["selectors"][0]["resolved_values"] == [
        "Total",
        "work",
    ]
    assert page_defs["tour_tod"]["selectors"][0]["export_enabled"] is True
    assert page_defs["tour_mode"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["tour_mode"]["selectors"][0]["resolved_values"] == [
        "Total",
        "work",
    ]
    assert page_defs["tour_mode"]["selectors"][0]["export_enabled"] is True
    assert page_defs["trip_mode"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["trip_mode"]["selectors"][0]["resolved_values"] == [
        "Total",
        "eatout",
        "social",
    ]
    assert page_defs["trip_mode"]["selectors"][0]["export_enabled"] is True
    assert page_defs["trip_mode"]["selectors"][1]["request_mode"] == "all"
    assert page_defs["trip_mode"]["selectors"][1]["resolved_values"] == [
        "All",
        "DRIVE",
        "WALK",
    ]
    assert page_defs["trip_mode"]["selectors"][1]["export_enabled"] is True

    weighted_percent = payload["states"]["Weighted||Percent"]["tour_summary"]
    assert weighted_percent["kind"] == "page_variants"
    assert sorted(weighted_percent["variants"]) == [
        '["Total"]',
        '["worker"]',
    ]
    joint_tours_weighted_percent = payload["states"]["Weighted||Percent"]["joint_tours"]
    assert joint_tours_weighted_percent["kind"] == "page_variants"
    assert sorted(joint_tours_weighted_percent["variants"]) == [
        '["2"]',
        '["3"]',
        '["4"]',
        '["5"]',
        '["Total"]',
    ]
    destination_weighted_percent = payload["states"]["Weighted||Percent"]["destination"]
    assert destination_weighted_percent["kind"] == "page_variants"
    assert sorted(destination_weighted_percent["variants"]) == [
        '["All NM"]',
        '["eatout"]',
        '["social"]',
    ]
    stop_frequency_weighted_percent = payload["states"]["Weighted||Percent"][
        "stop_frequency"
    ]
    assert stop_frequency_weighted_percent["kind"] == "page_variants"
    assert sorted(stop_frequency_weighted_percent["variants"]) == [
        '["Total"]',
        '["eatout"]',
        '["social"]',
    ]
    stop_timing_weighted_percent = payload["states"]["Weighted||Percent"]["stop_timing"]
    assert stop_timing_weighted_percent["kind"] == "page_variants"
    assert sorted(stop_timing_weighted_percent["variants"]) == [
        '["Total"]',
        '["eatout"]',
        '["social"]',
    ]
    tour_tod_weighted_percent = payload["states"]["Weighted||Percent"]["tour_tod"]
    assert tour_tod_weighted_percent["kind"] == "page_variants"
    assert sorted(tour_tod_weighted_percent["variants"]) == [
        '["Total"]',
        '["work"]',
    ]
    tour_mode_weighted_percent = payload["states"]["Weighted||Percent"]["tour_mode"]
    assert tour_mode_weighted_percent["kind"] == "page_variants"
    assert sorted(tour_mode_weighted_percent["variants"]) == [
        '["Total"]',
        '["work"]',
    ]
    trip_mode_weighted_percent = payload["states"]["Weighted||Percent"]["trip_mode"]
    assert trip_mode_weighted_percent["kind"] == "page_variants"
    assert sorted(trip_mode_weighted_percent["variants"]) == [
        '["Total","All"]',
        '["Total","DRIVE"]',
        '["Total","WALK"]',
        '["eatout","All"]',
        '["eatout","DRIVE"]',
        '["eatout","WALK"]',
        '["social","All"]',
        '["social","DRIVE"]',
        '["social","WALK"]',
    ]


def test_build_export_html_document_keeps_grouped_tour_mode_chart_when_mode_groups_enabled(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        modes_lines=[
            "groups:",
            "  Auto:",
            "    - DRIVE",
            "  Active:",
            "    - WALK",
        ],
        export_html_lines=[
            "pages:",
            "  tour_mode:",
            "    purpose: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    tour_mode = payload["states"]["Weighted||Percent"]["tour_mode"]

    assert tour_mode["kind"] == "page_variants"
    assert sorted(tour_mode["variants"]) == [
        '["Total"]',
        '["work"]',
    ]
    variant_nodes = _walk_nodes(tour_mode["variants"]['["Total"]'])
    assert sum(1 for node in variant_nodes if node.get("kind") == "plotly") == 5
    assert any(
        node.get("kind") == "html" and "Grouped Mode Summary" in node.get("html", "")
        for node in variant_nodes
    )


def test_build_export_html_document_serializes_long_term_geography_variants(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        geography_lines=[
            "enabled: true",
            "landuse_col: district",
        ],
        export_html_lines=[
            "pages:",
            "  long_term:",
            "    geography: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    page_defs = {page["id"]: page for page in payload["pages"]}

    assert page_defs["long_term"]["selectors"][0]["id"] == "geography"
    assert page_defs["long_term"]["selectors"][0]["request_mode"] == "all"
    assert page_defs["long_term"]["selectors"][0]["resolved_values"] == [
        "Total",
        "Suburban",
        "Urban",
    ]
    assert page_defs["long_term"]["selectors"][0]["export_enabled"] is True

    long_term = payload["states"]["Weighted||Percent"]["long_term"]
    assert long_term["kind"] == "page_variants"
    assert long_term["selector_ids"] == ["geography"]
    assert long_term["default_key"] == '["Total"]'
    assert sorted(long_term["variants"]) == [
        '["Suburban"]',
        '["Total"]',
        '["Urban"]',
    ]
    variant_nodes = _walk_nodes(long_term["variants"]['["Urban"]'])
    assert sum(1 for node in variant_nodes if node.get("kind") == "plotly") == 6
    assert sum(1 for node in variant_nodes if node.get("kind") == "table") == 2


def test_build_export_html_document_warns_and_falls_back_when_long_term_geography_is_unavailable(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "pages:",
            "  long_term:",
            "    geography: all",
        ],
    )
    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    page_defs = {page["id"]: page for page in payload["pages"]}

    assert page_defs["long_term"]["selectors"] == []
    assert payload["states"]["Weighted||Percent"]["long_term"]["kind"] == "static_page"


def test_build_export_html_document_serializes_stop_frequency_four_chart_variant(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "pages:",
            "  stop_frequency:",
            "    tour_purpose: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    stop_frequency = payload["states"]["Weighted||Percent"]["stop_frequency"]

    assert stop_frequency["kind"] == "page_variants"
    assert sorted(stop_frequency["variants"]) == [
        '["Total"]',
        '["eatout"]',
        '["social"]',
    ]
    variant_nodes = _walk_nodes(stop_frequency["variants"]['["eatout"]'])
    assert sum(1 for node in variant_nodes if node.get("kind") == "plotly") == 4


def test_build_export_html_document_serializes_stop_timing_two_chart_variant(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "pages:",
            "  stop_timing:",
            "    purpose: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    stop_timing = payload["states"]["Weighted||Percent"]["stop_timing"]

    assert stop_timing["kind"] == "page_variants"
    assert sorted(stop_timing["variants"]) == [
        '["Total"]',
        '["eatout"]',
        '["social"]',
    ]
    variant_nodes = _walk_nodes(stop_timing["variants"]['["Total"]'])
    assert sum(1 for node in variant_nodes if node.get("kind") == "plotly") == 2


def test_build_export_html_document_serializes_joint_tours_hh_size_variants(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "pages:",
            "  joint_tours:",
            "    hh_size: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    joint_tours = payload["states"]["Weighted||Percent"]["joint_tours"]

    assert joint_tours["kind"] == "page_variants"
    assert sorted(joint_tours["variants"]) == [
        '["2"]',
        '["3"]',
        '["4"]',
        '["5"]',
        '["Total"]',
    ]
    variant_nodes = _walk_nodes(joint_tours["variants"]['["2"]'])
    assert sum(1 for node in variant_nodes if node.get("kind") == "plotly") == 4


def test_build_export_html_document_serializes_trip_mode_tour_purpose_variants(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "pages:",
            "  trip_mode:",
            "    tour_purpose: all",
            "    tour_mode: all",
        ],
    )

    html = build_export_html_document([], config, summary_runs=[_full_summary_run()])
    payload = _extract_payload(html)
    trip_mode = payload["states"]["Weighted||Percent"]["trip_mode"]

    assert trip_mode["kind"] == "page_variants"
    assert trip_mode["selector_ids"] == ["tour_purpose", "tour_mode"]
    assert sorted(trip_mode["variants"]) == [
        '["Total","All"]',
        '["Total","DRIVE"]',
        '["Total","WALK"]',
        '["eatout","All"]',
        '["eatout","DRIVE"]',
        '["eatout","WALK"]',
        '["social","All"]',
        '["social","DRIVE"]',
        '["social","WALK"]',
    ]
    variant_nodes = _walk_nodes(trip_mode["variants"]['["eatout","DRIVE"]'])
    assert sum(1 for node in variant_nodes if node.get("kind") == "plotly") == 1
    widget_nodes = [node for node in variant_nodes if node.get("kind") == "widget"]
    assert any(
        node.get("selector_id") == "tour_purpose"
        and node.get("export_enabled")
        and not node.get("disabled")
        for node in widget_nodes
    )
    assert any(
        node.get("selector_id") == "tour_mode"
        and node.get("export_enabled")
        and not node.get("disabled")
        for node in widget_nodes
    )


def test_build_export_html_document_rejects_unknown_page_and_selector_ids(
    tmp_path: Path,
) -> None:
    bad_page_config = _write_config(
        tmp_path / "bad_page",
        export_html_lines=[
            "pages:",
            "  unknown_page:",
            "    purpose: all",
        ],
    )
    with pytest.raises(
        ValueError, match="Unsupported visualizer.export_html.pages entries"
    ):
        build_export_html_document(
            [], bad_page_config, summary_runs=[_full_summary_run()]
        )

    bad_selector_config = _write_config(
        tmp_path / "bad_selector",
        export_html_lines=[
            "pages:",
            "  destination:",
            "    unknown_selector: all",
        ],
    )
    with pytest.raises(
        ValueError,
        match="Unsupported visualizer.export_html.pages.destination entries",
    ):
        build_export_html_document(
            [],
            bad_selector_config,
            summary_runs=[_full_summary_run()],
        )


def test_export_html_save_writes_single_client_side_html_file(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
        ],
    )
    out_dir = tmp_path / "html_export"
    out_dir.mkdir()
    out_path = out_dir / "dashboard.html"

    write_export_html_document(
        out_path,
        [],
        config,
        summary_runs=[_full_summary_run()],
    )

    assert out_path.exists()
    assert sorted(path.name for path in out_dir.iterdir()) == ["dashboard.html"]

    html = out_path.read_text(encoding="utf-8")
    assert "Weighting" in html
    assert "Unweighted" in html
    assert "Count" in html
    assert "activitysim-export-data" in html
    assert "Plotly.react" in html
    assert "export-layout" in html
    assert "Runs Loaded" in html
    assert "Tour Purpose" in html
    assert "panel.models.state.State" not in html
