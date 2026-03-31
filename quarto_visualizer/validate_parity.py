"""Phase 6 parity validation against the frozen Panel reference bundle."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import io
import json
from pathlib import Path
import sys
from typing import Callable

import polars as pl

from quarto_visualizer.app_state import find_config_path, load_app_state
from quarto_visualizer.panel_reference import build_reference_summaries
from quarto_visualizer.quarto_shell import (
    destination_purpose_choices,
    long_term_geo_choices,
    stop_frequency_purpose_choices,
    stop_location_purpose_choices,
    stop_timing_purpose_choices,
    tour_mode_purpose_choices,
    tour_summary_ptype_values,
    tour_tod_purpose_choices,
    trip_mode_purpose_choices,
    trip_mode_tour_mode_choices,
)
from quarto_visualizer.summary_bundle import PreparedRuns, RunFrameList, SummaryBundle, strip_weights


@dataclass(frozen=True)
class ValidationResult:
    category: str
    name: str
    passed: bool
    detail: str


BundleExtractor = Callable[[SummaryBundle, str], pl.DataFrame]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="activitysim-viz-validate-parity",
        description="Validate the Quarto migration against the frozen Panel reference bundle.",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=None,
        help="Path to config.yaml (default: auto-discover config.yaml)",
    )
    parser.add_argument(
        "--reference-dir",
        default="artifacts/panel_reference",
        help="Directory containing the frozen Panel reference bundle",
    )
    parser.add_argument(
        "--report-markdown",
        default=None,
        help="Optional path to write a markdown validation report",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = find_config_path(args.config) if args.config else find_config_path()
    reference_dir = Path(args.reference_dir).resolve()
    manifest_path = reference_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"Error: missing reference manifest at {manifest_path}", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    state = load_app_state(config_path)
    dashboard_qmd = Path(__file__).resolve().parents[1] / "quarto" / "dashboard.qmd"

    results: list[ValidationResult] = []
    results.extend(validate_manifest_alignment(manifest, state.runs))
    results.extend(validate_reference_replay(manifest, reference_dir, state.runs, state.config))
    results.extend(validate_bundle_projection(manifest, reference_dir, state.bundles.weighted, state.bundles.unweighted))
    results.extend(validate_selector_behaviors(manifest, reference_dir, state))
    results.extend(validate_dashboard_structure(dashboard_qmd, state.config.geography_enabled))

    report = render_markdown_report(
        results=results,
        manifest=manifest,
        config_path=config_path,
        reference_dir=reference_dir,
    )
    print(report)

    if args.report_markdown:
        report_path = Path(args.report_markdown)
        report_path.write_text(report, encoding="utf-8")
        print(f"\n[validate-parity] Wrote markdown report to {report_path.resolve()}")

    failed = [result for result in results if not result.passed]
    if failed:
        print(f"\n[validate-parity] {len(failed)} checks failed.", file=sys.stderr)
        sys.exit(1)

    print(f"\n[validate-parity] All {len(results)} checks passed.")


def validate_manifest_alignment(manifest: dict, runs: PreparedRuns) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    manifest_runs = manifest.get("runs", [])
    results.append(
        ValidationResult(
            category="manifest",
            name="run_count",
            passed=len(manifest_runs) == len(runs),
            detail=f"manifest={len(manifest_runs)} current={len(runs)}",
        )
    )
    for idx, ((label, rd), manifest_entry) in enumerate(zip(runs, manifest_runs, strict=False), start=1):
        results.append(
            ValidationResult(
                category="manifest",
                name=f"run_{idx}_label",
                passed=label == manifest_entry.get("label"),
                detail=f"current={label!r} manifest={manifest_entry.get('label')!r}",
            )
        )
        results.append(
            ValidationResult(
                category="manifest",
                name=f"run_{idx}_dir",
                passed=str(rd.run_dir) == str(manifest_entry.get("run_dir")),
                detail=f"current={rd.run_dir!r} manifest={manifest_entry.get('run_dir')!r}",
            )
        )
    return results


def validate_reference_replay(
    manifest: dict,
    reference_dir: Path,
    runs: PreparedRuns,
    config,
) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    modes = tuple(manifest.get("modes", []))
    for (label, rd), manifest_entry in zip(runs, manifest.get("runs", []), strict=False):
        run_dir = reference_dir / manifest_entry["artifact_dir"]
        for mode in modes:
            mode_rd = rd if mode == "weighted" else strip_weights(rd)
            summaries = build_reference_summaries(mode_rd, config)
            for summary_name, df in summaries.items():
                ref_path = run_dir / mode / f"{summary_name}.csv"
                passed, detail = compare_df_to_reference(df, ref_path)
                results.append(
                    ValidationResult(
                        category="reference-replay",
                        name=f"{label}/{mode}/{summary_name}",
                        passed=passed,
                        detail=detail,
                    )
                )
    return results


def validate_bundle_projection(
    manifest: dict,
    reference_dir: Path,
    weighted_bundle: SummaryBundle,
    unweighted_bundle: SummaryBundle,
) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    bundle_map: dict[str, BundleExtractor] = {
        "autoOwnership": lambda b, label: run_frame(b.long_term.auto_ownership, label),
        "pertypeDistbn": lambda b, label: run_frame(b.overview.person_type, label),
        "hhSizeDist": lambda b, label: run_frame(b.overview.hh_size, label),
        "workTLFD": lambda b, label: run_tlfd(b.long_term.tlfd, label, "work"),
        "univTLFD": lambda b, label: run_tlfd(b.long_term.tlfd, label, "univ"),
        "schlTLFD": lambda b, label: run_tlfd(b.long_term.tlfd, label, "schl"),
        "mandTourLengths": lambda b, label: run_frame(b.long_term.mandatory_tour_lengths, label),
        "wfh_summary": lambda b, label: run_frame(b.long_term.wfh, label),
        "telecommuteFrequency": lambda b, label: run_frame(b.long_term.telecommute, label),
        "geoFlows": lambda b, label: run_frame(b.long_term.geo_flows, label),
        "dapSummary_vis": lambda b, label: run_frame(b.tour_summary.dap, label),
        "mtfSummary_vis": lambda b, label: run_frame(b.tour_summary.mandatory_tour_frequency, label),
        "inmSummary_vis": lambda b, label: run_frame(b.tour_summary.individual_nm, label),
        "jtf": lambda b, label: run_frame(b.joint_tours.joint_tour_frequency, label),
        "jointComp": lambda b, label: run_frame(b.joint_tours.composition, label),
        "jointPartySize": lambda b, label: run_frame(b.joint_tours.party_size, label),
        "jointToursHHSize": lambda b, label: run_frame(b.joint_tours.household_size, label),
        "tmodeProfile_vis": lambda b, label: run_frame(b.tour_mode.detail, label),
        "todProfile_vis": lambda b, label: run_frame(b.tour_tod.profiles, label),
        "tripModeProfile_vis": lambda b, label: run_frame(b.trip_mode.profiles, label),
        "stopFreq": lambda b, label: run_frame(b.stop_freq.stop_frequency, label),
        "stopPurpose": lambda b, label: run_frame(b.stop_freq.stop_purpose, label),
        "stopLocation": lambda b, label: run_frame(b.stop_location.profiles, label),
        "stopTiming": lambda b, label: run_frame(b.stop_timing.profiles, label),
        "totals": lambda b, label: run_frame(b.overview.totals, label),
    }
    bundle_by_mode = {"weighted": weighted_bundle, "unweighted": unweighted_bundle}

    for manifest_entry in manifest.get("runs", []):
        label = manifest_entry["label"]
        run_dir = reference_dir / manifest_entry["artifact_dir"]
        for mode, bundle in bundle_by_mode.items():
            for summary_name, extractor in bundle_map.items():
                ref_path = run_dir / mode / f"{summary_name}.csv"
                passed, detail = compare_df_to_reference(extractor(bundle, label), ref_path)
                results.append(
                    ValidationResult(
                        category="bundle-projection",
                        name=f"{label}/{mode}/{summary_name}",
                        passed=passed,
                        detail=detail,
                    )
                )

    results.append(
        ValidationResult(
            category="bundle-projection",
            name="nm_tour_rates_bundle_scope",
            passed=True,
            detail="`nm_tour_rates` remains part of the frozen reference bundle but is intentionally not surfaced in SummaryBundle because no current page consumes it.",
        )
    )
    return results


def validate_selector_behaviors(manifest: dict, reference_dir: Path, state) -> list[ValidationResult]:
    weighted = state.bundles.weighted
    results: list[ValidationResult] = []

    expected_geo = expected_long_term_geo_choices(manifest, reference_dir)
    results.append(check_tuple("selectors", "long_term_geo_choices", long_term_geo_choices(weighted), expected_geo))

    expected_ptypes = expected_unique_values(reference_dir, manifest, "weighted", "dapSummary_vis.csv", "ptype")
    results.append(check_tuple("selectors", "tour_summary_ptype_values", tour_summary_ptype_values(weighted), expected_ptypes))

    expected_destination = expected_destination_purposes_from_runs(state.runs)
    results.append(check_tuple("selectors", "destination_purpose_choices", destination_purpose_choices(weighted), expected_destination))

    expected_tour_tod = expected_tour_tod_purpose_choices(reference_dir, manifest)
    results.append(check_tuple("selectors", "tour_tod_purpose_choices", tour_tod_purpose_choices(weighted), expected_tour_tod))

    expected_tour_mode = expected_union_values(reference_dir, manifest, "weighted", "tmodeProfile_vis.csv", "purpose", prefix="Total")
    results.append(check_tuple("selectors", "tour_mode_purpose_choices", tour_mode_purpose_choices(weighted), expected_tour_mode))

    expected_stop_freq = expected_first_run_values(reference_dir, manifest, "weighted", "stopFreq.csv", "primary_purpose", prefix="Total")
    results.append(check_tuple("selectors", "stop_frequency_purpose_choices", stop_frequency_purpose_choices(weighted), expected_stop_freq))

    expected_stop_loc = expected_unique_values(reference_dir, manifest, "weighted", "stopLocation.csv", "primary_purpose")
    results.append(check_tuple("selectors", "stop_location_purpose_choices", stop_location_purpose_choices(weighted), expected_stop_loc))

    expected_stop_timing = tuple(v for v in expected_unique_values(reference_dir, manifest, "weighted", "stopTiming.csv", "primary_purpose") if v != "Total")
    results.append(check_tuple("selectors", "stop_timing_purpose_choices", stop_timing_purpose_choices(weighted), expected_stop_timing))

    expected_trip_purpose = expected_first_run_values(reference_dir, manifest, "weighted", "tripModeProfile_vis.csv", "primary_purpose", prefix="Total")
    results.append(check_tuple("selectors", "trip_mode_purpose_choices", trip_mode_purpose_choices(weighted), expected_trip_purpose))

    expected_trip_tour_mode = expected_first_run_values(reference_dir, manifest, "weighted", "tripModeProfile_vis.csv", "tour_mode", prefix="All")
    results.append(check_tuple("selectors", "trip_mode_tour_mode_choices", trip_mode_tour_mode_choices(weighted), expected_trip_tour_mode))
    return results


def validate_dashboard_structure(dashboard_qmd: Path, geography_enabled: bool) -> list[ValidationResult]:
    text = dashboard_qmd.read_text(encoding="utf-8")
    results: list[ValidationResult] = []

    page_order = [
        "Overview",
        "Long-Term",
        "Tour Summary",
        "Joint Tours",
        "Destination",
        "Tour TOD",
        "Tour Mode",
        "Stop Frequency",
        "Stop Location",
        "Stop Timing",
        "Trip Mode",
    ]
    positions = [text.find(f"# {page}") for page in page_order]
    results.append(
        ValidationResult(
            category="dashboard-structure",
            name="page_order",
            passed=all(pos >= 0 for pos in positions) and positions == sorted(positions),
            detail=str(dict(zip(page_order, positions, strict=True))),
        )
    )

    required_ids = [
        "weight_mode",
        "value_mode",
        "tour_summary_ptype",
        "joint_tours_hhsize",
        "destination_purpose",
        "tour_tod_purpose",
        "tour_mode_purpose",
        "stop_freq_purpose",
        "stop_timing_purpose",
        "trip_mode_purpose",
        "trip_mode_tour_mode",
    ]
    if geography_enabled:
        required_ids.append("long_term_geo")
    missing = [item for item in required_ids if f'"{item}"' not in text]
    results.append(
        ValidationResult(
            category="dashboard-structure",
            name="required_input_ids",
            passed=not missing,
            detail="missing=" + (", ".join(missing) if missing else "none"),
        )
    )

    results.append(
        ValidationResult(
            category="dashboard-structure",
            name="stop_location_has_no_selector",
            passed='ui.input_select(\n    "stop_location' not in text and 'ui.input_select("stop_location' not in text,
            detail="No stop-location-specific input selector found in dashboard.qmd",
        )
    )
    return results


def expected_long_term_geo_choices(manifest: dict, reference_dir: Path) -> tuple[str, ...]:
    if not manifest.get("runs"):
        return ("Total",)
    first_run_dir = reference_dir / manifest["runs"][0]["artifact_dir"] / "weighted" / "workTLFD.csv"
    df = pl.read_csv(first_run_dir)
    choices = [column for column in df.columns if column not in ("distbin", "Total")]
    return tuple(["Total", *choices]) if choices else ("Total",)


def expected_tour_tod_purpose_choices(reference_dir: Path, manifest: dict) -> tuple[str, ...]:
    for run_entry in manifest.get("runs", []):
        df = pl.read_csv(reference_dir / run_entry["artifact_dir"] / "weighted" / "todProfile_vis.csv")
        if len(df) > 0 and "purpose" in df.columns:
            values = sorted(str(v) for v in df["purpose"].drop_nulls().cast(pl.Utf8).unique().to_list())
            return tuple(["Total", *[v for v in values if v != "Total"]]) if values else ("work",)
    return ("work",)


def expected_first_run_values(
    reference_dir: Path,
    manifest: dict,
    mode: str,
    filename: str,
    column: str,
    *,
    prefix: str | None = None,
) -> tuple[str, ...]:
    for run_entry in manifest.get("runs", []):
        df = pl.read_csv(reference_dir / run_entry["artifact_dir"] / mode / filename)
        if len(df) > 0 and column in df.columns:
            values = sorted(str(v) for v in df[column].drop_nulls().cast(pl.Utf8).unique().to_list())
            if prefix is None:
                return tuple(values)
            return tuple([prefix, *[v for v in values if v != prefix]]) if values else (prefix,)
    return (prefix,) if prefix else tuple()


def expected_unique_values(
    reference_dir: Path,
    manifest: dict,
    mode: str,
    filename: str,
    column: str,
) -> tuple[str, ...]:
    return expected_first_run_values(reference_dir, manifest, mode, filename, column, prefix=None)


def expected_union_values(
    reference_dir: Path,
    manifest: dict,
    mode: str,
    filename: str,
    column: str,
    *,
    prefix: str | None = None,
) -> tuple[str, ...]:
    values: set[str] = set()
    for run_entry in manifest.get("runs", []):
        df = pl.read_csv(reference_dir / run_entry["artifact_dir"] / mode / filename)
        if len(df) > 0 and column in df.columns:
            values.update(str(v) for v in df[column].drop_nulls().cast(pl.Utf8).unique().to_list())
    ordered = tuple(sorted(values))
    if prefix is None:
        return ordered
    return tuple([prefix, *[v for v in ordered if v != prefix]]) if ordered else (prefix,)


def expected_destination_purposes_from_runs(runs: PreparedRuns) -> tuple[str, ...]:
    if not runs:
        return ("All NM",)
    _, rd = runs[0]
    tours_df = rd.tours
    if "tour_category" in tours_df.columns and "primary_purpose" in tours_df.columns:
        nm_tours = tours_df.filter(pl.col("tour_category").is_in(["non-mandatory", "atwork", "joint"]))
        purposes = sorted(str(value) for value in nm_tours["primary_purpose"].drop_nulls().unique().to_list())
        return tuple(["All NM", *purposes]) if purposes else ("All NM",)
    return ("All NM",)


def compare_df_to_reference(df: pl.DataFrame, reference_path: Path) -> tuple[bool, str]:
    if not reference_path.exists():
        return False, f"missing reference file: {reference_path}"
    current_csv = normalize_csv_text(df.write_csv())
    reference_csv = normalize_csv_text(reference_path.read_text(encoding="utf-8"))
    if current_csv == reference_csv:
        return True, "exact csv match"

    current_df = pl.read_csv(io.StringIO(current_csv)) if current_csv.strip() else pl.DataFrame()
    reference_df = pl.read_csv(reference_path) if reference_csv.strip() else pl.DataFrame()
    if current_df.columns == reference_df.columns and current_df.shape == reference_df.shape:
        sort_cols = list(current_df.columns)
        if current_df.sort(sort_cols).equals(reference_df.sort(sort_cols)):
            return True, "match after row-order normalization"

    return (
        False,
        "csv mismatch "
        f"ref_shape={reference_df.shape} cur_shape={current_df.shape} "
        f"ref_cols={reference_df.columns} cur_cols={current_df.columns}",
    )


def normalize_csv_text(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


def run_frame(frames: RunFrameList, label: str) -> pl.DataFrame:
    for run_label, df in frames:
        if run_label == label:
            return df
    raise KeyError(f"Could not find run label {label!r}")


def run_tlfd(frames, label: str, series: str) -> pl.DataFrame:
    for run_label, tlfd_map in frames:
        if run_label == label:
            return tlfd_map.get(series, pl.DataFrame())
    raise KeyError(f"Could not find run label {label!r}")


def check_tuple(category: str, name: str, actual: tuple[str, ...], expected: tuple[str, ...]) -> ValidationResult:
    return ValidationResult(
        category=category,
        name=name,
        passed=tuple(actual) == tuple(expected),
        detail=f"actual={actual} expected={expected}",
    )


def render_markdown_report(
    *,
    results: list[ValidationResult],
    manifest: dict,
    config_path: Path,
    reference_dir: Path,
) -> str:
    category_totals: dict[str, tuple[int, int]] = {}
    for category in {result.category for result in results}:
        cat_results = [result for result in results if result.category == category]
        category_totals[category] = (sum(1 for result in cat_results if result.passed), len(cat_results))

    failed = [result for result in results if not result.passed]
    lines = [
        "# Phase 6 Validation Report",
        "",
        f"- Config: `{config_path}`",
        f"- Reference bundle: `{reference_dir}`",
        f"- Runs: {manifest.get('run_count', 0)}",
        f"- Modes: {', '.join(manifest.get('modes', []))}",
        "",
        "## Summary",
        "",
    ]
    for category in sorted(category_totals):
        passed, total = category_totals[category]
        lines.append(f"- `{category}`: {passed}/{total} checks passed")

    if failed:
        lines.extend(["", "## Failures", ""])
        for result in failed:
            lines.append(f"- `{result.category} / {result.name}`: {result.detail}")
    else:
        lines.extend(["", "## Result", "", "- All recorded parity checks passed."])

    lines.extend(
        [
            "",
            "## Remaining Manual Follow-Up",
            "",
            "- Static export behavior remains a manual UI check; the validator does not assert disabled controls in rendered HTML.",
            "- Geography-enabled, mode-group-enabled, and 24-bin timing scenarios still need config/data coverage beyond the current default reference bundle.",
            "- Percent vs Count visual behavior is preserved in code, but still benefits from an explicit interactive smoke test because many density charts intentionally stay normalized.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
