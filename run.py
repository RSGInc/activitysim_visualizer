"""ActivitySim Visualizer — CLI entry point.

Usage examples:
  # Use runs defined in config.yaml
  python run.py --config config.yaml

  # Override/add runs on the command line (repeatable)
  python run.py --run /path/to/run1 "Base" --run /path/to/run2 "Build"

  # Per-run skim override
  python run.py --run /path/to/run1 "Base" --run-skim /path/to/run1/skims.omx

  # Dashboard + write calibration CSVs
  python run.py --write-csvs

  # Write CSVs only (no dashboard)
  python run.py --write-csvs --no-dashboard

  # Export self-contained HTML
  python run.py --export-html output.html
"""

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
        help="Add a run: --run /path/to/dir 'My Label'  (repeatable; overrides config runs)",
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
        help="Write summary CSVs to each run's output directory",
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

    # ------------------------------------------------------------------ #
    # Imports (deferred so --help is fast)
    # ------------------------------------------------------------------ #
    from summarize.reader import Config, read_run, prepare_data
    from summarize import writer as csv_writer
    from summarize.summary_bundle import build_summaries

    print(f"[main] Loading config: {args.config}")
    config = Config.from_yaml(args.config)

    # ------------------------------------------------------------------ #
    # Resolve which runs to load
    # ------------------------------------------------------------------ #
    # CLI --run entries override config runs when provided
    if args.cli_runs:
        print("[main] Using runs provided on CLI")
        run_entries = []
        cli_skims = args.cli_run_skims or []
        for i, (run_dir, label) in enumerate(args.cli_runs):
            skim = cli_skims[i] if i < len(cli_skims) else None
            if skim in ("", "null", "None"):
                skim = None
            run_entries.append({"dir": run_dir, "label": label, "skim_file": skim})
    elif config.runs:
        print("[main] Using runs from config")
        run_entries = config.runs
    else:
        print(
            "Error: no runs specified. Add runs to config.yaml or use --run DIR LABEL.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.from_csvs:
        raise NotImplementedError("--from-csvs is not yet implemented.")

    # ------------------------------------------------------------------ #
    # Load and prepare run data
    # ------------------------------------------------------------------ #
    runs: list[tuple[str, object]] = []
    for entry in run_entries:
        run_dir = entry.get("dir", "")
        label = entry.get("label", Path(run_dir).name)
        skim = entry.get("skim_file") or None

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
        runs.append((label, rd))

    if not runs:
        print("Error: no runs were loaded.", file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------ #
    # Optionally write CSVs
    # ------------------------------------------------------------------ #
    if args.write_csvs:
        print("[main] Generating summary outputs")

        for label, rd in runs:
            print(f"Writing CSVs for run: {label}")
            out_dir = Path(rd.run_dir) / "summary_outputs"
            summaries = build_summaries(rd, config)
            csv_writer.write_all(summaries, out_dir)
            print(f"[main] Wrote summaries: {out_dir}")

    if args.no_dashboard:
        print("Done writing CSVs. Exiting.")
        print(f"[main] Run completed in {(time.perf_counter() - t0) / 60:.2f} minutes.")
        return

    # ------------------------------------------------------------------ #
    # Build and serve the dashboard
    # ------------------------------------------------------------------ #
    from dashboard.app import build_dashboard, build_export_view
    import panel as pn

    if args.export_html:
        print("[main] Building dashboard")
        print(f"Exporting dashboard to {args.export_html} ...")
        export_view, _ = build_export_view(runs, config)
        export_view.save(args.export_html)
        print("Done.")
        print(
            f"[main] Dashboard created in {(time.perf_counter() - t0) / 60:.2f} minutes."
        )
        return

    print("[main] Building dashboard")
    dashboard = build_dashboard(runs, config, static_export=False)
    print(f"[main] Dashboard created in {(time.perf_counter() - t0) / 60:.2f} minutes.")
    pn.serve(
        dashboard,
        port=args.port,
        show=not args.no_show,
        title=config.dashboard_title,
    )


if __name__ == "__main__":
    main()
