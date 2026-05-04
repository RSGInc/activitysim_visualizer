"""Standalone single-file HTML export for offline dashboard viewing."""

from __future__ import annotations

import html
import json
from pathlib import Path

from plotly.offline import get_plotlyjs

from dashboard.export.payload import build_export_artifacts, emit_export_size_warnings
from dashboard.export.runtime_assets import build_export_html_shell
from dashboard.export.serializer import json_default, sanitize_export_payload
from runtime.config import Config
from processor.models import RunData
from processor.summarize.cache import SummaryRun


def build_export_html_document(
    runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> str:
    """Build a self-contained HTML document for offline dashboard viewing."""
    payload, diagnostics = build_export_artifacts(
        runs, config, summary_runs=summary_runs
    )
    emit_export_size_warnings(diagnostics.get("size_analysis"))
    payload = sanitize_export_payload(payload)
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
    payload, diagnostics = build_export_artifacts(
        runs, config, summary_runs=summary_runs
    )
    emit_export_size_warnings(diagnostics.get("size_analysis"))
    payload = sanitize_export_payload(payload)
    output_path.write_text(
        build_export_html_shell(
            title=html.escape(config.dashboard_title),
            payload_json=json.dumps(
                payload,
                default=json_default,
                allow_nan=False,
            ).replace("</", "<\\/"),
            plotly_js=get_plotlyjs(),
        ),
        encoding="utf-8",
    )
    diagnostics_path = output_path.with_name(f"{output_path.stem}.diagnostics.json")
    diagnostics_path.write_text(
        json.dumps(
            sanitize_export_payload(diagnostics),
            default=json_default,
            allow_nan=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return output_path
