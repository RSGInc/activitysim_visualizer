"""Legacy config-key warnings."""

from __future__ import annotations

from typing import Any

from activitysim_viz_logging import get_logger

LOGGER = get_logger("runtime.config")


def warn_ignored_legacy_key(
    *,
    mapping: dict[str, Any],
    key: str,
    legacy_field_name: str,
    replacement_field_name: str,
) -> None:
    if key in mapping:
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
) -> None:
    if key in mapping:
        LOGGER.warning(
            "Config key '%s' is deprecated but still supported. Use '%s' instead.",
            legacy_field_name,
            replacement_field_name,
        )
