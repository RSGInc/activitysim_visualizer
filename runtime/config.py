"""Shared runtime config models and YAML parsing.

This module may understand both ``summaries.*`` and ``visualizer.*`` config
sections because configuration is a cross-cutting runtime concern used by both
the summarizer and the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Literal, Optional

from activitysim_viz_logging import get_logger
import polars as pl
import yaml

LOGGER = get_logger("runtime.config")


FILE_MAPPING_DEFAULTS: dict[str, str] = {
    "households": "final_households",
    "persons": "final_persons",
    "tours": "final_tours",
    "trips": "final_trips",
    "joint_tour_participants": "final_joint_tour_participants",
    "land_use": "final_land_use",
}
PREPARED_TABLE_MAP_KEYS: tuple[str, ...] = tuple(FILE_MAPPING_DEFAULTS)
OPTIONAL_PREPARED_TABLE_IDS: set[str] = {"joint_tour_participants", "land_use"}


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
    segmentation_type: str | None = None
    segmentation_visibility: Literal[
        "full_only", "segments_only", "full_and_segments"
    ] | None = None

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
    resolved_skim_files: tuple[str, ...] = ()
    resolved_network_los_file: str | None = None


@dataclass(frozen=True)
class RunSkimjoinOverrides:
    """Optional per-run skimjoin overrides resolved from the main config."""

    config_path: str | None = None
    skim_files: tuple[str, ...] = ()
    network_los_file: str | None = None


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


def _normalize_optional_path_string(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> str | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    resolved_path = Path(raw_value).expanduser()
    if not resolved_path.is_absolute():
        resolved_path = (config_dir / resolved_path).resolve()
    return str(resolved_path)


def _normalize_run_skimjoin_overrides(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> RunSkimjoinOverrides:
    if raw_value in (None, {}):
        return RunSkimjoinOverrides()
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    config_path = _normalize_optional_path_string(
        raw_value.get("config_path"),
        field_name=f"{field_name}.config_path",
        config_dir=config_dir,
    )
    skim_files = tuple(
        _normalize_string_list(
            raw_value.get("skim_files"),
            field_name=f"{field_name}.skim_files",
        )
    )
    if skim_files:
        skim_files = tuple(
            str(
                (
                    Path(raw_path).expanduser()
                    if Path(raw_path).expanduser().is_absolute()
                    else (config_dir / Path(raw_path).expanduser()).resolve()
                )
            )
            for raw_path in skim_files
        )
    network_los_file = _normalize_optional_path_string(
        raw_value.get("network_los_file"),
        field_name=f"{field_name}.network_los_file",
        config_dir=config_dir,
    )
    return RunSkimjoinOverrides(
        config_path=config_path,
        skim_files=skim_files,
        network_los_file=network_los_file,
    )


def _validate_integrated_skim_files(
    skim_files: list[str],
    *,
    context_label: str,
) -> None:
    if not skim_files:
        raise ValueError(
            f"Integrated skimjoin for {context_label} requires at least one skim file after applying run overrides and skimjoin config defaults."
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


def _validate_required_period_mappings(
    normalized_config: Any,
    *,
    context_label: str,
) -> None:
    period_requires_mapping = any(
        "PERIOD" in getattr(rule, "dimensions_used", [])
        for rule in [
            *getattr(normalized_config, "trip_lookups", []),
            *getattr(normalized_config, "tour_lookups", []),
        ]
    )
    if not period_requires_mapping:
        return

    for rule in [*normalized_config.trip_lookups, *normalized_config.tour_lookups]:
        if "PERIOD" not in rule.dimensions_used:
            continue
        period_dimension = rule.dimensions.get("PERIOD")
        if period_dimension is None or period_dimension.values:
            continue
        raise ValueError(
            f"{context_label} requires period mapping for skimjoin dimension 'PERIOD', but no usable network_los_file or explicit dimensions.PERIOD.values were provided."
        )


def _load_resolved_skimjoin_settings(
    *,
    config_path: str,
    skim_files_override: tuple[str, ...] = (),
    network_los_file_override: str | None = None,
    context_label: str,
) -> SkimjoinSettings:
    from processor.skimjoin.config.io import load_config_file
    from processor.skimjoin.config.normalize import normalize_config
    from processor.skimjoin.config.validation import load_config

    resolved_config_path = Path(config_path).expanduser().resolve()
    if not resolved_config_path.exists():
        raise ValueError(
            f"{context_label} skimjoin.config_path does not exist: {resolved_config_path}"
        )

    skimjoin_data = load_config_file(resolved_config_path)
    if skim_files_override or network_los_file_override is not None:
        skimjoin_data = dict(skimjoin_data)
        project = dict(skimjoin_data.get("project") or {})
        if skim_files_override:
            project["skim_files"] = list(skim_files_override)
        if network_los_file_override is not None:
            network_los_file = Path(network_los_file_override).expanduser().resolve()
            if not network_los_file.exists():
                raise ValueError(
                    f"{context_label} skimjoin.network_los_file does not exist: {network_los_file}"
                )
            project["network_los_file"] = str(network_los_file)
        skimjoin_data["project"] = project

    explicit_config = load_config(
        skimjoin_data,
        require_activitysim_tables=False,
    )
    normalized_config = normalize_config(explicit_config)
    _validate_required_period_mappings(
        normalized_config,
        context_label=context_label,
    )
    skim_files = list(normalized_config.skim_files)
    _validate_integrated_skim_files(skim_files, context_label=context_label)
    project = explicit_config.project
    return SkimjoinSettings(
        enabled=True,
        config_path=str(resolved_config_path),
        config_digest=_digest_payload(normalized_config.model_dump(mode="python")),
        normalized_config=normalized_config,
        resolved_skim_files=tuple(skim_files),
        resolved_network_los_file=(
            None if project is None else project.network_los_file
        ),
    )


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
    resolved_config_path = _normalize_optional_path_string(
        raw_value.get("config_path"),
        field_name="skimjoin.config_path",
        config_dir=config_dir,
    )

    if not enabled:
        return SkimjoinSettings(
            enabled=False,
            config_path=resolved_config_path,
        )

    if resolved_config_path is None:
        return SkimjoinSettings(
            enabled=True,
            config_path=None,
        )
    return _load_resolved_skimjoin_settings(
        config_path=resolved_config_path,
        context_label="global",
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


def _warn_supported_legacy_key(
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


@dataclass(frozen=True)
class GeographyAggregationDefinition:
    """Normalized custom geography aggregation definition."""

    name: str
    source_zone_system: str
    lookup_rows: tuple[tuple[int, str], ...] = ()
    file: str | None = None
    zone_id_col: str | None = None
    geography_col: str | None = None


@dataclass(frozen=True)
class GeographyAggregationSettings:
    """Normalized geography aggregation settings."""

    enabled: bool = False
    aggregations: tuple[GeographyAggregationDefinition, ...] = ()


@dataclass(frozen=True)
class SegmentSpec:
    """One named segment definition."""

    id: str
    label: str
    values: tuple[object, ...]


@dataclass(frozen=True)
class PreparedColumnSegmentationSource:
    """Segment directly from a prepared-table column."""

    type: Literal["prepared_column"] = "prepared_column"
    column: str = ""
    source_table: str | None = None


@dataclass(frozen=True)
class CsvLookupSegmentationSource:
    """Segment from a CSV joined to one prepared table by key."""

    type: Literal["csv_lookup"] = "csv_lookup"
    file: str = ""
    join_source_table: str = ""
    join_source_key_column: str = ""
    csv_key_column: str = ""
    segment_value_column: str = ""
    lookup_rows: tuple[tuple[str, str], ...] = ()


SegmentationSourceConfig = PreparedColumnSegmentationSource | CsvLookupSegmentationSource


@dataclass(frozen=True)
class DashboardSegmentationSettings:
    """Presentation-only dashboard controls for segmented summaries."""

    segmentation_type: str | None = None
    visibility: Literal[
        "full_only", "segments_only", "full_and_segments"
    ] = "full_and_segments"


@dataclass(frozen=True)
class SegmentationDefinition:
    """One named segmentation type and its slicing rules."""

    name: str
    include_full: bool = True
    persist_segmented_prepared_tables: bool = False
    allow_overlapping: bool = False
    on_empty_segment: Literal["error", "warn", "skip"] = "warn"
    source: SegmentationSourceConfig | None = None
    segments: tuple[SegmentSpec, ...] = ()


@dataclass(frozen=True)
class SegmentationSettings:
    """Normalized multi-segmentation settings."""

    enabled: bool = False
    dashboard: DashboardSegmentationSettings = field(
        default_factory=DashboardSegmentationSettings
    )
    definitions: tuple[SegmentationDefinition, ...] = ()

    def definition_names(self) -> tuple[str, ...]:
        return tuple(definition.name for definition in self.definitions)

    def definition_by_name(self, name: str | None) -> SegmentationDefinition | None:
        if name is None:
            return None
        for definition in self.definitions:
            if definition.name == name:
                return definition
        return None


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


def _normalize_file_mapping(
    raw_value,
    *,
    field_name: str,
    defaults: dict[str, str] | None = None,
) -> dict[str, str]:
    """Normalize a canonical-table-to-filename mapping."""
    if raw_value is None:
        raw_value = {}
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    allowed_keys = set(FILE_MAPPING_DEFAULTS)
    invalid_keys = sorted(str(key) for key in raw_value if str(key) not in allowed_keys)
    if invalid_keys:
        raise ValueError(
            f"{field_name} contains unsupported table ids: "
            + ", ".join(repr(key) for key in invalid_keys)
        )

    normalized = dict(defaults or {})
    for raw_key, raw_value in raw_value.items():
        key = str(raw_key)
        if not isinstance(raw_value, str):
            raise ValueError(f"{field_name}.{key} must be a non-empty string.")
        token = raw_value.strip()
        if not token:
            raise ValueError(f"{field_name}.{key} must be a non-empty string.")
        normalized[key] = token
    return normalized


def _normalize_fallback_file_mapping(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> dict[str, str]:
    """Normalize optional fallback file paths for missing raw inputs."""
    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    allowed_keys = OPTIONAL_PREPARED_TABLE_IDS
    invalid_keys = sorted(str(key) for key in raw_value if str(key) not in allowed_keys)
    if invalid_keys:
        raise ValueError(
            f"{field_name} contains unsupported table ids: "
            + ", ".join(repr(key) for key in invalid_keys)
        )

    normalized: dict[str, str] = {}
    for raw_key, raw_path in raw_value.items():
        key = str(raw_key)
        if not isinstance(raw_path, str):
            raise ValueError(f"{field_name}.{key} must be a non-empty path string.")
        token = raw_path.strip()
        if not token:
            raise ValueError(f"{field_name}.{key} must be a non-empty path string.")
        suffix = Path(token).suffix.lower()
        if suffix not in {".parquet", ".csv"}:
            raise ValueError(
                f"{field_name}.{key} must end with '.parquet' or '.csv'."
            )
        resolved = Path(token).expanduser()
        if not resolved.is_absolute():
            resolved = (config_dir / resolved).resolve()
        normalized[key] = str(resolved)
    return normalized


def _normalize_prepared_output_file_format(
    raw_value,
    *,
    field_name: str,
) -> str:
    """Normalize the configured prepared output file format."""
    if raw_value is None:
        return "parquet"
    if not isinstance(raw_value, str):
        raise ValueError(f"{field_name} must be 'parquet' or 'csv'.")
    token = raw_value.strip().lower()
    if token not in {"parquet", "csv"}:
        raise ValueError(f"{field_name} must be 'parquet' or 'csv'.")
    return token


def _normalize_prepare_relationship_checks(
    raw_value,
    *,
    field_name: str,
) -> str:
    """Normalize prepared-table relationship validation behavior."""
    if raw_value is None:
        return "warn"
    if raw_value is False:
        return "off"
    if raw_value is True:
        raise ValueError(f"{field_name} must be 'off', 'warn', or 'error'.")
    if not isinstance(raw_value, str):
        raise ValueError(f"{field_name} must be 'off', 'warn', or 'error'.")
    token = raw_value.strip().lower()
    if token not in {"off", "warn", "error"}:
        raise ValueError(f"{field_name} must be 'off', 'warn', or 'error'.")
    return token


def _normalize_prepared_table_map(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> dict[str, str]:
    """Normalize canonical prepared table ids to resolved file paths."""
    if raw_value is None:
        raw_value = {}
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    invalid_keys = sorted(
        str(key) for key in raw_value if str(key) not in PREPARED_TABLE_MAP_KEYS
    )
    if invalid_keys:
        raise ValueError(
            f"{field_name} contains unsupported table ids: "
            + ", ".join(repr(key) for key in invalid_keys)
        )

    normalized: dict[str, str] = {}
    for raw_key, raw_path in raw_value.items():
        key = str(raw_key)
        if not isinstance(raw_path, str):
            raise ValueError(f"{field_name}.{key} must be a non-empty path string.")
        token = raw_path.strip()
        if not token:
            raise ValueError(f"{field_name}.{key} must be a non-empty path string.")
        suffix = Path(token).suffix.lower()
        if suffix not in {".parquet", ".csv"}:
            raise ValueError(
                f"{field_name}.{key} must end with '.parquet' or '.csv'."
            )
        resolved = Path(token).expanduser()
        if not resolved.is_absolute():
            resolved = (config_dir / resolved).resolve()
        normalized[key] = str(resolved)
    return normalized


def _normalize_runs(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> list[dict[str, Any]]:
    """Normalize run entries and validate optional per-run file mappings."""
    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise ValueError(f"{field_name} must be a list when provided.")

    normalized_runs: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(raw_value):
        if not isinstance(raw_entry, dict):
            raise ValueError(f"{field_name}[{index}] must be a mapping.")
        normalized_entry = dict(raw_entry)
        if "file_map" in raw_entry:
            normalized_entry["file_map"] = _normalize_file_mapping(
                raw_entry.get("file_map"),
                field_name=f"{field_name}[{index}].file_map",
            )
        if "prepared_table_map" in raw_entry:
            normalized_entry["prepared_table_map"] = _normalize_prepared_table_map(
                raw_entry.get("prepared_table_map"),
                field_name=f"{field_name}[{index}].prepared_table_map",
                config_dir=config_dir,
            )
            if "file_map" in raw_entry:
                raise ValueError(
                    f"{field_name}[{index}] cannot define both file_map and prepared_table_map."
                )
        if "skimjoin" in raw_entry:
            normalized_entry["skimjoin"] = _normalize_run_skimjoin_overrides(
                raw_entry.get("skimjoin"),
                field_name=f"{field_name}[{index}].skimjoin",
                config_dir=config_dir,
            )
        normalized_runs.append(normalized_entry)
    return normalized_runs


def resolve_run_skimjoin_settings(config: Config, run_entry: dict[str, Any]) -> SkimjoinSettings:
    """Resolve the effective skimjoin settings for one run entry."""
    if not config.skimjoin.enabled:
        return config.skimjoin

    run_label = str(
        run_entry.get("label", Path(str(run_entry.get("dir", ""))).name or "run")
    )
    raw_overrides = run_entry.get("skimjoin")
    if isinstance(raw_overrides, RunSkimjoinOverrides):
        overrides = raw_overrides
    elif raw_overrides in (None, {}):
        overrides = RunSkimjoinOverrides()
    else:
        # Defensive fallback for callers that bypass Config.from_yaml normalization.
        overrides = _normalize_run_skimjoin_overrides(
            raw_overrides,
            field_name=f"runs[{run_label}].skimjoin",
            config_dir=Path(config.config_path).resolve().parent,
        )

    effective_config_path = overrides.config_path or config.skimjoin.config_path
    if effective_config_path is None:
        raise ValueError(
            f"Skimjoin is enabled for run '{run_label}' but no skimjoin config_path could be resolved from run.skimjoin.config_path or global skimjoin.config_path."
        )

    if (
        overrides.config_path is None
        and not overrides.skim_files
        and overrides.network_los_file is None
        and config.skimjoin.config_path == effective_config_path
        and config.skimjoin.normalized_config is not None
    ):
        return config.skimjoin

    context_label = f"run '{run_label}'"
    return _load_resolved_skimjoin_settings(
        config_path=effective_config_path,
        skim_files_override=overrides.skim_files,
        network_los_file_override=overrides.network_los_file,
        context_label=context_label,
    )


def config_for_run(config: Config, run_entry: dict[str, Any]) -> Config:
    """Return a run-scoped config view with resolved skimjoin settings."""
    resolved_skimjoin = resolve_run_skimjoin_settings(config, run_entry)
    if resolved_skimjoin == config.skimjoin:
        return config
    return replace(config, skimjoin=resolved_skimjoin)


def _normalize_geography_zone_id(
    raw_value,
    *,
    field_name: str,
) -> int:
    if isinstance(raw_value, bool):
        raise ValueError(f"{field_name} must be an integer zone id.")
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        if raw_value.is_integer():
            return int(raw_value)
        raise ValueError(f"{field_name} must be an integer zone id.")
    token = str(raw_value).strip()
    if not token:
        raise ValueError(f"{field_name} must be a non-empty zone id.")
    try:
        return int(token)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer zone id.") from exc


def _normalize_geography_lookup_rows(
    rows: list[tuple[int, str]],
    *,
    field_name: str,
) -> tuple[tuple[int, str], ...]:
    if not rows:
        raise ValueError(f"{field_name} resolved to no geography mappings.")

    seen_zone_labels: dict[int, str] = {}
    normalized: list[tuple[int, str]] = []
    for zone_id, geography_label in rows:
        prior = seen_zone_labels.get(zone_id)
        if prior is not None and prior != geography_label:
            raise ValueError(
                f"{field_name} assigns zone id {zone_id} to multiple geography labels."
            )
        if prior is None:
            seen_zone_labels[zone_id] = geography_label
            normalized.append((zone_id, geography_label))
    normalized.sort(key=lambda item: (item[0], item[1]))
    return tuple(normalized)


def _normalize_inline_geography_mapping(
    raw_value,
    *,
    field_name: str,
) -> tuple[tuple[int, str], ...]:
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping.")

    rows: list[tuple[int, str]] = []
    for raw_label, raw_zone_ids in raw_value.items():
        geography_label = str(raw_label).strip()
        if not geography_label:
            raise ValueError(f"{field_name} contains a blank geography label.")
        if isinstance(raw_zone_ids, list):
            zone_values = raw_zone_ids
        else:
            zone_values = [raw_zone_ids]
        if not zone_values:
            raise ValueError(f"{field_name}.{geography_label} must list at least one zone id.")
        for idx, zone_id in enumerate(zone_values):
            rows.append(
                (
                    _normalize_geography_zone_id(
                        zone_id,
                        field_name=f"{field_name}.{geography_label}[{idx}]",
                    ),
                    geography_label,
                )
            )
    return _normalize_geography_lookup_rows(rows, field_name=field_name)


def _normalize_file_geography_mapping(
    raw_value: dict[str, Any],
    *,
    field_name: str,
    config_dir: Path,
) -> tuple[str, str, str, tuple[tuple[int, str], ...]]:
    file_raw = raw_value.get("file")
    zone_id_col = str(raw_value.get("zone_id_col", "")).strip()
    geography_col = str(raw_value.get("geography_col", "")).strip()
    if not isinstance(file_raw, str) or not file_raw.strip():
        raise ValueError(f"{field_name}.file must be a non-empty string.")
    if not zone_id_col:
        raise ValueError(f"{field_name}.zone_id_col is required with file-based mappings.")
    if not geography_col:
        raise ValueError(f"{field_name}.geography_col is required with file-based mappings.")

    resolved_path = Path(file_raw).expanduser()
    if not resolved_path.is_absolute():
        resolved_path = (config_dir / resolved_path).resolve()
    if not resolved_path.exists():
        raise ValueError(f"{field_name}.file does not exist: {resolved_path}")

    lookup = pl.read_csv(resolved_path)
    required_columns = {zone_id_col, geography_col}
    missing_columns = sorted(required_columns - set(lookup.columns))
    if missing_columns:
        raise ValueError(
            f"{field_name}.file is missing required columns: {', '.join(missing_columns)}"
        )

    rows: list[tuple[int, str]] = []
    for idx, row in enumerate(
        lookup.select([zone_id_col, geography_col]).iter_rows(named=True)
    ):
        geography_label = str(row[geography_col]).strip() if row[geography_col] is not None else ""
        if not geography_label:
            raise ValueError(
                f"{field_name}.file contains a blank geography label at row {idx + 1}."
            )
        rows.append(
            (
                _normalize_geography_zone_id(
                    row[zone_id_col],
                    field_name=f"{field_name}.file row {idx + 1} zone id",
                ),
                geography_label,
            )
        )

    return (
        str(resolved_path),
        zone_id_col,
        geography_col,
        _normalize_geography_lookup_rows(rows, field_name=f"{field_name}.file"),
    )


def _normalize_geography_aggregations(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> GeographyAggregationSettings:
    if raw_value is None:
        return GeographyAggregationSettings()
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    enabled = raw_value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(f"{field_name}.enabled must be true or false when provided.")

    aggregations_raw = raw_value.get("aggregations")
    if aggregations_raw is None:
        return GeographyAggregationSettings(enabled=enabled)
    if not isinstance(aggregations_raw, dict):
        raise ValueError(f"{field_name}.aggregations must be a mapping when provided.")

    aggregations: list[GeographyAggregationDefinition] = []
    for raw_name, raw_definition in aggregations_raw.items():
        name = str(raw_name).strip()
        entry_name = f"{field_name}.aggregations.{name or raw_name}"
        if not name:
            raise ValueError(f"{field_name}.aggregations contains a blank aggregation name.")
        if not isinstance(raw_definition, dict):
            raise ValueError(f"{entry_name} must be a mapping.")

        source_zone_system = str(
            raw_definition.get("source_zone_system", "")
        ).strip().lower()
        if source_zone_system not in {"maz", "taz"}:
            raise ValueError(f"{entry_name}.source_zone_system must be 'maz' or 'taz'.")

        has_inline_mapping = "mapping" in raw_definition
        has_file_mapping = "file" in raw_definition
        if has_inline_mapping == has_file_mapping:
            raise ValueError(
                f"{entry_name} must define exactly one of 'mapping' or 'file'."
            )

        if has_inline_mapping:
            aggregations.append(
                GeographyAggregationDefinition(
                    name=name,
                    source_zone_system=source_zone_system,
                    lookup_rows=_normalize_inline_geography_mapping(
                        raw_definition["mapping"],
                        field_name=f"{entry_name}.mapping",
                    ),
                )
            )
            continue

        file_path, zone_id_col, geography_col, lookup_rows = (
            _normalize_file_geography_mapping(
                raw_definition,
                field_name=entry_name,
                config_dir=config_dir,
            )
        )
        aggregations.append(
            GeographyAggregationDefinition(
                name=name,
                source_zone_system=source_zone_system,
                lookup_rows=lookup_rows,
                file=file_path,
                zone_id_col=zone_id_col,
                geography_col=geography_col,
            )
        )

    aggregations.sort(key=lambda entry: entry.name)
    return GeographyAggregationSettings(
        enabled=enabled,
        aggregations=tuple(aggregations),
    )


def _normalize_segment_values(
    raw_value,
    *,
    field_name: str,
) -> tuple[object, ...]:
    if isinstance(raw_value, list):
        values = raw_value
    else:
        values = [raw_value]
    if not values:
        raise ValueError(f"{field_name} must define at least one value.")
    return tuple(values)


def _normalize_segmentation_source(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> SegmentationSourceConfig:
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping.")

    source_type = str(raw_value.get("type", "prepared_column")).strip().lower()
    if source_type == "prepared_column":
        column = str(raw_value.get("column", "")).strip()
        if not column:
            raise ValueError(f"{field_name}.column is required.")
        source_table_raw = raw_value.get("source_table")
        source_table = (
            str(source_table_raw).strip() if source_table_raw is not None else None
        )
        if source_table == "":
            source_table = None
        if source_table is not None and source_table not in {
            "hh",
            "per",
            "tours",
            "trips",
            "land_use",
        }:
            raise ValueError(
                f"{field_name}.source_table must be one of hh, per, tours, trips, land_use."
            )
        return PreparedColumnSegmentationSource(
            column=column,
            source_table=source_table,
        )

    if source_type != "csv_lookup":
        raise ValueError(
            f"{field_name}.type must be 'prepared_column' or 'csv_lookup'."
        )

    file_raw = raw_value.get("file")
    if not isinstance(file_raw, str) or not file_raw.strip():
        raise ValueError(f"{field_name}.file must be a non-empty string.")
    join_raw = raw_value.get("join")
    if not isinstance(join_raw, dict):
        raise ValueError(f"{field_name}.join must be a mapping.")
    join_source_table = str(join_raw.get("source_table", "")).strip()
    join_source_key_column = str(join_raw.get("source_key_column", "")).strip()
    csv_key_column = str(join_raw.get("csv_key_column", "")).strip()
    segment_value_column = str(raw_value.get("segment_value_column", "")).strip()
    if join_source_table not in {"hh", "per", "tours", "trips", "land_use"}:
        raise ValueError(
            f"{field_name}.join.source_table must be one of hh, per, tours, trips, land_use."
        )
    if not join_source_key_column:
        raise ValueError(f"{field_name}.join.source_key_column is required.")
    if not csv_key_column:
        raise ValueError(f"{field_name}.join.csv_key_column is required.")
    if not segment_value_column:
        raise ValueError(f"{field_name}.segment_value_column is required.")

    resolved_path = Path(file_raw).expanduser()
    if not resolved_path.is_absolute():
        resolved_path = (config_dir / resolved_path).resolve()
    if not resolved_path.exists():
        raise ValueError(f"{field_name}.file does not exist: {resolved_path}")

    lookup = pl.read_csv(resolved_path)
    required_columns = {csv_key_column, segment_value_column}
    missing_columns = sorted(required_columns - set(lookup.columns))
    if missing_columns:
        raise ValueError(
            f"{field_name}.file is missing required columns: {', '.join(missing_columns)}"
        )

    seen_key_to_value: dict[str, str] = {}
    normalized_rows: list[tuple[str, str]] = []
    for idx, row in enumerate(
        lookup.select([csv_key_column, segment_value_column]).iter_rows(named=True)
    ):
        key = "" if row[csv_key_column] is None else str(row[csv_key_column]).strip()
        if not key:
            raise ValueError(
                f"{field_name}.file contains a blank join key at row {idx + 1}."
            )
        value = (
            "" if row[segment_value_column] is None else str(row[segment_value_column]).strip()
        )
        if not value:
            raise ValueError(
                f"{field_name}.file contains a blank segment value at row {idx + 1}."
            )
        prior = seen_key_to_value.get(key)
        if prior is not None and prior != value:
            raise ValueError(
                f"{field_name}.file assigns key {key!r} to multiple segment values."
            )
        if prior is None:
            seen_key_to_value[key] = value
            normalized_rows.append((key, value))

    if not normalized_rows:
        raise ValueError(f"{field_name}.file resolved to no lookup rows.")

    normalized_rows.sort(key=lambda item: (item[0], item[1]))
    return CsvLookupSegmentationSource(
        file=str(resolved_path),
        join_source_table=join_source_table,
        join_source_key_column=join_source_key_column,
        csv_key_column=csv_key_column,
        segment_value_column=segment_value_column,
        lookup_rows=tuple(normalized_rows),
    )


def _normalize_segmentation(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> SegmentationSettings:
    if raw_value is None:
        return SegmentationSettings()
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    enabled = raw_value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(f"{field_name}.enabled must be true or false.")
    if not enabled:
        return SegmentationSettings(enabled=False)

    dashboard_raw = raw_value.get("dashboard", {})
    if dashboard_raw is None:
        dashboard_raw = {}
    if not isinstance(dashboard_raw, dict):
        raise ValueError(f"{field_name}.dashboard must be a mapping when provided.")
    dashboard_segmentation_type = dashboard_raw.get("segmentation_type")
    if dashboard_segmentation_type is not None:
        dashboard_segmentation_type = str(dashboard_segmentation_type).strip().lower()
        if not dashboard_segmentation_type:
            dashboard_segmentation_type = None
    dashboard_visibility = str(
        dashboard_raw.get("visibility", "full_and_segments")
    ).strip().lower()
    if dashboard_visibility not in {"full_only", "segments_only", "full_and_segments"}:
        raise ValueError(
            f"{field_name}.dashboard.visibility must be one of full_only, segments_only, or full_and_segments."
        )
    definitions_raw = raw_value.get("definitions")
    if not isinstance(definitions_raw, dict) or not definitions_raw:
        raise ValueError(
            f"{field_name}.definitions must be a non-empty mapping when enabled."
        )

    normalized_definitions: list[SegmentationDefinition] = []
    seen_definition_names: set[str] = set()
    for raw_name, raw_definition in definitions_raw.items():
        definition_name = str(raw_name).strip().lower()
        entry_name = f"{field_name}.definitions.{raw_name}"
        if not definition_name:
            raise ValueError(f"{field_name}.definitions contains a blank name.")
        if definition_name != str(raw_name).strip():
            raise ValueError(f"{entry_name} name must already be normalized and lowercase.")
        if (
            re.sub(r"[^A-Za-z0-9._-]+", "-", definition_name)
            .strip("-_.")
            .lower()
            != definition_name
        ):
            raise ValueError(f"{entry_name} name must be path-safe.")
        if definition_name in seen_definition_names:
            raise ValueError(f"{entry_name} name must be unique.")
        seen_definition_names.add(definition_name)
        if not isinstance(raw_definition, dict):
            raise ValueError(f"{entry_name} must be a mapping.")

        include_full = raw_definition.get("include_full", True)
        if not isinstance(include_full, bool):
            raise ValueError(f"{entry_name}.include_full must be true or false.")

        persist_segmented_prepared_tables = raw_definition.get(
            "persist_segmented_prepared_tables", False
        )
        if not isinstance(persist_segmented_prepared_tables, bool):
            raise ValueError(
                f"{entry_name}.persist_segmented_prepared_tables must be true or false."
            )
        allow_overlapping = raw_definition.get("allow_overlapping", False)
        if not isinstance(allow_overlapping, bool):
            raise ValueError(f"{entry_name}.allow_overlapping must be true or false.")

        on_empty_segment = str(raw_definition.get("on_empty_segment", "warn")).strip().lower()
        if on_empty_segment not in {"error", "warn", "skip"}:
            raise ValueError(
                f"{entry_name}.on_empty_segment must be one of error, warn, or skip."
            )

        source = _normalize_segmentation_source(
            raw_definition.get("source"),
            field_name=f"{entry_name}.source",
            config_dir=config_dir,
        )

        segments_raw = raw_definition.get("segments")
        if not isinstance(segments_raw, list) or not segments_raw:
            raise ValueError(f"{entry_name}.segments must be a non-empty list.")

        normalized_segments: list[SegmentSpec] = []
        seen_segment_ids: set[str] = set()
        seen_values: dict[str, str] = {}
        for idx, raw_segment in enumerate(segments_raw):
            segment_name = f"{entry_name}.segments[{idx}]"
            if not isinstance(raw_segment, dict):
                raise ValueError(f"{segment_name} must be a mapping.")
            raw_segment_id = str(raw_segment.get("id", "")).strip()
            if not raw_segment_id:
                raise ValueError(f"{segment_name}.id is required.")
            normalized_id = raw_segment_id.lower()
            if normalized_id != raw_segment_id:
                raise ValueError(
                    f"{segment_name}.id must already be normalized and lowercase."
                )
            if (
                re.sub(r"[^A-Za-z0-9._-]+", "-", normalized_id)
                .strip("-_.")
                .lower()
                != normalized_id
            ):
                raise ValueError(f"{segment_name}.id must be path-safe.")
            if normalized_id in seen_segment_ids:
                raise ValueError(f"{segment_name}.id must be unique.")
            seen_segment_ids.add(normalized_id)
            label = str(raw_segment.get("label", "")).strip()
            if not label:
                raise ValueError(f"{segment_name}.label is required.")
            values = _normalize_segment_values(
                raw_segment.get("values"),
                field_name=f"{segment_name}.values",
            )
            if not allow_overlapping:
                for raw_value_token in values:
                    overlap_key = json.dumps(raw_value_token, sort_keys=True, default=str)
                    prior_segment = seen_values.get(overlap_key)
                    if prior_segment is not None:
                        raise ValueError(
                            f"{segment_name}.values overlaps with segment {prior_segment!r} while allow_overlapping is false."
                        )
                    seen_values[overlap_key] = normalized_id
            normalized_segments.append(
                SegmentSpec(id=normalized_id, label=label, values=values)
            )

        normalized_definitions.append(
            SegmentationDefinition(
                name=definition_name,
                include_full=include_full,
                persist_segmented_prepared_tables=persist_segmented_prepared_tables,
                allow_overlapping=allow_overlapping,
                on_empty_segment=on_empty_segment,
                source=source,
                segments=tuple(normalized_segments),
            )
        )

    normalized_definitions.sort(key=lambda definition: definition.name)
    available_definition_names = {definition.name for definition in normalized_definitions}
    if dashboard_segmentation_type is None:
        dashboard_segmentation_type = normalized_definitions[0].name
    if dashboard_segmentation_type not in available_definition_names:
        raise ValueError(
            f"{field_name}.dashboard.segmentation_type must name one configured definition."
        )

    return SegmentationSettings(
        enabled=enabled,
        dashboard=DashboardSegmentationSettings(
            segmentation_type=dashboard_segmentation_type,
            visibility=dashboard_visibility,
        ),
        definitions=tuple(normalized_definitions),
    )


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
    enable_maz_geographies: bool
    run_colors: list[str]
    missing_data_display: str
    summary_root: str
    weighting_modes: list[str]
    export_html: ExportHTMLSettings
    skimjoin: SkimjoinSettings
    prepare_vot_bins: PrepareVotBinsSettings
    prepare_output_file_format: str
    prepare_relationship_checks: str

    files: dict[str, str]
    fallback_files: dict[str, str]

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
    maz_col: list[str]
    taz_col: list[str]

    geography_enabled: bool
    geography_landuse_col: Optional[str]
    geography_mapping: Optional[dict]
    geography_aggregations: GeographyAggregationSettings
    segmentation: SegmentationSettings

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

        processor_cfg = raw.get("processor") or {}
        if not isinstance(processor_cfg, dict):
            raise ValueError("processor must be a mapping when provided.")

        summaries_cfg = raw.get("summaries") or {}
        if not isinstance(summaries_cfg, dict):
            raise ValueError("summaries must be a mapping when provided.")
        processor_summaries_cfg = processor_cfg.get("summaries") or {}
        if not isinstance(processor_summaries_cfg, dict):
            raise ValueError("processor.summaries must be a mapping when provided.")

        visualizer_cfg = raw.get("visualizer") or {}
        if not isinstance(visualizer_cfg, dict):
            raise ValueError("visualizer must be a mapping when provided.")

        files = _normalize_file_mapping(
            raw.get("files"),
            field_name="files",
            defaults=FILE_MAPPING_DEFAULTS,
        )
        fallback_files = _normalize_fallback_file_mapping(
            raw.get("fallback_files"),
            field_name="fallback_files",
            config_dir=config_path.parent,
        )
        runs = _normalize_runs(
            raw.get("runs"),
            field_name="runs",
            config_dir=config_path.parent,
        )

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
        prepare_output_cfg = prepare_cfg.get("output", {})
        if prepare_output_cfg is None:
            prepare_output_cfg = {}
        if not isinstance(prepare_output_cfg, dict):
            raise ValueError("prepare.output must be a mapping when provided.")
        prepare_validation_cfg = prepare_cfg.get("validation", {})
        if prepare_validation_cfg is None:
            prepare_validation_cfg = {}
        if not isinstance(prepare_validation_cfg, dict):
            raise ValueError("prepare.validation must be a mapping when provided.")
        geo_enabled = bool(geo.get("enabled", False))
        geo_mapping = None
        if geo_enabled and "mapping" in geo:
            geo_mapping = {str(k): str(v) for k, v in geo["mapping"].items()}
        if geo_enabled:
            geography_aggregations = _normalize_geography_aggregations(
                geo,
                field_name="geography",
                config_dir=config_path.parent,
            )
        else:
            geography_aggregations = GeographyAggregationSettings(enabled=False)
        segmentation = _normalize_segmentation(
            raw.get("segmentation"),
            field_name="segmentation",
            config_dir=config_path.parent,
        )

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
        prepare_output_file_format = _normalize_prepared_output_file_format(
            prepare_output_cfg.get("file_format"),
            field_name="prepare.output.file_format",
        )
        prepare_relationship_checks = _normalize_prepare_relationship_checks(
            prepare_validation_cfg.get("relationship_checks"),
            field_name="prepare.validation.relationship_checks",
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
            replacement_field_name="processor.root",
        )
        _warn_ignored_legacy_key(
            mapping=outputs_cfg,
            key="weighting_modes",
            legacy_field_name="outputs.weighting_modes",
            replacement_field_name="processor.summaries.weighting_modes",
        )
        _warn_ignored_legacy_key(
            mapping=outputs_cfg,
            key="export_html",
            legacy_field_name="outputs.export_html",
            replacement_field_name="visualizer.export_html",
        )
        _warn_supported_legacy_key(
            mapping=summaries_cfg,
            key="root",
            legacy_field_name="summaries.root",
            replacement_field_name="processor.root",
        )
        _warn_supported_legacy_key(
            mapping=summaries_cfg,
            key="weighting_modes",
            legacy_field_name="summaries.weighting_modes",
            replacement_field_name="processor.summaries.weighting_modes",
        )

        dashboard_pages_cfg = visualizer_cfg.get("dashboard_pages")
        if dashboard_pages_cfg is None:
            dashboard_pages = None
        else:
            dashboard_pages = _normalize_dashboard_page_entries(
                dashboard_pages_cfg,
                field_name="visualizer.dashboard_pages",
            )

        summary_root_raw = processor_cfg.get(
            "root",
            summaries_cfg.get("root", "artifacts/summary_cache"),
        )
        summary_root = Path(summary_root_raw)
        if not summary_root.is_absolute():
            summary_root = (config_path.parent / summary_root).resolve()

        weighting_modes_cfg = processor_summaries_cfg.get(
            "weighting_modes",
            summaries_cfg.get(
                "weighting_modes",
                ["weighted", "unweighted"],
            ),
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
                "Unsupported processor.summaries.weighting_modes values: "
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
                segmentation_type=(
                    None
                    if not segmentation.enabled
                    else (
                        (
                            str(dashboard_cfg.get("segmentation_type")).strip().lower()
                            if dashboard_cfg.get("segmentation_type") is not None
                            else segmentation.dashboard.segmentation_type
                        )
                    )
                ),
                segmentation_visibility=(
                    None
                    if not segmentation.enabled
                    else (
                        str(
                            dashboard_cfg.get(
                                "segmentation_visibility",
                                segmentation.dashboard.visibility,
                            )
                        )
                        .strip()
                        .lower()
                    )
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

        if export_html.dashboard.segmentation_type is not None:
            if (
                export_html.dashboard.segmentation_type
                not in segmentation.definition_names()
            ):
                raise ValueError(
                    "visualizer.export_html.dashboard.segmentation_type must name one configured segmentation definition."
                )
        if export_html.dashboard.segmentation_visibility is not None and (
            export_html.dashboard.segmentation_visibility
            not in {"full_only", "segments_only", "full_and_segments"}
        ):
            raise ValueError(
                "visualizer.export_html.dashboard.segmentation_visibility must be one of full_only, segments_only, or full_and_segments."
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
        enable_maz_geographies_raw = visualizer_cfg.get("enable_maz_geographies", False)
        if not isinstance(enable_maz_geographies_raw, bool):
            raise ValueError(
                "visualizer.enable_maz_geographies must be true or false when provided."
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
            enable_maz_geographies=enable_maz_geographies_raw,
            run_colors=run_colors,
            missing_data_display=missing_data_display,
            summary_root=str(summary_root),
            weighting_modes=weighting_modes,
            export_html=export_html,
            skimjoin=skimjoin,
            prepare_vot_bins=prepare_vot_bins,
            prepare_output_file_format=prepare_output_file_format,
            prepare_relationship_checks=prepare_relationship_checks,
            files=files,
            fallback_files=fallback_files,
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
            maz_col=_normalize_column_aliases(
                zones.get("maz_col"),
                field_name="zones.maz_col",
                default=["MAZ", "zone_id"],
            ),
            taz_col=_normalize_column_aliases(
                zones.get("taz_col"),
                field_name="zones.taz_col",
                default=["TAZ", "taz"],
            ),
            geography_enabled=geo_enabled,
            geography_landuse_col=geo.get("landuse_col") if geo_enabled else None,
            geography_mapping=geo_mapping,
            geography_aggregations=geography_aggregations,
            segmentation=segmentation,
            skim_file=skim_cfg.get("file"),
            skim_matrix=skim_cfg.get("matrix", "SOV_DIST__MD"),
            mode_order=modes_cfg.get("order"),
            mode_groups=modes_cfg.get("groups"),
            runs=runs,
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
        geography_payload["aggregations"] = [
            {
                "name": aggregation.name,
                "source_zone_system": aggregation.source_zone_system,
                "file": aggregation.file,
                "zone_id_col": aggregation.zone_id_col,
                "geography_col": aggregation.geography_col,
                "lookup_rows": [
                    {"zone_id": zone_id, "geography_id": geography_id}
                    for zone_id, geography_id in aggregation.lookup_rows
                ],
            }
            for aggregation in self.geography_aggregations.aggregations
        ]
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
                "maz_col": list(self.maz_col),
                "taz_col": list(self.taz_col),
            },
            "geography": geography_payload,
            "skim": {"matrix": self.skim_matrix},
            "skimjoin": {
                "enabled": self.skimjoin.enabled,
                "config_digest": self.skimjoin.config_digest,
            },
            "prepare": {
                "output": {
                    "file_format": self.prepare_output_file_format,
                },
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
        geography_payload["aggregations"] = [
            {
                "name": aggregation.name,
                "source_zone_system": aggregation.source_zone_system,
                "file": aggregation.file,
                "zone_id_col": aggregation.zone_id_col,
                "geography_col": aggregation.geography_col,
                "lookup_rows": [
                    {"zone_id": zone_id, "geography_id": geography_id}
                    for zone_id, geography_id in aggregation.lookup_rows
                ],
            }
            for aggregation in self.geography_aggregations.aggregations
        ]
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
        segmentation_payload: dict[str, Any] = {"enabled": self.segmentation.enabled}
        if self.segmentation.enabled:
            segmentation_payload["definitions"] = [
                {
                    "name": definition.name,
                    "include_full": definition.include_full,
                    "persist_segmented_prepared_tables": definition.persist_segmented_prepared_tables,
                    "allow_overlapping": definition.allow_overlapping,
                    "on_empty_segment": definition.on_empty_segment,
                    "source": (
                        {
                            "type": "prepared_column",
                            "column": definition.source.column,
                            "source_table": definition.source.source_table,
                        }
                        if isinstance(definition.source, PreparedColumnSegmentationSource)
                        else {
                            "type": "csv_lookup",
                            "file": definition.source.file,
                            "join_source_table": definition.source.join_source_table,
                            "join_source_key_column": definition.source.join_source_key_column,
                            "csv_key_column": definition.source.csv_key_column,
                            "segment_value_column": definition.source.segment_value_column,
                            "lookup_rows": [
                                {"key": key, "value": value}
                                for key, value in definition.source.lookup_rows
                            ],
                        }
                    ),
                    "segments": [
                        {
                            "id": segment.id,
                            "label": segment.label,
                            "values": list(segment.values),
                        }
                        for segment in definition.segments
                    ],
                }
                for definition in self.segmentation.definitions
            ]
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
                "maz_col": list(self.maz_col),
                "taz_col": list(self.taz_col),
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
            "segmentation": segmentation_payload,
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
            "enable_maz_geographies": self.enable_maz_geographies,
            "run_colors": list(self.run_colors),
            "missing_data_display": self.missing_data_display,
            "segmentation": {
                "enabled": self.segmentation.enabled,
                "dashboard": {
                    "segmentation_type": self.segmentation.dashboard.segmentation_type,
                    "visibility": self.segmentation.dashboard.visibility,
                },
            },
            "categories": _category_specs_payload(self.categories),
            "export_html": {
                "enabled": self.export_html.enabled,
                "dashboard": {
                    "weighting": list(self.export_html.dashboard.weighting),
                    "values": list(self.export_html.dashboard.values),
                    "segmentation_type": self.export_html.dashboard.segmentation_type,
                    "segmentation_visibility": self.export_html.dashboard.segmentation_visibility,
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
