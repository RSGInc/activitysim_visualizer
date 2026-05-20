"""Shared runtime config models and YAML parsing.

This module may understand both ``summaries.*`` and ``visualizer.*`` config
sections because configuration is a cross-cutting runtime concern used by both
the summarizer and the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Optional

from activitysim_viz_logging import get_logger
import polars as pl
import yaml

LOGGER = get_logger("runtime.config")


@dataclass(frozen=True)
class DashboardPageConfigEntry:
    """Normalized dashboard page-selection entry from config."""

    page_id: str
    mode: str = "explicit"
    page_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExportSelectorRequest:
    """Requested export values for one page-level selector.

    This is the normalized config contract used by the HTML export path after
    YAML parsing. ``mode`` controls how values are resolved:

    - ``default``: export only the widget's default value
    - ``all``: export every currently available widget option
    - ``explicit``: export only the normalized values listed in ``values``
    """

    mode: str = "default"
    values: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExportPartOverride:
    """Requested export behavior for one named page part."""

    enabled: bool | None = None


@dataclass(frozen=True)
class ExportPageOverride:
    """Resolved export overrides for one leaf page."""

    enabled: bool | None = None
    selector_requests: dict[str, ExportSelectorRequest] = field(default_factory=dict)
    parts: dict[str, ExportPartOverride] = field(default_factory=dict)


@dataclass(frozen=True)
class ExportDashboardSettings:
    """Resolved dashboard-level controls for HTML export."""

    weighting: list[str] = field(default_factory=lambda: ["weighted"])
    values: list[str] = field(default_factory=lambda: ["percent"])

    def panel_weighting_values(self) -> list[str]:
        return [mode.title() for mode in self.weighting]

    def panel_value_values(self) -> list[str]:
        labels = {"percent": "Percent", "count": "Count"}
        return [labels[value] for value in self.values]


@dataclass(frozen=True)
class ExportHTMLSettings:
    """Normalized HTML export configuration.

    This combines two related settings:

    - dashboard-level state selection such as weighted/unweighted and
      percent/count combinations
    - page-level selector requests keyed by ``page_id`` and ``selector_id``
    """

    enabled: bool = False
    dashboard: ExportDashboardSettings = field(default_factory=ExportDashboardSettings)
    pages: dict[str, ExportPageOverride] = field(default_factory=dict)
    exclude_pages: tuple[str, ...] = ()
    exclude_groups: tuple[str, ...] = ()
    pages_configured: bool = False
    default_selector_request: ExportSelectorRequest = field(
        default_factory=lambda: ExportSelectorRequest(mode="all")
    )

    @property
    def weighting(self) -> list[str]:
        return self.dashboard.weighting

    @property
    def values(self) -> list[str]:
        return self.dashboard.values

    def panel_weighting_values(self) -> list[str]:
        return self.dashboard.panel_weighting_values()

    def panel_value_values(self) -> list[str]:
        return self.dashboard.panel_value_values()

    def selector_request(
        self,
        page_id: str,
        selector_id: str,
        *,
        group_id: str | None = None,
    ) -> ExportSelectorRequest:
        request = self.page_override(
            page_id,
            group_id=group_id,
        ).selector_requests.get(selector_id)
        if request is not None:
            return request
        return self.default_selector_request

    def page_override(
        self,
        page_id: str,
        *,
        group_id: str | None = None,
    ) -> ExportPageOverride:
        override = self.pages.get(page_id)
        if override is not None:
            return override
        if group_id is not None:
            override = self.pages.get(f"{group_id}.{page_id}")
            if override is not None:
                return override
        return ExportPageOverride()


@dataclass(frozen=True)
class SkimjoinSettings:
    """Optional runtime wiring for skim enrichment."""

    enabled: bool = False
    config_path: str | None = None
    config_digest: str | None = None
    normalized_config: Any | None = None


@dataclass(frozen=True)
class PrepareVotBinsSettings:
    """Optional run-aware VOT normalization applied during prepare."""

    enabled: bool = False
    source_column: str = "income_segment"
    output_column: str = "vot_bin"
    fallback_value: str | None = None
    mappings: dict[str, dict[str, str]] = field(default_factory=dict)

    def mapping_for_run(self, run_label: str) -> dict[str, str] | None:
        return self.mappings.get(_normalize_run_selector_key(run_label))


@dataclass(frozen=True)
class CategorySpec:
    """Canonical display labels and ordering rules for one categorical domain."""

    mapping_items: tuple[tuple[str, str], ...] = ()
    labels_by_raw: dict[str, str] = field(default_factory=dict)
    raw_values_in_order: tuple[str, ...] = ()
    fallback_order: str = "data"


_ESCORT_CANONICAL_DEFAULT_LABELS: dict[str, str] = {
    "not_escorted": "No Escort",
    "pure_escort": "Pure Escort",
    "ride_share": "Ride Share",
}


def _escort_normalization_key(raw_value) -> str | None:
    if raw_value is None:
        return "not_escorted"
    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        if not stripped:
            return "not_escorted"
        lowered = stripped.lower()
        compact = lowered.replace("_", "").replace(" ", "")
        if lowered in {"none", "null", "nan"}:
            return "not_escorted"
        if compact in {"0", "notescorted", "noescort"}:
            return "not_escorted"
        if compact in {"1", "pureescort"}:
            return "pure_escort"
        if compact in {"2", "rideshare"}:
            return "ride_share"
        return None
    return _escort_normalization_key(str(raw_value))


def _normalize_escort_category_spec(spec: CategorySpec | None) -> CategorySpec:
    canonical_labels = dict(_ESCORT_CANONICAL_DEFAULT_LABELS)
    extras: list[tuple[str, str]] = []
    seen_extras: set[str] = set()

    if spec is not None:
        for raw_key, display_label in spec.mapping_items:
            normalized = _escort_normalization_key(raw_key)
            if normalized is not None:
                if raw_key == normalized and normalized not in canonical_labels:
                    canonical_labels[normalized] = display_label
                elif raw_key == normalized:
                    canonical_labels[normalized] = display_label
                continue
            if raw_key not in seen_extras:
                extras.append((raw_key, display_label))
                seen_extras.add(raw_key)
        for canonical in _ESCORT_CANONICAL_DEFAULT_LABELS:
            for raw_key, display_label in spec.mapping_items:
                if raw_key == canonical:
                    canonical_labels[canonical] = display_label
                    break

    mapping_items = [
        (canonical, canonical_labels[canonical])
        for canonical in ("not_escorted", "pure_escort", "ride_share")
    ]
    if spec is not None:
        for raw_key, display_label in spec.mapping_items:
            if raw_key in {key for key, _ in mapping_items}:
                continue
            if raw_key not in seen_extras and _escort_normalization_key(raw_key) is None:
                extras.append((raw_key, display_label))
                seen_extras.add(raw_key)
            elif _escort_normalization_key(raw_key) is not None and raw_key not in seen_extras:
                extras.append((raw_key, display_label))
                seen_extras.add(raw_key)
    mapping_items.extend(extras)

    labels_by_raw = {raw_key: display_label for raw_key, display_label in mapping_items}
    return CategorySpec(
        mapping_items=tuple(mapping_items),
        labels_by_raw=labels_by_raw,
        raw_values_in_order=tuple(raw_key for raw_key, _ in mapping_items),
        fallback_order="data" if spec is None else spec.fallback_order,
    )


def _normalize_run_selector_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return normalized or str(value).strip().lower()


def _normalize_prepare_vot_bins(
    raw_value,
    *,
    field_name: str,
) -> PrepareVotBinsSettings:
    """Normalize optional run-aware VOT bin mappings."""
    if raw_value in (None, {}):
        return PrepareVotBinsSettings()
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    output_column = str(raw_value.get("output_column", "vot_bin")).strip()
    source_column = str(raw_value.get("source_column", "income_segment")).strip()
    if not output_column:
        raise ValueError(f"{field_name}.output_column must be a non-empty string.")
    if not source_column:
        raise ValueError(f"{field_name}.source_column must be a non-empty string.")

    fallback_raw = raw_value.get("fallback_value")
    fallback_value = None if fallback_raw is None else str(fallback_raw)

    mappings_raw = raw_value.get("mappings", {})
    if mappings_raw in (None, {}):
        return PrepareVotBinsSettings(
            enabled=False,
            source_column=source_column,
            output_column=output_column,
            fallback_value=fallback_value,
        )
    if not isinstance(mappings_raw, dict):
        raise ValueError(f"{field_name}.mappings must be a mapping.")

    mappings: dict[str, dict[str, str]] = {}
    for run_name, raw_mapping in mappings_raw.items():
        if not isinstance(raw_mapping, dict):
            raise ValueError(f"{field_name}.mappings.{run_name} must be a mapping.")
        normalized_run_name = _normalize_run_selector_key(str(run_name))
        if normalized_run_name in mappings:
            raise ValueError(
                f"{field_name}.mappings contains duplicate run key {run_name!r} after normalization."
            )
        mappings[normalized_run_name] = {
            str(source_value): str(mapped_value)
            for source_value, mapped_value in raw_mapping.items()
        }

    return PrepareVotBinsSettings(
        enabled=bool(mappings),
        source_column=source_column,
        output_column=output_column,
        fallback_value=fallback_value,
        mappings=mappings,
    )


def _normalize_export_html_selection(
    raw_value,
    *,
    field_name: str,
    default: list[str],
    allowed: list[str],
) -> list[str]:
    """Resolve an export HTML config selection to validated lowercase values."""
    if raw_value is None:
        raw_value = "default"

    if isinstance(raw_value, str):
        token = raw_value.strip().lower()
        if token == "default":
            result = list(default)
        elif token == "all":
            result = list(allowed)
        else:
            result = [token]
    elif isinstance(raw_value, list):
        result = []
        for item in raw_value:
            if not isinstance(item, str):
                raise ValueError(f"{field_name} entries must be strings.")
            token = item.strip().lower()
            if not token:
                continue
            result.append(token)
    else:
        raise ValueError(
            f"{field_name} must be 'default', 'all', or a list of strings."
        )

    deduped: list[str] = []
    invalid: list[str] = []
    for token in result:
        if token not in allowed:
            invalid.append(token)
            continue
        if token not in deduped:
            deduped.append(token)

    if invalid:
        raise ValueError(
            f"Unsupported {field_name} values: "
            + ", ".join(repr(token) for token in invalid)
        )
    if not deduped:
        raise ValueError(f"{field_name} resolved to no values.")
    return deduped


def _normalize_export_selector_request(
    raw_value,
    *,
    field_name: str,
) -> ExportSelectorRequest:
    """Normalize a page-level selector request."""
    if raw_value is None:
        return ExportSelectorRequest()

    if isinstance(raw_value, str):
        token = raw_value.strip().lower()
        if not token or token == "default":
            return ExportSelectorRequest(mode="default")
        if token == "all":
            return ExportSelectorRequest(mode="all")
        return ExportSelectorRequest(mode="explicit", values=(token,))

    if not isinstance(raw_value, list):
        raise ValueError(
            f"{field_name} must be 'default', 'all', or a list of strings."
        )

    normalized: list[str] = []
    for item in raw_value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} entries must be strings.")
        token = item.strip().lower()
        if not token:
            continue
        if token not in normalized:
            normalized.append(token)
    if not normalized:
        raise ValueError(f"{field_name} resolved to no values.")
    return ExportSelectorRequest(mode="explicit", values=tuple(normalized))


def _normalize_optional_bool(raw_value, *, field_name: str) -> bool | None:
    """Normalize an optional boolean config field."""
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        return raw_value
    raise ValueError(f"{field_name} must be true or false when provided.")


def _normalize_string_list(raw_value, *, field_name: str) -> list[str]:
    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise ValueError(f"{field_name} must be a list when provided.")

    normalized: list[str] = []
    for item in raw_value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} entries must be strings.")
        token = item.strip()
        if token and token not in normalized:
            normalized.append(token)
    return normalized


def _normalize_skimjoin_settings(
    raw_value,
    *,
    config_dir: Path,
) -> SkimjoinSettings:
    if raw_value is None:
        return SkimjoinSettings()
    if not isinstance(raw_value, dict):
        raise ValueError("skimjoin must be a mapping when provided.")

    enabled = raw_value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("skimjoin.enabled must be true or false when provided.")
    config_path_raw = raw_value.get("config_path")
    resolved_config_path: str | None = None
    if config_path_raw is not None:
        if not isinstance(config_path_raw, str) or not config_path_raw.strip():
            raise ValueError("skimjoin.config_path must be a non-empty string.")
        resolved_path = Path(config_path_raw).expanduser()
        if not resolved_path.is_absolute():
            resolved_path = (config_dir / resolved_path).resolve()
        resolved_config_path = str(resolved_path)

    if not enabled:
        return SkimjoinSettings(
            enabled=False,
            config_path=resolved_config_path,
        )

    if resolved_config_path is None:
        raise ValueError(
            "skimjoin.config_path is required when skimjoin.enabled is true."
        )

    from processor.skimjoin.config.io import load_config_file
    from processor.skimjoin.config.normalize import normalize_config
    from processor.skimjoin.config.validation import load_config

    skimjoin_data = load_config_file(resolved_config_path)
    explicit_config = load_config(
        skimjoin_data,
        require_activitysim_tables=False,
    )
    normalized_config = normalize_config(explicit_config)
    skim_files = list(normalized_config.skim_files)
    if not skim_files:
        raise ValueError(
            "Integrated skimjoin requires at least one skim file in the separate skimjoin config."
        )
    invalid_skim_files = [
        str(path)
        for path in skim_files
        if Path(str(path)).suffix.lower() not in {".omx", ".csv", ".h5", ".hdf5"}
    ]
    if invalid_skim_files:
        raise ValueError(
            "Integrated skimjoin supports only OMX, HDF5, and CSV skim inputs. "
            + "Unsupported skim files: "
            + ", ".join(repr(path) for path in invalid_skim_files)
        )

    return SkimjoinSettings(
        enabled=True,
        config_path=resolved_config_path,
        config_digest=_digest_payload(normalized_config.model_dump(mode="python")),
        normalized_config=normalized_config,
    )


def _normalize_excluded_ids(
    raw_value,
    *,
    field_name: str,
) -> tuple[str, ...]:
    """Normalize a page/group exclusion list."""
    if raw_value is None:
        return ()
    if not isinstance(raw_value, list):
        raise ValueError(f"{field_name} must be a list of ids when provided.")
    normalized: list[str] = []
    for item in raw_value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} entries must be strings.")
        token = item.strip().lower()
        if token and token not in normalized:
            normalized.append(token)
    return tuple(normalized)


def _normalize_export_page_override(
    raw_value,
    *,
    field_name: str,
) -> ExportPageOverride:
    """Normalize one leaf page export override."""
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping.")

    enabled = _normalize_optional_bool(
        raw_value.get("enabled"), field_name=f"{field_name}.enabled"
    )

    selector_requests: dict[str, ExportSelectorRequest] = {}
    parts: dict[str, ExportPartOverride] = {}
    for raw_key, raw_item in raw_value.items():
        key = str(raw_key).strip().lower()
        if not key:
            raise ValueError(f"{field_name} contains an empty key.")
        if key == "enabled":
            continue
        if key == "parts":
            if not isinstance(raw_item, dict):
                raise ValueError(f"{field_name}.parts must be a mapping.")
            for raw_part_id, raw_part_cfg in raw_item.items():
                part_id = str(raw_part_id).strip().lower()
                if not part_id:
                    raise ValueError(f"{field_name}.parts contains an empty part id.")
                if not isinstance(raw_part_cfg, dict):
                    raise ValueError(f"{field_name}.parts.{part_id} must be a mapping.")
                if set(raw_part_cfg) - {"enabled"}:
                    invalid_keys = ", ".join(
                        repr(str(item))
                        for item in sorted(set(raw_part_cfg) - {"enabled"})
                    )
                    raise ValueError(
                        f"{field_name}.parts.{part_id} only supports 'enabled'. Invalid keys: {invalid_keys}"
                    )
                parts[part_id] = ExportPartOverride(
                    enabled=_normalize_optional_bool(
                        raw_part_cfg.get("enabled"),
                        field_name=f"{field_name}.parts.{part_id}.enabled",
                    )
                )
            continue
        selector_requests[key] = _normalize_export_selector_request(
            raw_item,
            field_name=f"{field_name}.{key}",
        )

    return ExportPageOverride(
        enabled=enabled,
        selector_requests=selector_requests,
        parts=parts,
    )


def _normalize_dashboard_page_entries(
    raw_value,
    *,
    field_name: str,
) -> list[DashboardPageConfigEntry]:
    """Normalize live dashboard page config to ordered page/group entries."""
    if not isinstance(raw_value, list):
        raise ValueError(f"{field_name} must be a list when provided.")

    entries: list[DashboardPageConfigEntry] = []
    seen_page_ids: set[str] = set()
    for raw_entry in raw_value:
        if isinstance(raw_entry, str):
            page_id = raw_entry.strip().lower()
            if not page_id:
                raise ValueError(f"{field_name} contains an empty page id.")
            if page_id in seen_page_ids:
                raise ValueError(
                    f"{field_name} contains duplicate page id {page_id!r}."
                )
            entries.append(DashboardPageConfigEntry(page_id=page_id))
            seen_page_ids.add(page_id)
            continue

        if not isinstance(raw_entry, dict) or len(raw_entry) != 1:
            raise ValueError(
                f"{field_name} entries must be strings or single-key mappings."
            )
        raw_group_id, raw_children = next(iter(raw_entry.items()))
        page_id = str(raw_group_id).strip().lower()
        if not page_id:
            raise ValueError(f"{field_name} contains an empty page id.")
        if page_id in seen_page_ids:
            raise ValueError(f"{field_name} contains duplicate page id {page_id!r}.")

        if isinstance(raw_children, str):
            token = raw_children.strip().lower()
            if token not in {"default", "all"}:
                raise ValueError(
                    f"{field_name}.{page_id} must be 'default', 'all', or a list of page ids."
                )
            entries.append(DashboardPageConfigEntry(page_id=page_id, mode=token))
        elif isinstance(raw_children, list):
            child_page_ids: list[str] = []
            for raw_child_page_id in raw_children:
                if not isinstance(raw_child_page_id, str):
                    raise ValueError(f"{field_name}.{page_id} entries must be strings.")
                child_page_id = raw_child_page_id.strip().lower()
                if not child_page_id or child_page_id in child_page_ids:
                    continue
                child_page_ids.append(child_page_id)
            if not child_page_ids:
                raise ValueError(f"{field_name}.{page_id} resolved to no page ids.")
            entries.append(
                DashboardPageConfigEntry(
                    page_id=page_id,
                    mode="explicit",
                    page_ids=tuple(child_page_ids),
                )
            )
        else:
            raise ValueError(
                f"{field_name}.{page_id} must be 'default', 'all', or a list of page ids."
            )
        seen_page_ids.add(page_id)

    return entries


def _normalize_export_page_entries(
    raw_value,
    *,
    field_name: str,
) -> dict[str, ExportPageOverride]:
    """Normalize nested export page overrides keyed by leaf page id or group/child ids."""
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping.")

    normalized: dict[str, ExportPageOverride] = {}
    for raw_page_id, raw_page_cfg in raw_value.items():
        page_id = str(raw_page_id).strip().lower()
        if not page_id:
            raise ValueError(f"{field_name} contains an empty page id.")
        if not isinstance(raw_page_cfg, dict):
            raise ValueError(f"{field_name}.{page_id} must be a mapping.")

        is_leaf_override = any(
            str(key).strip().lower() in {"enabled", "parts"}
            or not isinstance(value, dict)
            for key, value in raw_page_cfg.items()
        )
        if is_leaf_override:
            normalized[page_id] = _normalize_export_page_override(
                raw_page_cfg,
                field_name=f"{field_name}.{page_id}",
            )
            continue

        child_entries = raw_page_cfg
        if set(raw_page_cfg) == {"children"}:
            raw_children = raw_page_cfg["children"]
            if not isinstance(raw_children, dict):
                raise ValueError(f"{field_name}.{page_id}.children must be a mapping.")
            child_entries = raw_children

        for raw_child_page_id, raw_child_cfg in child_entries.items():
            child_page_id = str(raw_child_page_id).strip().lower()
            if not child_page_id:
                raise ValueError(f"{field_name}.{page_id} contains an empty page id.")
            normalized[f"{page_id}.{child_page_id}"] = _normalize_export_page_override(
                raw_child_cfg,
                field_name=f"{field_name}.{page_id}.children.{child_page_id}",
            )
    return normalized


def _normalize_column_aliases(
    raw_value,
    *,
    field_name: str,
    default: list[str],
    allow_none: bool = False,
) -> list[str] | None:
    """Normalize a schema column alias config entry to an ordered list."""

    if raw_value is None:
        return None if allow_none else list(default)

    if isinstance(raw_value, str):
        candidates = [raw_value]
    elif isinstance(raw_value, list):
        candidates = raw_value
    else:
        raise ValueError(f"{field_name} must be a string or list of strings.")

    normalized: list[str] = []
    for item in candidates:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} entries must be strings.")
        token = item.strip()
        if not token or token in normalized:
            continue
        normalized.append(token)

    if not normalized:
        if allow_none:
            return None
        raise ValueError(f"{field_name} resolved to no values.")
    return normalized


def _normalize_label_mapping(
    raw_value,
    *,
    field_name: str,
) -> dict[str, str] | None:
    """Normalize a simple value->label mapping used for display overrides."""
    if raw_value is None:
        return None
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    normalized = {str(key): str(value) for key, value in raw_value.items()}
    return normalized or None


def _normalize_category_order(
    raw_value,
    *,
    field_name: str,
) -> str:
    if raw_value is None:
        return "data"
    token = str(raw_value).strip().lower()
    if token not in {"ascending", "descending", "data"}:
        raise ValueError(
            f"{field_name} must be one of 'ascending', 'descending', or 'data'."
        )
    return token


def _normalize_categories(
    raw_value,
    *,
    field_name: str,
) -> dict[str, CategorySpec]:
    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    categories: dict[str, CategorySpec] = {}
    for raw_category_id, raw_spec in raw_value.items():
        category_id = str(raw_category_id).strip()
        if not category_id:
            raise ValueError(f"{field_name} contains an empty category id.")
        if not isinstance(raw_spec, dict):
            raise ValueError(f"{field_name}.{category_id} must be a mapping.")

        mapping_raw = raw_spec.get("mapping")
        if mapping_raw is None:
            mapping_items: list[tuple[str, str]] = []
        else:
            if not isinstance(mapping_raw, dict):
                raise ValueError(
                    f"{field_name}.{category_id}.mapping must be a mapping."
                )
            mapping_items = [
                (str(raw_key), str(display_label))
                for raw_key, display_label in mapping_raw.items()
            ]
        spec = CategorySpec(
            mapping_items=tuple(mapping_items),
            labels_by_raw={
                raw_key: display_label for raw_key, display_label in mapping_items
            },
            raw_values_in_order=tuple(raw_key for raw_key, _ in mapping_items),
            fallback_order=_normalize_category_order(
                raw_spec.get("order"),
                field_name=f"{field_name}.{category_id}.order",
            ),
        )
        categories[category_id] = spec
    return categories


def _category_spec_from_mapping(
    mapping: dict[str, str] | None,
    *,
    fallback_order: str = "data",
) -> CategorySpec | None:
    if not mapping:
        return None
    mapping_items = [
        (str(raw_key), str(display_label)) for raw_key, display_label in mapping.items()
    ]
    return CategorySpec(
        mapping_items=tuple(mapping_items),
        labels_by_raw={
            raw_key: display_label for raw_key, display_label in mapping_items
        },
        raw_values_in_order=tuple(raw_key for raw_key, _ in mapping_items),
        fallback_order=fallback_order,
    )


def _category_spec_from_sequence(
    values: list[str] | tuple[str, ...] | None,
) -> CategorySpec | None:
    if not values:
        return None
    normalized = tuple(str(value) for value in values)
    return CategorySpec(
        mapping_items=(),
        labels_by_raw={},
        raw_values_in_order=normalized,
        fallback_order="data",
    )


def _category_specs_payload(
    categories: dict[str, CategorySpec],
) -> list[dict[str, Any]]:
    return [
        {
            "category_id": category_id,
            "mapping": [
                {"raw": raw_value, "label": display_label}
                for raw_value, display_label in spec.mapping_items
            ],
            "order": spec.fallback_order,
        }
        for category_id, spec in categories.items()
    ]


_DEFAULT_RUN_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
]


def _warn_ignored_legacy_key(
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


def _digest_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class StudentTypePersonSelector:
    """Optional person-side selector for one configured student type."""

    is_university: bool | None = None
    school_segment: tuple[str, ...] = ()
    SCHG: tuple[str, ...] = ()
    pstudent: tuple[str, ...] = ()


@dataclass(frozen=True)
class StudentTypeConfig:
    """Prepared student-type configuration shared by prepare and summaries."""

    label: str
    land_use_columns: tuple[str, ...]
    person: StudentTypePersonSelector | None = None


def _student_type_defaults_to_university(
    label: str,
    land_use_columns: tuple[str, ...],
) -> bool:
    text = f"{label} {' '.join(land_use_columns)}".lower()
    return "univ" in text or "college" in text


def _normalize_student_selector_values(
    raw_value,
    *,
    field_name: str,
) -> tuple[str, ...]:
    if isinstance(raw_value, (str, int, float, bool)):
        values = [raw_value]
    elif isinstance(raw_value, list):
        values = raw_value
    else:
        raise ValueError(f"{field_name} must be a scalar or list.")

    normalized: list[str] = []
    for value in values:
        token = str(value).strip()
        if not token or token in normalized:
            continue
        normalized.append(token)
    if not normalized:
        raise ValueError(f"{field_name} resolved to no values.")
    return tuple(normalized)


def _normalize_student_types(
    raw_value,
    *,
    field_name: str,
) -> list[StudentTypeConfig]:
    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise ValueError(f"{field_name} must be a list when provided.")

    normalized: list[StudentTypeConfig] = []
    for idx, raw_entry in enumerate(raw_value):
        entry_name = f"{field_name}[{idx}]"
        if not isinstance(raw_entry, dict):
            raise ValueError(f"{entry_name} must be a mapping.")

        label = str(raw_entry.get("label", "")).strip()
        if not label:
            raise ValueError(f"{entry_name}.label is required.")

        land_use_columns = _normalize_column_aliases(
            raw_entry.get("land_use_columns"),
            field_name=f"{entry_name}.land_use_columns",
            default=[],
        )

        person_raw = raw_entry.get("person")
        person_selector: StudentTypePersonSelector | None = None
        if person_raw is not None:
            if not isinstance(person_raw, dict):
                raise ValueError(f"{entry_name}.person must be a mapping.")
            allowed_keys = {"is_university", "school_segment", "SCHG", "pstudent"}
            unknown_keys = sorted(set(person_raw) - allowed_keys)
            if unknown_keys:
                raise ValueError(
                    f"{entry_name}.person contains unsupported keys: "
                    + ", ".join(unknown_keys)
                )

            is_university = person_raw.get("is_university")
            if is_university is not None and not isinstance(is_university, bool):
                raise ValueError(
                    f"{entry_name}.person.is_university must be true or false."
                )
            person_selector = StudentTypePersonSelector(
                is_university=is_university,
                school_segment=(
                    _normalize_student_selector_values(
                        person_raw["school_segment"],
                        field_name=f"{entry_name}.person.school_segment",
                    )
                    if "school_segment" in person_raw
                    else ()
                ),
                SCHG=(
                    _normalize_student_selector_values(
                        person_raw["SCHG"],
                        field_name=f"{entry_name}.person.SCHG",
                    )
                    if "SCHG" in person_raw
                    else ()
                ),
                pstudent=(
                    _normalize_student_selector_values(
                        person_raw["pstudent"],
                        field_name=f"{entry_name}.person.pstudent",
                    )
                    if "pstudent" in person_raw
                    else ()
                ),
            )

        normalized.append(
            StudentTypeConfig(
                label=label,
                land_use_columns=tuple(land_use_columns),
                person=person_selector,
            )
        )

    if len(normalized) > 2:
        for idx, entry in enumerate(normalized):
            if entry.person is None and not _student_type_defaults_to_university(
                entry.label, entry.land_use_columns
            ):
                raise ValueError(
                    f"{field_name}[{idx}].person is required for custom multi-school segmentation."
                )
    return normalized


@dataclass
class Config:
    """Normalized runtime configuration shared by summarize and dashboard code.

    ``Config`` is the single normalized contract used by raw run loading,
    summary generation, cache validation, live dashboard assembly, and
    standalone HTML export.
    """

    config_path: str
    config_digest: str
    prepare_config_digest: str
    summary_config_digest: str
    presentation_config_digest: str
    name: str
    dashboard_title: str
    dashboard_pages: list[DashboardPageConfigEntry] | None
    run_colors: list[str]
    missing_data_display: str
    summary_root: str
    weighting_modes: list[str]
    export_html: ExportHTMLSettings
    skimjoin: SkimjoinSettings
    prepare_vot_bins: PrepareVotBinsSettings

    files: dict[str, str]

    col_ptype: str
    col_hhsize: str
    col_auto_ownership: str
    col_num_workers: str
    col_num_adults: str
    col_sample_rate: Optional[str]
    col_household_id: list[str]
    col_person_id: list[str]
    col_tour_id: list[str]
    col_trip_id: list[str]
    col_tour_purpose: list[str]
    col_trip_purpose: list[str]
    col_tour_mode: list[str]
    col_trip_mode: list[str]
    col_tour_category: list[str]
    col_tour_start: list[str]
    col_tour_end: list[str]
    col_tour_duration: list[str]
    col_trip_depart: list[str]
    col_total_employment: list[str]
    col_income_segment: list[str]
    col_school_esc_outbound: list[str]
    col_school_esc_inbound: list[str]
    col_num_escortees: list[str]
    col_out_escorted_tour_ids: list[str]
    col_inb_escorted_tour_ids: list[str]
    col_out_escorting_type: list[str]
    col_inb_escorting_type: list[str]
    col_out_chauffeur_tour_id: list[str]
    col_inb_chauffeur_tour_id: list[str]
    categories: dict[str, CategorySpec]
    person_type_labels: Optional[dict[str, str]]
    transit_subsidy_labels: Optional[dict[str, str]]
    group_joint_tour_purposes: bool
    group_atwork_tour_purposes: bool
    group_school_tour_purposes: bool
    student_types: list[StudentTypeConfig]

    use_maz: bool
    maz_col: str
    taz_col: str

    geography_enabled: bool
    geography_landuse_col: Optional[str]
    geography_mapping: Optional[dict]

    skim_file: Optional[str]
    skim_matrix: str

    mode_order: Optional[list[str]]
    mode_groups: Optional[dict[str, list[str]]]

    runs: list[dict]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        """Load, validate, and normalize ``config.yaml`` into a ``Config``."""
        config_path = Path(path).resolve()
        config_bytes = config_path.read_bytes()
        raw = yaml.safe_load(config_bytes.decode("utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("config file must parse to a mapping.")

        summaries_cfg = raw.get("summaries") or {}
        if not isinstance(summaries_cfg, dict):
            raise ValueError("summaries must be a mapping when provided.")

        visualizer_cfg = raw.get("visualizer") or {}
        if not isinstance(visualizer_cfg, dict):
            raise ValueError("visualizer must be a mapping when provided.")

        files = raw.get("files", {})
        if not isinstance(files, dict):
            raise ValueError("files must be a mapping when provided.")
        file_defaults = {
            "households": "final_households",
            "persons": "final_persons",
            "tours": "final_tours",
            "trips": "final_trips",
            "joint_tour_participants": "final_joint_tour_participants",
            "land_use": "final_land_use",
        }
        for key, value in file_defaults.items():
            files.setdefault(key, value)

        cols = raw.get("columns", {})
        if not isinstance(cols, dict):
            raise ValueError("columns must be a mapping when provided.")
        zones = raw.get("zones", {})
        if not isinstance(zones, dict):
            raise ValueError("zones must be a mapping when provided.")

        geo = raw.get("geography", {})
        if not isinstance(geo, dict):
            raise ValueError("geography must be a mapping when provided.")
        prepare_cfg = raw.get("prepare", {})
        if prepare_cfg is None:
            prepare_cfg = {}
        if not isinstance(prepare_cfg, dict):
            raise ValueError("prepare must be a mapping when provided.")
        geo_enabled = bool(geo.get("enabled", False))
        geo_mapping = None
        if geo_enabled and "mapping" in geo:
            geo_mapping = {str(k): str(v) for k, v in geo["mapping"].items()}

        skim_cfg = raw.get("skim", {})
        if not isinstance(skim_cfg, dict):
            raise ValueError("skim must be a mapping when provided.")
        skimjoin = _normalize_skimjoin_settings(
            raw.get("skimjoin"),
            config_dir=config_path.parent,
        )
        prepare_vot_bins = _normalize_prepare_vot_bins(
            prepare_cfg.get("vot_bins"),
            field_name="prepare.vot_bins",
        )
        modes_cfg = raw.get("modes", {})
        if not isinstance(modes_cfg, dict):
            raise ValueError("modes must be a mapping when provided.")
        outputs_cfg = raw.get("outputs", {})
        if outputs_cfg is None:
            outputs_cfg = {}
        if not isinstance(outputs_cfg, dict):
            raise ValueError("outputs must be a mapping when provided.")

        if "dashboard_title" in raw and "dashboard_title" in visualizer_cfg:
            _warn_ignored_legacy_key(
                mapping=raw,
                key="dashboard_title",
                legacy_field_name="dashboard_title",
                replacement_field_name="visualizer.dashboard_title",
            )
        _warn_ignored_legacy_key(
            mapping=raw,
            key="dashboard_pages",
            legacy_field_name="dashboard_pages",
            replacement_field_name="visualizer.dashboard_pages",
        )
        _warn_ignored_legacy_key(
            mapping=raw,
            key="run_colors",
            legacy_field_name="run_colors",
            replacement_field_name="visualizer.run_colors",
        )
        _warn_ignored_legacy_key(
            mapping=outputs_cfg,
            key="summary_root",
            legacy_field_name="outputs.summary_root",
            replacement_field_name="summaries.root",
        )
        _warn_ignored_legacy_key(
            mapping=outputs_cfg,
            key="weighting_modes",
            legacy_field_name="outputs.weighting_modes",
            replacement_field_name="summaries.weighting_modes",
        )
        _warn_ignored_legacy_key(
            mapping=outputs_cfg,
            key="export_html",
            legacy_field_name="outputs.export_html",
            replacement_field_name="visualizer.export_html",
        )

        dashboard_pages_cfg = visualizer_cfg.get("dashboard_pages")
        if dashboard_pages_cfg is None:
            dashboard_pages = None
        else:
            dashboard_pages = _normalize_dashboard_page_entries(
                dashboard_pages_cfg,
                field_name="visualizer.dashboard_pages",
            )

        summary_root_raw = summaries_cfg.get("root", "artifacts/summary_cache")
        summary_root = Path(summary_root_raw)
        if not summary_root.is_absolute():
            summary_root = (config_path.parent / summary_root).resolve()

        weighting_modes_cfg = summaries_cfg.get(
            "weighting_modes",
            ["weighted", "unweighted"],
        )
        raw_weighting_modes = [
            str(mode).strip().lower() for mode in weighting_modes_cfg
        ]
        supported_weighting_modes = {"weighted", "unweighted"}
        invalid_weighting_modes = [
            mode
            for mode in raw_weighting_modes
            if mode and mode not in supported_weighting_modes
        ]
        if invalid_weighting_modes:
            raise ValueError(
                "Unsupported summaries.weighting_modes values: "
                + ", ".join(repr(mode) for mode in invalid_weighting_modes)
            )
        weighting_modes: list[str] = []
        for mode in raw_weighting_modes:
            if mode and mode not in weighting_modes:
                weighting_modes.append(mode)
        if not weighting_modes:
            weighting_modes = ["weighted", "unweighted"]

        raw_export_html_cfg = visualizer_cfg.get("export_html")
        export_html_present = raw_export_html_cfg is not None
        export_html_cfg = raw_export_html_cfg or {}
        if not isinstance(export_html_cfg, dict):
            raise ValueError("visualizer.export_html must be a mapping when provided.")
        _warn_ignored_legacy_key(
            mapping=export_html_cfg,
            key="weighting",
            legacy_field_name="visualizer.export_html.weighting",
            replacement_field_name="visualizer.export_html.dashboard.weighting",
        )
        _warn_ignored_legacy_key(
            mapping=export_html_cfg,
            key="values",
            legacy_field_name="visualizer.export_html.values",
            replacement_field_name="visualizer.export_html.dashboard.values",
        )
        export_enabled_raw = export_html_cfg.get("enabled")
        if export_enabled_raw is None:
            export_enabled = export_html_present
        elif isinstance(export_enabled_raw, bool):
            export_enabled = export_enabled_raw
        else:
            raise ValueError("visualizer.export_html.enabled must be true or false.")

        dashboard_cfg = export_html_cfg.get("dashboard")
        if dashboard_cfg is None:
            dashboard_cfg = {}
        elif not isinstance(dashboard_cfg, dict):
            raise ValueError("visualizer.export_html.dashboard must be a mapping.")

        pages_cfg = export_html_cfg.get("pages")
        pages_configured = pages_cfg is not None
        if pages_cfg is None:
            pages_cfg = {}
        normalized_pages = _normalize_export_page_entries(
            pages_cfg,
            field_name="visualizer.export_html.pages",
        )

        export_html = ExportHTMLSettings(
            enabled=export_enabled,
            dashboard=ExportDashboardSettings(
                weighting=_normalize_export_html_selection(
                    dashboard_cfg.get("weighting"),
                    field_name="visualizer.export_html.dashboard.weighting",
                    default=weighting_modes,
                    allowed=weighting_modes,
                ),
                values=_normalize_export_html_selection(
                    dashboard_cfg.get("values"),
                    field_name="visualizer.export_html.dashboard.values",
                    default=["percent", "count"],
                    allowed=["percent", "count"],
                ),
            ),
            pages=normalized_pages,
            exclude_pages=_normalize_excluded_ids(
                export_html_cfg.get("exclude_pages"),
                field_name="visualizer.export_html.exclude_pages",
            ),
            exclude_groups=_normalize_excluded_ids(
                export_html_cfg.get("exclude_groups"),
                field_name="visualizer.export_html.exclude_groups",
            ),
            pages_configured=pages_configured,
            default_selector_request=ExportSelectorRequest(mode="all"),
        )

        dashboard_title = visualizer_cfg.get("dashboard_title")
        if dashboard_title is None:
            dashboard_title = raw.get("dashboard_title", "ActivitySim Visualizer")
        run_colors = visualizer_cfg.get("run_colors", list(_DEFAULT_RUN_COLORS))
        if not isinstance(run_colors, list):
            raise ValueError("visualizer.run_colors must be a list when provided.")
        missing_data_display = (
            str(visualizer_cfg.get("missing_data_display", "card")).strip().lower()
        )
        if missing_data_display not in {"card", "blank"}:
            raise ValueError(
                "visualizer.missing_data_display must be either 'card' or 'blank'."
            )

        person_type_labels = _normalize_label_mapping(
            raw.get("person_types"),
            field_name="person_types",
        )
        transit_subsidy_labels = _normalize_label_mapping(
            raw.get("transit_subsidies"),
            field_name="transit_subsidies",
        )
        categories = _normalize_categories(
            raw.get("categories"),
            field_name="categories",
        )
        if "person_type" not in categories:
            legacy_person_type_spec = _category_spec_from_mapping(person_type_labels)
            if legacy_person_type_spec is not None:
                categories["person_type"] = legacy_person_type_spec
        if "transit_subsidy" not in categories:
            legacy_transit_subsidy_spec = _category_spec_from_mapping(
                transit_subsidy_labels
            )
            if legacy_transit_subsidy_spec is not None:
                categories["transit_subsidy"] = legacy_transit_subsidy_spec
        if "geography" not in categories and geo_mapping:
            legacy_geography_spec = _category_spec_from_mapping(geo_mapping)
            if legacy_geography_spec is not None:
                categories["geography"] = legacy_geography_spec
        if "mode" not in categories:
            legacy_mode_spec = _category_spec_from_sequence(modes_cfg.get("order"))
            if legacy_mode_spec is not None:
                categories["mode"] = legacy_mode_spec
        categories["escort"] = _normalize_escort_category_spec(
            categories.get("escort")
        )
        group_joint_tour_purposes = (
            _normalize_optional_bool(
                raw.get("group_joint_tour_purposes"),
                field_name="group_joint_tour_purposes",
            )
            if raw.get("group_joint_tour_purposes") is not None
            else True
        )
        group_atwork_tour_purposes = (
            _normalize_optional_bool(
                raw.get("group_atwork_tour_purposes"),
                field_name="group_atwork_tour_purposes",
            )
            if raw.get("group_atwork_tour_purposes") is not None
            else True
        )
        group_school_tour_purposes = (
            _normalize_optional_bool(
                raw.get("group_school_tour_purposes"),
                field_name="group_school_tour_purposes",
            )
            if raw.get("group_school_tour_purposes") is not None
            else True
        )
        student_types = _normalize_student_types(
            raw.get("student_types"),
            field_name="student_types",
        )

        config = cls(
            config_path=str(config_path),
            config_digest=hashlib.sha256(config_bytes).hexdigest(),
            prepare_config_digest="",
            summary_config_digest="",
            presentation_config_digest="",
            name=raw.get("name", ""),
            dashboard_title=str(dashboard_title),
            dashboard_pages=dashboard_pages,
            run_colors=run_colors,
            missing_data_display=missing_data_display,
            summary_root=str(summary_root),
            weighting_modes=weighting_modes,
            export_html=export_html,
            skimjoin=skimjoin,
            prepare_vot_bins=prepare_vot_bins,
            files=files,
            col_ptype=cols.get("ptype", "ptype"),
            col_hhsize=cols.get("hhsize", "hhsize"),
            col_auto_ownership=cols.get("auto_ownership", "auto_ownership"),
            col_num_workers=cols.get("num_workers", "num_workers"),
            col_num_adults=cols.get("num_adults", "num_adults"),
            col_sample_rate=cols.get("sample_rate") or None,
            col_household_id=_normalize_column_aliases(
                cols.get("household_id"),
                field_name="columns.household_id",
                default=["household_id"],
            ),
            col_person_id=_normalize_column_aliases(
                cols.get("person_id"),
                field_name="columns.person_id",
                default=["person_id"],
            ),
            col_tour_id=_normalize_column_aliases(
                cols.get("tour_id"),
                field_name="columns.tour_id",
                default=["tour_id"],
            ),
            col_trip_id=_normalize_column_aliases(
                cols.get("trip_id"),
                field_name="columns.trip_id",
                default=["trip_id"],
            ),
            col_tour_purpose=_normalize_column_aliases(
                cols.get("tour_purpose"),
                field_name="columns.tour_purpose",
                default=["tour_purpose", "primary_purpose", "tour_type", "purpose"],
            ),
            col_trip_purpose=_normalize_column_aliases(
                cols.get("trip_purpose"),
                field_name="columns.trip_purpose",
                default=["trip_purpose", "purpose"],
            ),
            col_tour_mode=_normalize_column_aliases(
                cols.get("tour_mode"),
                field_name="columns.tour_mode",
                default=["tour_mode"],
            ),
            col_trip_mode=_normalize_column_aliases(
                cols.get("trip_mode"),
                field_name="columns.trip_mode",
                default=["trip_mode"],
            ),
            col_tour_category=_normalize_column_aliases(
                cols.get("tour_category"),
                field_name="columns.tour_category",
                default=["tour_category"],
            ),
            col_tour_start=_normalize_column_aliases(
                cols.get("tour_start"),
                field_name="columns.tour_start",
                default=["start", "start_hour"],
            ),
            col_tour_end=_normalize_column_aliases(
                cols.get("tour_end"),
                field_name="columns.tour_end",
                default=["end", "end_hour"],
            ),
            col_tour_duration=_normalize_column_aliases(
                cols.get("tour_duration"),
                field_name="columns.tour_duration",
                default=["duration", "tourdur"],
            ),
            col_trip_depart=_normalize_column_aliases(
                cols.get("trip_depart"),
                field_name="columns.trip_depart",
                default=["depart", "depart_hour"],
            ),
            col_total_employment=_normalize_column_aliases(
                cols.get("total_employment"),
                field_name="columns.total_employment",
                default=[
                    "EMP_TOTAL",
                    "EMP_Total",
                    "EMPLOY_TOT",
                    "TOTEMP",
                    "total_employment",
                    "employment",
                ],
            ),
            col_income_segment=_normalize_column_aliases(
                cols.get("income_segment"),
                field_name="columns.income_segment",
                default=["income_segment", "income_broad", "income"],
            ),
            col_school_esc_outbound=_normalize_column_aliases(
                cols.get("school_esc_outbound"),
                field_name="columns.school_esc_outbound",
                default=["school_esc_outbound"],
            ),
            col_school_esc_inbound=_normalize_column_aliases(
                cols.get("school_esc_inbound"),
                field_name="columns.school_esc_inbound",
                default=["school_esc_inbound"],
            ),
            col_num_escortees=_normalize_column_aliases(
                cols.get("num_escortees"),
                field_name="columns.num_escortees",
                default=["num_escortees", "num_escorted"],
            ),
            col_out_escorted_tour_ids=_normalize_column_aliases(
                cols.get("out_escorted_tour_ids"),
                field_name="columns.out_escorted_tour_ids",
                default=["out_escorted_tour_ids"],
            ),
            col_inb_escorted_tour_ids=_normalize_column_aliases(
                cols.get("inb_escorted_tour_ids"),
                field_name="columns.inb_escorted_tour_ids",
                default=["inb_escorted_tour_ids"],
            ),
            col_out_escorting_type=_normalize_column_aliases(
                cols.get("out_escorting_type"),
                field_name="columns.out_escorting_type",
                default=["out_escorting_type"],
            ),
            col_inb_escorting_type=_normalize_column_aliases(
                cols.get("inb_escorting_type"),
                field_name="columns.inb_escorting_type",
                default=["inb_escorting_type"],
            ),
            col_out_chauffeur_tour_id=_normalize_column_aliases(
                cols.get("out_chauffeur_tour_id"),
                field_name="columns.out_chauffeur_tour_id",
                default=["out_chauffeur_tour_id"],
            ),
            col_inb_chauffeur_tour_id=_normalize_column_aliases(
                cols.get("inb_chauffeur_tour_id"),
                field_name="columns.inb_chauffeur_tour_id",
                default=["inb_chauffeur_tour_id"],
            ),
            categories=categories,
            person_type_labels=person_type_labels,
            transit_subsidy_labels=transit_subsidy_labels,
            group_joint_tour_purposes=group_joint_tour_purposes,
            group_atwork_tour_purposes=group_atwork_tour_purposes,
            group_school_tour_purposes=group_school_tour_purposes,
            student_types=student_types,
            use_maz=bool(zones.get("use_maz", True)),
            maz_col=zones.get("maz_col", "zone_id"),
            taz_col=zones.get("taz_col", "TAZ"),
            geography_enabled=geo_enabled,
            geography_landuse_col=geo.get("landuse_col") if geo_enabled else None,
            geography_mapping=geo_mapping,
            skim_file=skim_cfg.get("file"),
            skim_matrix=skim_cfg.get("matrix", "SOV_DIST__MD"),
            mode_order=modes_cfg.get("order"),
            mode_groups=modes_cfg.get("groups"),
            runs=raw.get("runs", []),
        )
        config.prepare_config_digest = _digest_payload(
            config.prepare_signature_payload()
        )
        config.summary_config_digest = _digest_payload(
            config.summary_signature_payload()
        )
        config.presentation_config_digest = _digest_payload(
            config.presentation_signature_payload()
        )
        return config

    def prepare_signature_payload(self) -> dict[str, Any]:
        """Return the config subset that changes prepared-table contents."""
        geography_payload: dict[str, Any] = {"enabled": self.geography_enabled}
        if self.geography_enabled:
            geography_spec = self.category_spec("geography")
            geography_payload["landuse_col"] = self.geography_landuse_col
            geography_payload["mapping"] = (
                dict(geography_spec.mapping_items)
                if geography_spec is not None and geography_spec.mapping_items
                else (
                    {
                        key: self.geography_mapping[key]
                        for key in sorted(self.geography_mapping)
                    }
                    if self.geography_mapping
                    else None
                )
            )
        effective_person_type_labels = (
            None
            if self.category_spec("person_type") is not None
            else self.person_type_labels
        )
        effective_transit_subsidy_labels = (
            None
            if self.category_spec("transit_subsidy") is not None
            else self.transit_subsidy_labels
        )
        effective_mode_order = (
            None if self.category_spec("mode") is not None else self.mode_order
        )
        return {
            "files": {key: self.files[key] for key in sorted(self.files)},
            "columns": {
                "ptype": self.col_ptype,
                "hhsize": self.col_hhsize,
                "auto_ownership": self.col_auto_ownership,
                "num_workers": self.col_num_workers,
                "num_adults": self.col_num_adults,
                "sample_rate": self.col_sample_rate,
                "household_id": list(self.col_household_id),
                "person_id": list(self.col_person_id),
                "tour_id": list(self.col_tour_id),
                "trip_id": list(self.col_trip_id),
                "tour_purpose": list(self.col_tour_purpose),
                "trip_purpose": list(self.col_trip_purpose),
                "tour_mode": list(self.col_tour_mode),
                "trip_mode": list(self.col_trip_mode),
                "tour_category": list(self.col_tour_category),
                "tour_start": list(self.col_tour_start),
                "tour_end": list(self.col_tour_end),
                "tour_duration": list(self.col_tour_duration),
                "trip_depart": list(self.col_trip_depart),
                "total_employment": list(self.col_total_employment),
                "income_segment": list(self.col_income_segment),
                "school_esc_outbound": list(self.col_school_esc_outbound),
                "school_esc_inbound": list(self.col_school_esc_inbound),
                "num_escortees": list(self.col_num_escortees),
                "out_escorted_tour_ids": list(self.col_out_escorted_tour_ids),
                "inb_escorted_tour_ids": list(self.col_inb_escorted_tour_ids),
                "out_escorting_type": list(self.col_out_escorting_type),
                "inb_escorting_type": list(self.col_inb_escorting_type),
                "out_chauffeur_tour_id": list(self.col_out_chauffeur_tour_id),
                "inb_chauffeur_tour_id": list(self.col_inb_chauffeur_tour_id),
            },
            "categories": _category_specs_payload(self.categories),
            "legacy_categories": {
                "person_type_labels": (
                    {
                        key: effective_person_type_labels[key]
                        for key in sorted(effective_person_type_labels)
                    }
                    if effective_person_type_labels
                    else None
                ),
                "transit_subsidy_labels": (
                    {
                        key: effective_transit_subsidy_labels[key]
                        for key in sorted(effective_transit_subsidy_labels)
                    }
                    if effective_transit_subsidy_labels
                    else None
                ),
                "mode_order": list(effective_mode_order)
                if effective_mode_order
                else None,
            },
            "tour_purpose_grouping": {
                "group_joint_tour_purposes": self.group_joint_tour_purposes,
                "group_atwork_tour_purposes": self.group_atwork_tour_purposes,
                "group_school_tour_purposes": self.group_school_tour_purposes,
            },
            "student_types": [
                {
                    "label": entry.label,
                    "land_use_columns": list(entry.land_use_columns),
                    "person": (
                        {
                            "is_university": entry.person.is_university,
                            "school_segment": list(entry.person.school_segment),
                            "SCHG": list(entry.person.SCHG),
                            "pstudent": list(entry.person.pstudent),
                        }
                        if entry.person is not None
                        else None
                    ),
                }
                for entry in self.student_types
            ],
            "zones": {
                "use_maz": self.use_maz,
                "maz_col": self.maz_col,
                "taz_col": self.taz_col,
            },
            "geography": geography_payload,
            "skim": {"matrix": self.skim_matrix},
            "skimjoin": {
                "enabled": self.skimjoin.enabled,
                "config_digest": self.skimjoin.config_digest,
            },
            "prepare": {
                "vot_bins": {
                    "enabled": self.prepare_vot_bins.enabled,
                    "source_column": self.prepare_vot_bins.source_column,
                    "output_column": self.prepare_vot_bins.output_column,
                    "fallback_value": self.prepare_vot_bins.fallback_value,
                    "mappings": {
                        run_name: {
                            key: value for key, value in sorted(run_mapping.items())
                        }
                        for run_name, run_mapping in sorted(
                            self.prepare_vot_bins.mappings.items()
                        )
                    },
                }
            },
        }

    def summary_signature_payload(self) -> dict[str, Any]:
        """Return the config subset that changes summary cache contents."""
        geography_payload: dict[str, Any] = {"enabled": self.geography_enabled}
        if self.geography_enabled:
            geography_spec = self.category_spec("geography")
            geography_payload["landuse_col"] = self.geography_landuse_col
            geography_payload["mapping"] = (
                dict(geography_spec.mapping_items)
                if geography_spec is not None and geography_spec.mapping_items
                else (
                    {
                        key: self.geography_mapping[key]
                        for key in sorted(self.geography_mapping)
                    }
                    if self.geography_mapping
                    else None
                )
            )
        effective_person_type_labels = (
            None
            if self.category_spec("person_type") is not None
            else self.person_type_labels
        )
        effective_transit_subsidy_labels = (
            None
            if self.category_spec("transit_subsidy") is not None
            else self.transit_subsidy_labels
        )
        effective_mode_order = (
            None if self.category_spec("mode") is not None else self.mode_order
        )
        return {
            "weighting_modes": list(self.weighting_modes),
            "files": {key: self.files[key] for key in sorted(self.files)},
            "columns": {
                "ptype": self.col_ptype,
                "hhsize": self.col_hhsize,
                "auto_ownership": self.col_auto_ownership,
                "num_workers": self.col_num_workers,
                "num_adults": self.col_num_adults,
                "sample_rate": self.col_sample_rate,
                "household_id": list(self.col_household_id),
                "person_id": list(self.col_person_id),
                "tour_id": list(self.col_tour_id),
                "trip_id": list(self.col_trip_id),
                "tour_purpose": list(self.col_tour_purpose),
                "trip_purpose": list(self.col_trip_purpose),
                "tour_mode": list(self.col_tour_mode),
                "trip_mode": list(self.col_trip_mode),
                "tour_category": list(self.col_tour_category),
                "tour_start": list(self.col_tour_start),
                "tour_end": list(self.col_tour_end),
                "tour_duration": list(self.col_tour_duration),
                "trip_depart": list(self.col_trip_depart),
                "total_employment": list(self.col_total_employment),
                "income_segment": list(self.col_income_segment),
                "school_esc_outbound": list(self.col_school_esc_outbound),
                "school_esc_inbound": list(self.col_school_esc_inbound),
                "num_escortees": list(self.col_num_escortees),
                "out_escorted_tour_ids": list(self.col_out_escorted_tour_ids),
                "inb_escorted_tour_ids": list(self.col_inb_escorted_tour_ids),
                "out_escorting_type": list(self.col_out_escorting_type),
                "inb_escorting_type": list(self.col_inb_escorting_type),
                "out_chauffeur_tour_id": list(self.col_out_chauffeur_tour_id),
                "inb_chauffeur_tour_id": list(self.col_inb_chauffeur_tour_id),
            },
            "categories": _category_specs_payload(self.categories),
            "person_type_labels": (
                {
                    key: effective_person_type_labels[key]
                    for key in sorted(effective_person_type_labels)
                }
                if effective_person_type_labels
                else None
            ),
            "transit_subsidy_labels": (
                {
                    key: effective_transit_subsidy_labels[key]
                    for key in sorted(effective_transit_subsidy_labels)
                }
                if effective_transit_subsidy_labels
                else None
            ),
            "tour_purpose_grouping": {
                "group_joint_tour_purposes": self.group_joint_tour_purposes,
                "group_atwork_tour_purposes": self.group_atwork_tour_purposes,
                "group_school_tour_purposes": self.group_school_tour_purposes,
            },
            "student_types": [
                {
                    "label": entry.label,
                    "land_use_columns": list(entry.land_use_columns),
                    "person": (
                        {
                            "is_university": entry.person.is_university,
                            "school_segment": list(entry.person.school_segment),
                            "SCHG": list(entry.person.SCHG),
                            "pstudent": list(entry.person.pstudent),
                        }
                        if entry.person is not None
                        else None
                    ),
                }
                for entry in self.student_types
            ],
            "zones": {
                "use_maz": self.use_maz,
                "maz_col": self.maz_col,
                "taz_col": self.taz_col,
            },
            "geography": geography_payload,
            "skim": {"matrix": self.skim_matrix},
            "modes": {
                "order": list(effective_mode_order) if effective_mode_order else None,
                "groups": (
                    [
                        (group_name, list(mode_names))
                        for group_name, mode_names in self.mode_groups.items()
                    ]
                    if self.mode_groups
                    else None
                ),
            },
            "skimjoin": {
                "enabled": self.skimjoin.enabled,
                "config_digest": self.skimjoin.config_digest,
            },
            "prepare": {
                "vot_bins": {
                    "enabled": self.prepare_vot_bins.enabled,
                    "source_column": self.prepare_vot_bins.source_column,
                    "output_column": self.prepare_vot_bins.output_column,
                    "fallback_value": self.prepare_vot_bins.fallback_value,
                    "mappings": {
                        run_name: {
                            key: value for key, value in sorted(run_mapping.items())
                        }
                        for run_name, run_mapping in sorted(
                            self.prepare_vot_bins.mappings.items()
                        )
                    },
                }
            },
        }

    def presentation_signature_payload(self) -> dict[str, Any]:
        """Return the config subset that only changes presentation behavior."""
        return {
            "dashboard_title": self.dashboard_title,
            "dashboard_pages": (
                [
                    {
                        "page_id": entry.page_id,
                        "mode": entry.mode,
                        "page_ids": list(entry.page_ids),
                    }
                    for entry in self.dashboard_pages
                ]
                if self.dashboard_pages is not None
                else None
            ),
            "run_colors": list(self.run_colors),
            "missing_data_display": self.missing_data_display,
            "categories": _category_specs_payload(self.categories),
            "export_html": {
                "enabled": self.export_html.enabled,
                "dashboard": {
                    "weighting": list(self.export_html.dashboard.weighting),
                    "values": list(self.export_html.dashboard.values),
                },
                "pages_configured": self.export_html.pages_configured,
                "exclude_pages": list(self.export_html.exclude_pages),
                "exclude_groups": list(self.export_html.exclude_groups),
                "pages": [
                    {
                        "page_id": page_id,
                        "enabled": override.enabled,
                        "selectors": {
                            selector_id: {
                                "mode": request.mode,
                                "values": list(request.values),
                            }
                            for selector_id, request in override.selector_requests.items()
                        },
                        "parts": {
                            part_id: {"enabled": part.enabled}
                            for part_id, part in override.parts.items()
                        },
                    }
                    for page_id, override in self.export_html.pages.items()
                ],
            },
        }

    def run_color(self, idx: int) -> str:
        """Return the configured display color for one run index."""
        return self.run_colors[idx % len(self.run_colors)]

    def category_spec(self, category_id: str) -> CategorySpec | None:
        """Return the canonical category spec for one category id."""
        return self.categories.get(str(category_id))

    def normalize_escort_value(self, raw_value) -> str:
        """Normalize one raw escort value to a canonical internal token."""
        normalized = _escort_normalization_key(raw_value)
        if normalized is None:
            return str(raw_value).strip()
        return normalized

    def escort_display_labels(self) -> dict[str, str]:
        """Return canonical escort-token display labels."""
        return {
            token: self.label_value("escort", token)
            for token in ("not_escorted", "pure_escort", "ride_share")
        }

    def label_value(self, category_id: str, raw_value) -> str:
        """Return the display label for one raw categorical value."""
        raw_value_str = str(raw_value)
        spec = self.category_spec(category_id)
        if spec is not None and raw_value_str in spec.labels_by_raw:
            return spec.labels_by_raw[raw_value_str]
        return raw_value_str

    def ordered_values(self, category_id: str, raw_values: list[str]) -> list[str]:
        """Return raw values in configured display order with extras appended."""
        spec = self.category_spec(category_id)
        values = [str(value) for value in raw_values]
        if spec is None:
            return values

        seen: set[str] = set()
        unique_values: list[str] = []
        for value in values:
            if value in seen:
                continue
            unique_values.append(value)
            seen.add(value)

        ordered = [value for value in spec.raw_values_in_order if value in seen]
        extras = [value for value in unique_values if value not in ordered]
        if spec.fallback_order == "ascending":
            extras = sorted(extras)
        elif spec.fallback_order == "descending":
            extras = sorted(extras, reverse=True)
        return ordered + extras

    def ordered_labels(self, category_id: str, raw_values: list[str]) -> list[str]:
        """Return display labels for raw values in canonical order."""
        return [
            self.label_value(category_id, raw_value)
            for raw_value in self.ordered_values(category_id, raw_values)
        ]

    def ordered_modes(self, modes_in_data: list[str]) -> list[str]:
        """Return modes in display order. Unknown modes appended at end."""
        return self.ordered_values("mode", modes_in_data)

    def apply_geo_mapping(self, series: pl.Series) -> pl.Series:
        """Apply geography mapping (value->name) to a string series."""
        spec = self.category_spec("geography")
        if spec is None:
            return series.cast(pl.Utf8)
        return series.cast(pl.Utf8).map_elements(
            lambda value: (
                self.label_value("geography", value) if value is not None else None
            ),
            return_dtype=pl.Utf8,
        )

    def person_type_label(self, value) -> str:
        """Return the display label for a person type value."""
        return self.label_value("person_type", value)

    def transit_subsidy_label(self, value) -> str:
        """Return the display label for a transit subsidy value."""
        return self.label_value("transit_subsidy", value)

    @staticmethod
    def _lookup_label(value, labels: dict[str, str] | None) -> str:
        """Return a configured display label, falling back to the raw value."""
        value_str = str(value)
        if labels and value_str in labels:
            return labels[value_str]
        return value_str
