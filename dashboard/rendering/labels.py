"""Presentation-only shortening and wrapping for run labels."""

from __future__ import annotations

import html
import textwrap
from collections.abc import Iterable
from typing import Any


MAX_DISPLAY_LABEL_LENGTH = 30
HOVER_LABEL_LINE_LENGTH = 36


def _truncate_middle(label: str, max_length: int) -> str:
    if len(label) <= max_length:
        return label
    if max_length <= 1:
        return "…"[:max_length]

    words = label.split()
    if len(words) >= 3 and len(words[0]) + len(words[-1]) + 1 <= max_length:
        leading_words = [words[0]]
        trailing_words = [words[-1]]
        leading_index = 1
        trailing_index = len(words) - 2
        while leading_index <= trailing_index:
            changed = False
            leading_candidate = (
                " ".join([*leading_words, words[leading_index]])
                + "…"
                + " ".join(trailing_words)
            )
            if len(leading_candidate) <= max_length:
                leading_words.append(words[leading_index])
                leading_index += 1
                changed = True
            trailing_candidate = (
                " ".join(leading_words)
                + "…"
                + " ".join([words[trailing_index], *trailing_words])
            )
            if leading_index <= trailing_index and len(trailing_candidate) <= max_length:
                trailing_words.insert(0, words[trailing_index])
                trailing_index -= 1
                changed = True
            if not changed:
                break
        return " ".join(leading_words) + "…" + " ".join(trailing_words)

    available = max_length - 1
    leading_length = (available * 2 + 2) // 3
    trailing_length = available - leading_length
    leading = label[:leading_length].rstrip()
    trailing = label[-trailing_length:].lstrip() if trailing_length else ""
    return f"{leading}…{trailing}"


def display_label_map(
    labels: Iterable[object],
    *,
    max_length: int = MAX_DISPLAY_LABEL_LENGTH,
) -> dict[str, str]:
    """Return stable, unique display labels without changing full identities."""
    full_labels = list(dict.fromkeys(str(label) for label in labels))
    candidates = {
        label: _truncate_middle(label, max_length)
        for label in full_labels
    }
    groups: dict[str, list[str]] = {}
    for label, candidate in candidates.items():
        groups.setdefault(candidate, []).append(label)

    output: dict[str, str] = {}
    used: set[str] = set()
    for label in full_labels:
        candidate = candidates[label]
        duplicates = groups[candidate]
        if len(duplicates) == 1 and candidate not in used:
            output[label] = candidate
            used.add(candidate)
            continue

        index = duplicates.index(label) + 1
        while True:
            suffix = f" [{index}]"
            unique_candidate = (
                _truncate_middle(label, max_length - len(suffix)) + suffix
            )
            if unique_candidate not in used:
                output[label] = unique_candidate
                used.add(unique_candidate)
                break
            index += 1
    return output


def hover_label(label: object) -> str:
    """Return the escaped full label with line breaks suitable for Plotly."""
    lines = textwrap.wrap(
        str(label),
        width=HOVER_LABEL_LINE_LENGTH,
        break_long_words=True,
        break_on_hyphens=False,
    ) or [""]
    return "<br>".join(html.escape(line) for line in lines)


def attach_full_tab_titles(tabs: Any, labels: Iterable[object]) -> None:
    """Attach full titles for the standalone-export serializer."""
    tabs._run_label_full_titles = tuple(str(label) for label in labels)
