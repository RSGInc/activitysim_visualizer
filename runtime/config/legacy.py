"""Legacy config-key warnings."""

from __future__ import annotations

from typing import Any

from activitysim_viz_logging import get_logger

LOGGER = get_logger("runtime.config")


def _record_legacy_warning(
    collector: list[tuple[str, str, str]] | None,
    *,
    kind: str,
    legacy_field_name: str,
    replacement_field_name: str,
) -> None:
    if collector is None:
        return
    collector.append((kind, legacy_field_name, replacement_field_name))


def warn_ignored_legacy_key(
    *,
    mapping: dict[str, Any],
    key: str,
    legacy_field_name: str,
    replacement_field_name: str,
    collector: list[tuple[str, str, str]] | None = None,
) -> None:
    if key in mapping:
        _record_legacy_warning(
            collector,
            kind="ignored",
            legacy_field_name=legacy_field_name,
            replacement_field_name=replacement_field_name,
        )
        LOGGER.warning(
            "Ignoring legacy config key '%s'. Use '%s' instead.",
            legacy_field_name,
            replacement_field_name,
        )


def warn_supported_legacy_key(
    *,
    mapping: dict[str, Any],
    key: str,
    legacy_field_name: str,
    replacement_field_name: str,
    collector: list[tuple[str, str, str]] | None = None,
) -> None:
    if key in mapping:
        _record_legacy_warning(
            collector,
            kind="supported",
            legacy_field_name=legacy_field_name,
            replacement_field_name=replacement_field_name,
        )
        LOGGER.warning(
            "Config key '%s' is deprecated but still supported. Use '%s' instead.",
            legacy_field_name,
            replacement_field_name,
        )


def emit_grouped_legacy_summary(
    collector: list[tuple[str, str, str]],
) -> None:
    if not collector:
        return

    seen: set[tuple[str, str, str]] = set()
    unique = []
    for item in collector:
        if item in seen:
            continue
        unique.append(item)
        seen.add(item)

    ignored = [
        (legacy_field_name, replacement_field_name)
        for kind, legacy_field_name, replacement_field_name in unique
        if kind == "ignored"
    ]
    supported = [
        (legacy_field_name, replacement_field_name)
        for kind, legacy_field_name, replacement_field_name in unique
        if kind == "supported"
    ]

    summary_lines = [
        "Deprecated config keys were detected. Prefer the canonical schema:"
    ]
    if supported:
        summary_lines.extend(
            f"- {legacy_field_name} -> {replacement_field_name}"
            for legacy_field_name, replacement_field_name in supported
        )
    if ignored:
        summary_lines.append(
            "Legacy keys ignored because a canonical replacement was also set:"
        )
        summary_lines.extend(
            f"- {legacy_field_name} -> {replacement_field_name}"
            for legacy_field_name, replacement_field_name in ignored
        )
    LOGGER.warning("\n".join(summary_lines))
