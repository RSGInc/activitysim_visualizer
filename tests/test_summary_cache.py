from __future__ import annotations

from pathlib import Path
import sys

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.live_pages import DestinationPage
from dashboard.state import DashboardState
from summarize.cache import (
    build_run_keys,
    create_summary_run,
    load_summary_run_cache,
    write_summary_run_cache,
)
from summarize.reader import Config


def _write_config(tmp_path: Path) -> Config:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "Test Config"',
                'dashboard_title: "Test Dashboard"',
                "runs: []",
                "outputs:",
                "  summary_root: summary_cache",
                "  weighting_modes:",
                "    - weighted",
                "    - unweighted",
            ]
        ),
        encoding="utf-8",
    )
    return Config.from_yaml(config_path)


def _sample_summary_run() -> object:
    weighted = {
        "destination_distance": pl.DataFrame(
            {
                "purpose": ["All NM", "All NM", "shopping", "shopping"],
                "distbin": [0, 1, 0, 1],
                "freq": [5.0, 7.5, 2.0, 4.0],
            }
        ),
        "destination_average_distance": pl.DataFrame(
            {
                "purpose": ["shopping"],
                "avg_distance": [3.25],
            }
        ),
        "geo_flows": pl.DataFrame(),
    }
    unweighted = {
        "destination_distance": pl.DataFrame(
            {
                "purpose": ["All NM", "All NM", "shopping", "shopping"],
                "distbin": [0, 1, 0, 1],
                "freq": [2.0, 3.0, 1.0, 2.0],
            }
        ),
        "destination_average_distance": pl.DataFrame(
            {
                "purpose": ["shopping"],
                "avg_distance": [2.5],
            }
        ),
        "geo_flows": pl.DataFrame(),
    }
    return create_summary_run(
        label="Base",
        run_key="base",
        summaries_by_mode={
            "weighted": weighted,
            "unweighted": unweighted,
        },
        source_run_dir=str(Path("C:/runs/base")),
    )


def test_build_run_keys_handles_case_insensitive_collisions() -> None:
    assert build_run_keys(["Base", "base", "Build"]) == ["base-1", "base-2", "build"]


def test_summary_cache_round_trip_creates_configured_layout(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    summary_run = _sample_summary_run()
    fingerprint = {"label": "Base", "run_dir": "C:/runs/base"}

    cache_dir = write_summary_run_cache(
        summary_run,
        config,
        run_fingerprint=fingerprint,
    )

    assert cache_dir == Path(config.summary_root) / "base"
    assert cache_dir.exists()
    assert (cache_dir / "manifest.json").exists()
    assert (cache_dir / "weighted" / "destinationDistByPurpose.csv").exists()
    assert (cache_dir / "unweighted" / "destinationAvgDistance.csv").exists()

    loaded = load_summary_run_cache(
        cache_dir,
        config,
        expected_modes=config.weighting_modes,
        expected_summary_ids=["destination_distance", "destination_average_distance", "geo_flows"],
        expected_config_digest=config.config_digest,
        expected_run_fingerprint=fingerprint,
        expected_label="Base",
        expected_run_key="base",
    )

    assert loaded.label == "Base"
    assert loaded.run_key == "base"
    assert loaded.summaries_by_mode["weighted"]["destination_distance"].to_dicts() == [
        {"purpose": "All NM", "distbin": 0, "freq": 5.0},
        {"purpose": "All NM", "distbin": 1, "freq": 7.5},
        {"purpose": "shopping", "distbin": 0, "freq": 2.0},
        {"purpose": "shopping", "distbin": 1, "freq": 4.0},
    ]
    assert loaded.summaries_by_mode["weighted"]["geo_flows"].width == 0


def test_destination_page_can_render_from_cached_summaries_only(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    summary_run = _sample_summary_run()
    state = DashboardState(
        runs=[],
        summary_runs=[summary_run],
        weighting_modes=config.weighting_modes,
    )

    page = DestinationPage(state, config)
    page.refresh(force=True)

    assert list(page.purp_sel.options) == ["All NM", "shopping"]
    assert page._body.objects
