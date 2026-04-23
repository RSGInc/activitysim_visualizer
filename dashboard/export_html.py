"""Standalone single-file HTML export for offline dashboard viewing."""

from __future__ import annotations

import html
import json
from pathlib import Path

from plotly.offline import get_plotlyjs

from dashboard.export_payload import build_export_payload
from dashboard.export_runtime_assets import build_export_html_shell
from dashboard.export_serializer import json_default, sanitize_export_payload
from runtime.config import Config
from runtime.models import RunData
from summarize.cache import SummaryRun


def build_export_html_document(
    runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> str:
    """Build a self-contained HTML document for offline dashboard viewing."""
    payload = sanitize_export_payload(
        build_export_payload(runs, config, summary_runs=summary_runs)
    )
    payload_json = json.dumps(
        payload,
        default=json_default,
        allow_nan=False,
    ).replace("</", "<\\/")
    return build_export_html_shell(
        title=html.escape(config.dashboard_title),
        payload_json=payload_json,
        plotly_js=get_plotlyjs(),
    )


def write_export_html_document(
    output_path: str | Path,
    runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> Path:
    """Write the standalone export HTML document to disk."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        build_export_html_document(runs, config, summary_runs=summary_runs),
        encoding="utf-8",
    )
    return output_path
