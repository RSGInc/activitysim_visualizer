"""Standalone single-file HTML export for offline dashboard viewing."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from runtime.logging import get_logger
from plotly.offline import get_plotlyjs

from dashboard.export.payload import build_export_artifacts, emit_export_size_warnings
from dashboard.export.runtime_assets import (
    build_export_html_shell,
    build_export_html_shell_parts,
)
from dashboard.export.serializer import (
    json_default,
    sanitize_export_payload_in_place,
)
from runtime.config import Config
from processor.models import RunData
from processor.summarize.cache_types import SummaryRun

LOGGER = get_logger("dashboard.export")

PAYLOAD_SCRIPT_START_TOKEN = (
    '<script id="activitysim-export-data" type="application/json">'
)
PAYLOAD_SCRIPT_END_TOKEN = "</script>"


class ExportBuildError(ValueError):
    """Raised when one phase of export generation fails."""

    def __init__(
        self,
        *,
        phase: str,
        output_path: str | Path | None = None,
        hint: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.phase = phase
        self.output_path = str(output_path) if output_path is not None else None
        self.hint = hint
        self.detail = detail

        message = f"HTML export failed during {phase}"
        if self.output_path:
            message += f" for {self.output_path}"
        if detail:
            message += f": {detail}"
        if hint:
            message += f" Hint: {hint}"
        super().__init__(message)


def _run_export_phase(
    phase: str,
    func,
    *,
    output_path: str | Path | None = None,
    hint: str | None = None,
):
    try:
        return func()
    except ExportBuildError:
        raise
    except Exception as exc:
        raise ExportBuildError(
            phase=phase,
            output_path=output_path,
            hint=hint,
            detail=str(exc),
        ) from exc


def _build_export_payload_and_diagnostics(
    runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> tuple[dict, dict]:
    payload, diagnostics = build_export_artifacts(
        runs, config, summary_runs=summary_runs
    )
    emit_export_size_warnings(diagnostics.get("size_analysis"))
    return (
        sanitize_export_payload_in_place(payload),
        sanitize_export_payload_in_place(diagnostics),
    )


def _serialize_export_payload_json(payload: dict) -> str:
    return json.dumps(
        payload,
        default=json_default,
        allow_nan=False,
    ).replace("</", "<\\/")


def _serialize_export_diagnostics_json(diagnostics: dict) -> str:
    return json.dumps(
        diagnostics,
        default=json_default,
        allow_nan=False,
        indent=2,
    )


def _build_export_html_shell_document(*, title: str, payload_json: str) -> str:
    return build_export_html_shell(
        title=html.escape(title),
        payload_json=payload_json,
        plotly_js=get_plotlyjs(),
    )


def _build_export_html_shell_parts(*, title: str) -> tuple[str, str]:
    return build_export_html_shell_parts(
        title=html.escape(title),
        plotly_js=get_plotlyjs(),
    )


def _validate_export_html_shell_parts(prefix: str, suffix: str) -> None:
    if not prefix.endswith(PAYLOAD_SCRIPT_START_TOKEN):
        raise ExportBuildError(
            phase="validate assembled HTML",
            hint="The generated HTML is missing the embedded export payload script tag.",
        )
    if not suffix.startswith(PAYLOAD_SCRIPT_END_TOKEN):
        raise ExportBuildError(
            phase="validate assembled HTML",
            hint="The generated HTML is missing the closing </script> for the embedded payload.",
        )


def _validate_export_html_document(document: str) -> None:
    if PAYLOAD_SCRIPT_START_TOKEN not in document:
        raise ExportBuildError(
            phase="validate assembled HTML",
            hint="The generated HTML is missing the embedded export payload script tag.",
        )
    start = document.index(PAYLOAD_SCRIPT_START_TOKEN) + len(PAYLOAD_SCRIPT_START_TOKEN)
    end = document.find(PAYLOAD_SCRIPT_END_TOKEN, start)
    if end < 0:
        raise ExportBuildError(
            phase="validate assembled HTML",
            hint="The generated HTML is missing the closing </script> for the embedded payload.",
        )
    payload_start = start
    while payload_start < end and document[payload_start].isspace():
        payload_start += 1
    payload_end = end - 1
    while payload_end >= payload_start and document[payload_end].isspace():
        payload_end -= 1
    if payload_start > payload_end:
        raise ExportBuildError(
            phase="validate assembled HTML",
            hint="The embedded export payload was empty. Regenerate the export and inspect the diagnostics output.",
        )
    if document[payload_start] != "{" or document[payload_end] != "}":
        raise ExportBuildError(
            phase="validate assembled HTML",
            hint="The generated HTML payload does not have the expected JSON object boundaries.",
        )


def _iter_script_safe_payload_json(payload: dict) -> Iterator[str]:
    """Yield JSON chunks while escaping closing tags across chunk boundaries."""

    encoder = json.JSONEncoder(
        default=json_default,
        allow_nan=False,
    )
    pending = ""
    for chunk in encoder.iterencode(payload):
        text = pending + chunk
        if text.endswith("<"):
            text = text[:-1]
            pending = "<"
        else:
            pending = ""
        if text:
            yield text.replace("</", "<\\/")
    if pending:
        yield pending


def _write_streamed_export_html(
    path: Path,
    *,
    prefix: str,
    payload: dict,
    suffix: str,
) -> None:
    """Write one export without materializing its JSON or final HTML string."""

    payload_characters = 0
    first_payload_character: str | None = None
    last_payload_character: str | None = None
    try:
        with path.open("w", encoding="utf-8") as stream:
            stream.write(prefix)
            for chunk in _iter_script_safe_payload_json(payload):
                if first_payload_character is None:
                    first_payload_character = chunk[0]
                last_payload_character = chunk[-1]
                payload_characters += len(chunk)
                stream.write(chunk)
            stream.write(suffix)
    except (TypeError, ValueError) as exc:
        raise ExportBuildError(
            phase="serialize payload JSON",
            output_path=path,
            hint="The export payload contained data that could not be serialized to JSON.",
            detail=str(exc),
        ) from exc

    if (
        payload_characters == 0
        or first_payload_character != "{"
        or last_payload_character != "}"
    ):
        raise ExportBuildError(
            phase="validate assembled HTML",
            output_path=path,
            hint="The streamed export payload was empty or incomplete.",
        )


def _write_text_file(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")


def _temporary_path(final_path: Path) -> Path:
    return final_path.with_name(f".{final_path.name}.{uuid4().hex}.tmp")


def _write_temp_text(final_path: Path, contents: str) -> Path:
    temp_path = _temporary_path(final_path)
    _write_text_file(temp_path, contents)
    return temp_path


def _finalize_temp_file(temp_path: Path, final_path: Path) -> None:
    temp_path.replace(final_path)


def _cleanup_temp_files(*paths: Path | None) -> None:
    for path in paths:
        if path is None:
            continue
        try:
            if path.exists():
                path.unlink()
        except OSError:
            LOGGER.warning("Could not remove temporary export file %s", path)


def build_export_html_document(
    runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> str:
    """Build a self-contained HTML document for offline dashboard viewing."""
    payload, _ = _run_export_phase(
        "build payload",
        lambda: _build_export_payload_and_diagnostics(
            runs, config, summary_runs=summary_runs
        ),
        hint="The export payload could not be constructed from the requested dashboard state.",
    )
    payload_json = _run_export_phase(
        "serialize payload JSON",
        lambda: _serialize_export_payload_json(payload),
        hint="The export payload contained data that could not be serialized to JSON.",
    )
    document = _run_export_phase(
        "assemble HTML shell",
        lambda: _build_export_html_shell_document(
            title=config.dashboard_title,
            payload_json=payload_json,
        ),
        hint="The standalone HTML shell could not be assembled.",
    )
    _run_export_phase(
        "validate assembled HTML",
        lambda: _validate_export_html_document(document),
        hint="The generated HTML failed an integrity check before it was returned.",
    )
    return document


def write_export_html_document(
    output_path: str | Path,
    runs: list[tuple[str, RunData]],
    config: Config,
    summary_runs: list[SummaryRun] | None = None,
) -> Path:
    """Write the standalone export HTML document to disk."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics_path = output_path.with_name(f"{output_path.stem}.diagnostics.json")
    output_existed = output_path.exists()
    diagnostics_existed = diagnostics_path.exists()
    html_temp_path: Path | None = None
    diagnostics_temp_path: Path | None = None
    html_finalized = False
    diagnostics_finalized = False

    LOGGER.info("Export phase: build payload")
    payload, diagnostics = _run_export_phase(
        "build payload",
        lambda: _build_export_payload_and_diagnostics(
            runs, config, summary_runs=summary_runs
        ),
        output_path=output_path,
        hint="Check summary/prepared data compatibility and export page configuration.",
    )
    diagnostics_json = _run_export_phase(
        "serialize diagnostics JSON",
        lambda: _serialize_export_diagnostics_json(diagnostics),
        output_path=diagnostics_path,
        hint="The export diagnostics contained data that could not be serialized to JSON.",
    )
    LOGGER.info("Export phase: assemble streaming HTML shell")
    prefix, suffix = _run_export_phase(
        "assemble HTML shell",
        lambda: _build_export_html_shell_parts(
            title=config.dashboard_title,
        ),
        output_path=output_path,
        hint="The standalone HTML shell could not be assembled.",
    )
    LOGGER.info("Export phase: validate assembled HTML")
    _run_export_phase(
        "validate assembled HTML",
        lambda: _validate_export_html_shell_parts(prefix, suffix),
        output_path=output_path,
        hint="The generated HTML looked incomplete or malformed before it was written.",
    )
    try:
        LOGGER.info("Export phase: stream HTML atomically")
        html_temp_path = _temporary_path(output_path)
        _run_export_phase(
            "write HTML atomically",
            lambda: _write_streamed_export_html(
                html_temp_path,
                prefix=prefix,
                payload=payload,
                suffix=suffix,
            ),
            output_path=output_path,
            hint="The HTML export could not be serialized or written to its temporary location.",
        )
        LOGGER.info("Export phase: write diagnostics file")
        diagnostics_temp_path = _run_export_phase(
            "write diagnostics sidecar",
            lambda: _write_temp_text(diagnostics_path, diagnostics_json),
            output_path=diagnostics_path,
            hint="The diagnostics file could not be written to its temporary location.",
        )
        LOGGER.info("Export phase: finalize export files")
        _run_export_phase(
            "finalize export files",
            lambda: _finalize_temp_file(diagnostics_temp_path, diagnostics_path),
            output_path=diagnostics_path,
            hint="The completed diagnostics file could not be moved into place.",
        )
        diagnostics_finalized = True
        _run_export_phase(
            "finalize export files",
            lambda: _finalize_temp_file(html_temp_path, output_path),
            output_path=output_path,
            hint="The completed HTML export file could not be moved into place.",
        )
        html_finalized = True
    except ExportBuildError:
        _cleanup_temp_files(html_temp_path, diagnostics_temp_path)
        if not output_existed and not html_finalized:
            _cleanup_temp_files(output_path)
        if not diagnostics_existed and not diagnostics_finalized:
            _cleanup_temp_files(diagnostics_path)
        raise
    return output_path
