"""ActivitySim Visualizer - CLI entry point."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="activitysim-viz",
        description="Panel-based ActivitySim comparison visualizer",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=str(Path(__file__).parent / "config.yaml"),
        help="Path to config.yaml (default: config.yaml next to run.py)",
    )
    parser.add_argument(
        "--run",
        nargs=2,
        action="append",
        metavar=("DIR", "LABEL"),
        dest="cli_runs",
        help="Add a run: --run /path/to/dir 'My Label' (repeatable; overrides config runs)",
    )
    parser.add_argument(
        "--run-skim",
        nargs="+",
        metavar="SKIM_PATH",
        dest="cli_run_skims",
        help="Skim file for each --run entry (in order); use '' or 'null' for global default",
    )
    parser.add_argument(
        "--write-csvs",
        action="store_true",
        help="Refresh and write summary CSV caches to the configured summary root",
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Skip the dashboard (only write CSVs; requires --write-csvs)",
    )
    parser.add_argument(
        "--from-csvs",
        nargs="*",
        metavar="CSV_DIR",
        help="Load pre-computed summary CSVs from directories instead of raw run outputs",
    )
    parser.add_argument(
        "--skip-summary-cache-write",
        action="store_true",
        help="Do not write missing or stale summary caches during normal runs",
    )
    parser.add_argument(
        "--export-html",
        metavar="PATH",
        help="Export dashboard to a self-contained HTML file and exit",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5006,
        help="Port to serve the dashboard on (default: 5006)",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Do not open the dashboard in a browser automatically",
    )
    return parser.parse_args()


def main() -> None:
    t0 = time.perf_counter()
    args = parse_args()
    print("[main] Starting ActivitySim Visualizer")

    if args.no_dashboard and not args.write_csvs:
        print("Error: --no-dashboard requires --write-csvs.", file=sys.stderr)
        sys.exit(1)
    if args.from_csvs is not None and args.write_csvs:
        print(
            "Error: --from-csvs cannot be combined with --write-csvs.", file=sys.stderr
        )
        sys.exit(1)

    from summarize.cache import (
        DEFAULT_SUMMARY_IDS,
        SummaryCacheError,
        build_mode_summaries,
        build_run_fingerprint,
        build_run_keys,
        create_summary_run,
        discover_cache_dirs,
        load_summary_run_cache,
        normalize_weighting_modes,
        summary_root,
        write_summary_run_cache,
    )
    from summarize.reader import Config, prepare_data, read_run, resolve_skim_path

    print(f"[main] Loading config: {args.config}")
    config = Config.from_yaml(args.config)
    config.weighting_modes = normalize_weighting_modes(config.weighting_modes)
    cache_root = summary_root(config)
    if args.from_csvs is None:
        cache_root.mkdir(parents=True, exist_ok=True)

    def _resolve_run_entries(require_runs: bool) -> list[dict]:
        if args.cli_runs:
            print("[main] Using runs provided on CLI")
            run_entries = []
            cli_skims = args.cli_run_skims or []
            for i, (run_dir, label) in enumerate(args.cli_runs):
                skim = cli_skims[i] if i < len(cli_skims) else None
                if skim in ("", "null", "None"):
                    skim = None
                run_entries.append({"dir": run_dir, "label": label, "skim_file": skim})
            return run_entries
        if config.runs:
            print("[main] Using runs from config")
            return list(config.runs)
        if require_runs:
            print(
                "Error: no runs specified. Add runs to config.yaml or use --run DIR LABEL.",
                file=sys.stderr,
            )
            sys.exit(1)
        return []

    raw_runs: list[tuple[str, object]] = []
    summary_runs = []

    if args.from_csvs is not None:
        explicit_dirs = [Path(path).resolve() for path in args.from_csvs]
        if explicit_dirs:
            cache_dirs = explicit_dirs
            run_entries_by_key: dict[str, dict] = {}
        else:
            run_entries = _resolve_run_entries(require_runs=False)
            if run_entries:
                run_labels = [
                    entry.get("label", Path(entry.get("dir", "")).name or "run")
                    for entry in run_entries
                ]
                run_keys = build_run_keys(run_labels)
                cache_dirs = [cache_root / run_key for run_key in run_keys]
                run_entries_by_key = {
                    run_key: entry for entry, run_key in zip(run_entries, run_keys)
                }
            else:
                cache_dirs = discover_cache_dirs(cache_root)
                run_entries_by_key = {}

        if not cache_dirs:
            print(
                "Error: no summary cache directories were found to load.",
                file=sys.stderr,
            )
            sys.exit(1)

        print("[main] Loading pre-computed summary caches")
        for cache_dir in cache_dirs:
            expected_label = None
            expected_run_key = None
            expected_run_fingerprint = None
            if cache_dir.name in run_entries_by_key:
                entry = run_entries_by_key[cache_dir.name]
                run_dir = entry.get("dir", "")
                expected_label = entry.get("label", Path(run_dir).name)
                expected_run_key = cache_dir.name
                expected_run_fingerprint = build_run_fingerprint(
                    label=expected_label,
                    run_dir=run_dir,
                    skim_file=resolve_skim_path(
                        entry.get("skim_file") or None,
                        config.skim_file,
                        run_dir,
                    ),
                    hh_weight_col=entry.get("hh_weight_col") or None,
                    person_weight_col=entry.get("person_weight_col") or None,
                    trip_weight_col=entry.get("trip_weight_col") or None,
                )
            summary_runs.append(
                load_summary_run_cache(
                    cache_dir,
                    config,
                    expected_modes=config.weighting_modes,
                    expected_summary_ids=DEFAULT_SUMMARY_IDS,
                    expected_config_digest=config.config_digest,
                    expected_run_fingerprint=expected_run_fingerprint,
                    expected_label=expected_label,
                    expected_run_key=expected_run_key,
                )
            )
    else:
        run_entries = _resolve_run_entries(require_runs=True)
        run_labels = [
            entry.get("label", Path(entry.get("dir", "")).name or "run")
            for entry in run_entries
        ]
        run_keys = build_run_keys(run_labels)

        for entry, run_key in zip(run_entries, run_keys):
            run_dir = entry.get("dir", "")
            label = entry.get("label", Path(run_dir).name)
            skim = entry.get("skim_file") or None
            resolved_skim = resolve_skim_path(skim, config.skim_file, run_dir)
            run_fingerprint = build_run_fingerprint(
                label=label,
                run_dir=run_dir,
                skim_file=resolved_skim,
                hh_weight_col=entry.get("hh_weight_col") or None,
                person_weight_col=entry.get("person_weight_col") or None,
                trip_weight_col=entry.get("trip_weight_col") or None,
            )
            cache_dir = cache_root / run_key

            if not args.write_csvs:
                try:
                    cached_run = load_summary_run_cache(
                        cache_dir,
                        config,
                        expected_modes=config.weighting_modes,
                        expected_summary_ids=DEFAULT_SUMMARY_IDS,
                        expected_config_digest=config.config_digest,
                        expected_run_fingerprint=run_fingerprint,
                        expected_label=label,
                        expected_run_key=run_key,
                    )
                    print(f"[main] Loaded summary cache for run: {label!r}")
                    summary_runs.append(cached_run)
                    continue
                except SummaryCacheError as exc:
                    print(f"[main] Cache miss for {label!r}: {exc}")

            print(f"Reading run: {label!r} from {run_dir}")
            rd = read_run(
                run_dir,
                config,
                label=label,
                skim_file=skim,
                hh_weight_col=entry.get("hh_weight_col") or None,
                person_weight_col=entry.get("person_weight_col") or None,
                trip_weight_col=entry.get("trip_weight_col") or None,
            )
            rd = prepare_data(rd, config)
            print(f"[main] Prepared run: {label!r}")
            raw_runs.append((label, rd))

            summary_run = create_summary_run(
                label=label,
                run_key=run_key,
                summaries_by_mode=build_mode_summaries(rd, config),
                source_run_dir=str(rd.run_dir),
                raw_run=rd,
            )
            summary_runs.append(summary_run)

            if args.write_csvs or not args.skip_summary_cache_write:
                print(f"[main] Writing summary cache for run: {label!r}")
                cache_path = write_summary_run_cache(
                    summary_run,
                    config,
                    run_fingerprint=run_fingerprint,
                )
                print(f"[main] Wrote summaries: {cache_path}")
            else:
                print(f"[main] Skipped cache write for run: {label!r}")

    if not summary_runs:
        print("Error: no runs were loaded.", file=sys.stderr)
        sys.exit(1)

    if args.no_dashboard:
        print("Done writing CSVs. Exiting.")
        print(f"[main] Run completed in {(time.perf_counter() - t0) / 60:.2f} minutes.")
        return

    from dashboard.app import build_dashboard
    from dashboard.export_html import write_export_html_document
    import panel as pn

    if args.export_html:
        print("[main] Building dashboard")
        print(f"Exporting dashboard to {args.export_html} ...")
        write_export_html_document(
            args.export_html,
            raw_runs,
            config,
            summary_runs=summary_runs,
        )
        print("Done.")
        print(
            f"[main] Dashboard created in {(time.perf_counter() - t0) / 60:.2f} minutes."
        )
        return

    print("[main] Building dashboard")
    dashboard = build_dashboard(
        raw_runs,
        config,
        # static_export=False,
        summary_runs=summary_runs,
    )
    print(f"[main] Dashboard created in {(time.perf_counter() - t0) / 60:.2f} minutes.")
    pn.serve(
        dashboard,
        port=args.port,
        show=not args.no_show,
        title=config.dashboard_title,
    )


if __name__ == "__main__":
    main()
