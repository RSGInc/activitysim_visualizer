"""Shared calculation-note content and rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import html
from pathlib import Path
from typing import Mapping

import panel as pn
import yaml


CALCULATION_NOTES_PATH = Path(__file__).with_name("calculation_notes.yaml")

CALCULATION_NOTE_STYLESHEET = """
.calculation-note-block {
  margin: 4px 0 12px;
}
.calculation-note-summary {
  margin: 0 0 6px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.45;
}
.calculation-note {
  margin: 0;
  border: 1px solid #dbe3ec;
  border-radius: 10px;
  background: #f8fafc;
  color: #334155;
  overflow: hidden;
}
.calculation-note summary {
  padding: 9px 12px;
  cursor: pointer;
  color: #334155;
  font-size: 13px;
  font-weight: 650;
  user-select: none;
}
.calculation-note summary:hover {
  background: #f1f5f9;
}
.calculation-note[open] summary {
  border-bottom: 1px solid #dbe3ec;
}
.calculation-note-content {
  padding: 10px 14px 12px;
  font-size: 13px;
  line-height: 1.5;
}
.calculation-note-content p {
  margin: 0 0 8px;
}
.calculation-note-content p:last-child,
.calculation-note-content ul:last-child {
  margin-bottom: 0;
}
.calculation-note-formula code {
  white-space: normal;
}
.calculation-note-section {
  margin-top: 8px;
}
.calculation-note-section ul {
  margin: 3px 0 0;
  padding-left: 20px;
}
"""


@dataclass(frozen=True)
class CalculationNote:
    """Validated calculation-note content loaded from YAML."""

    note_id: str
    label: str
    summary: str
    formula: str | None
    details: tuple[tuple[str, tuple[str, ...]], ...]
    method_explanation: str | None = None
    sources: tuple[str, ...] = ()


def _nonempty_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Calculation note {field} must be a non-empty string.")
    return value.strip()


def _parse_note(
    note_id: str,
    raw_note: object,
    methods: Mapping[str, str],
) -> CalculationNote:
    if not isinstance(raw_note, dict):
        raise ValueError(f"Calculation note {note_id!r} must be a mapping.")
    allowed_fields = {"label", "summary", "formula", "details", "method", "sources"}
    unexpected = sorted(set(raw_note) - allowed_fields)
    if unexpected:
        raise ValueError(
            f"Calculation note {note_id!r} has unsupported fields: "
            + ", ".join(unexpected)
        )

    label = _nonempty_text(
        raw_note.get("label", "How this is calculated"),
        field=f"{note_id!r}.label",
    )
    summary = _nonempty_text(
        raw_note.get("summary"), field=f"{note_id!r}.summary"
    )
    raw_formula = raw_note.get("formula")
    formula = (
        None
        if raw_formula is None
        else _nonempty_text(raw_formula, field=f"{note_id!r}.formula")
    )

    raw_method = raw_note.get("method", "grouped_counts")
    method_name = _nonempty_text(raw_method, field=f"{note_id!r}.method")
    try:
        method_explanation = methods[method_name]
    except KeyError as exc:
        raise ValueError(
            f"Calculation note {note_id!r} references unknown method "
            f"{method_name!r}."
        ) from exc

    raw_sources = raw_note.get("sources", [])
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError(
            f"Calculation note {note_id!r}.sources must be a non-empty list."
        )
    sources = tuple(
        _nonempty_text(source, field=f"{note_id!r}.sources item")
        for source in raw_sources
    )

    raw_details = raw_note.get("details", {})
    if not isinstance(raw_details, dict):
        raise ValueError(f"Calculation note {note_id!r}.details must be a mapping.")
    details: list[tuple[str, tuple[str, ...]]] = []
    for raw_heading, raw_items in raw_details.items():
        heading = _nonempty_text(
            raw_heading, field=f"{note_id!r}.details heading"
        )
        if not isinstance(raw_items, list) or not raw_items:
            raise ValueError(
                f"Calculation note {note_id!r}.details.{heading} must be a "
                "non-empty list."
            )
        items = tuple(
            _nonempty_text(item, field=f"{note_id!r}.details.{heading} item")
            for item in raw_items
        )
        details.append((heading, items))

    return CalculationNote(
        note_id=note_id,
        label=label,
        summary=summary,
        formula=formula,
        details=tuple(details),
        method_explanation=method_explanation,
        sources=sources,
    )


@lru_cache(maxsize=None)
def load_calculation_notes(
    path: str | Path = CALCULATION_NOTES_PATH,
) -> Mapping[str, CalculationNote]:
    """Load and validate the calculation-note registry."""
    note_path = Path(path)
    with note_path.open("r", encoding="utf-8") as stream:
        raw_registry = yaml.safe_load(stream)
    if not isinstance(raw_registry, dict) or set(raw_registry) != {"methods", "notes"}:
        raise ValueError(
            "Calculation notes YAML must contain top-level 'methods' and 'notes' mappings."
        )
    raw_methods = raw_registry["methods"]
    if not isinstance(raw_methods, dict) or not raw_methods:
        raise ValueError("Calculation notes YAML 'methods' must be a non-empty mapping.")
    methods = {
        _nonempty_text(name, field="method name"): _nonempty_text(
            explanation, field=f"method {name!r}"
        )
        for name, explanation in raw_methods.items()
    }
    raw_notes = raw_registry["notes"]
    if not isinstance(raw_notes, dict) or not raw_notes:
        raise ValueError("Calculation notes YAML 'notes' must be a non-empty mapping.")

    notes: dict[str, CalculationNote] = {}
    for raw_note_id, raw_note in raw_notes.items():
        note_id = _nonempty_text(raw_note_id, field="id")
        notes[note_id] = _parse_note(note_id, raw_note, methods)
    return notes


def get_calculation_note(note_id: str) -> CalculationNote:
    """Return a configured note or raise a useful error for an unknown id."""
    notes = load_calculation_notes()
    try:
        return notes[note_id]
    except KeyError as exc:
        available = ", ".join(sorted(notes))
        raise KeyError(
            f"Unknown calculation note {note_id!r}. Available notes: {available}"
        ) from exc


def render_calculation_note_html(note: CalculationNote) -> str:
    """Render one validated note as dependency-free native HTML details."""
    sections = [
        "<div class='calculation-note-block' "
        f"data-calculation-note-id='{html.escape(note.note_id, quote=True)}'>",
        f"<p class='calculation-note-summary'>{html.escape(note.summary)}</p>",
        "<details class='calculation-note' "
        f"data-calculation-note-id='{html.escape(note.note_id, quote=True)}'>",
        f"<summary>{html.escape(note.label)}</summary>",
        "<div class='calculation-note-content'>",
    ]
    if note.formula:
        sections.append(
            "<p class='calculation-note-formula'><strong>Formula:</strong> "
            f"<code>{html.escape(note.formula)}</code></p>"
        )
    if note.method_explanation:
        sections.append(
            "<div class='calculation-note-section'>"
            "<strong>How the summary is prepared:</strong>"
            f"<ul><li>{html.escape(note.method_explanation)}</li></ul>"
            "</div>"
        )
    for heading, items in note.details:
        rendered_items = "".join(f"<li>{html.escape(item)}</li>" for item in items)
        sections.append(
            "<div class='calculation-note-section'>"
            f"<strong>{html.escape(heading)}:</strong>"
            f"<ul>{rendered_items}</ul>"
            "</div>"
        )
    if note.sources:
        rendered_sources = "".join(
            f"<li><code>{html.escape(source)}</code></li>" for source in note.sources
        )
        sections.append(
            "<div class='calculation-note-section'>"
            "<strong>Prepared summaries used:</strong>"
            f"<ul>{rendered_sources}</ul>"
            "</div>"
        )
    sections.extend(["</div>", "</details>", "</div>"])
    return "".join(sections)


def calculation_note(note_id: str) -> pn.pane.HTML:
    """Build a collapsible note shared by the live dashboard and HTML export."""
    return pn.pane.HTML(
        render_calculation_note_html(get_calculation_note(note_id)),
        sizing_mode="stretch_width",
        stylesheets=[CALCULATION_NOTE_STYLESHEET],
    )
