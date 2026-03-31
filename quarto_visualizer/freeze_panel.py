"""CLI to freeze current Panel behavior into reference CSV artifacts."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quarto_visualizer.app_state import load_prepared_runs, resolve_run_entries
from quarto_visualizer.panel_reference import write_panel_reference_bundle
from summarize.reader import Config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="activitysim-viz-freeze-panel",
        description="Write weighted and unweighted reference summaries for the Panel dashboard.",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=str(Path(__file__).resolve().parents[1] / "config.yaml"),
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
        "--output-dir",
        default="artifacts/panel_reference",
        help="Directory where reference outputs will be written",
    )
    parser.add_argument(
        "--weighted-only",
        action="store_true",
        help="Write only weighted reference summaries",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = Config.from_yaml(args.config)
    run_entries = resolve_run_entries(config, cli_runs=args.cli_runs, cli_run_skims=args.cli_run_skims)
    if not run_entries:
        print("Error: no runs specified. Add runs to config.yaml or use --run DIR LABEL.", file=sys.stderr)
        sys.exit(1)

    runs = load_prepared_runs(config, run_entries)

    out_path = write_panel_reference_bundle(
        runs,
        config,
        args.output_dir,
        include_unweighted=not args.weighted_only,
        config_path=str(Path(args.config).resolve()),
    )
    print(f"[freeze-panel] Wrote Panel reference bundle to {out_path.resolve()}")


if __name__ == "__main__":
    main()
