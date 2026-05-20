"""Shared dashboard helpers for geography selector behavior."""

from __future__ import annotations


PREFERRED_TYPED_GEO_ORDER = [
    "all_geographies",
    "district",
    "taz",
    "maz",
]


def visible_geography_levels(
    values: list[str] | set[str] | tuple[str, ...],
    *,
    config,
) -> list[str]:
    """Return geography levels that should be exposed in dashboard selectors."""
    visible: list[str] = []
    for raw_value in values:
        value = str(raw_value).strip()
        if not value:
            continue
        if value.lower() == "maz" and not config.enable_maz_geographies:
            continue
        if value not in visible:
            visible.append(value)
    return visible


def ordered_visible_geography_levels(
    values: list[str] | set[str] | tuple[str, ...],
    *,
    config,
) -> list[str]:
    """Return visible geography levels in preferred dashboard order."""
    visible = visible_geography_levels(values, config=config)
    ordered = [value for value in PREFERRED_TYPED_GEO_ORDER if value in visible]
    extras = sorted(value for value in visible if value not in PREFERRED_TYPED_GEO_ORDER)
    return ordered + extras
