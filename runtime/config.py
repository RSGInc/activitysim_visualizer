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
    child_page_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExportPageConfigEntry:
    """Normalized export page-selection entry from config."""

    page_id: str
    mode: str = "explicit"
    child_page_ids: tuple[str, ...] = field(default_factory=tuple)


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

    dashboard: ExportDashboardSettings = field(default_factory=ExportDashboardSettings)
    page_entries: list[ExportPageConfigEntry] = field(default_factory=list)
    pages: dict[str, dict[str, ExportSelectorRequest]] = field(default_factory=dict)
    grouped_pages: dict[str, dict[str, dict[str, ExportSelectorRequest]]] = field(
        default_factory=dict
    )
    pages_configured: bool = False

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
        child_id: str | None = None,
    ) -> ExportSelectorRequest:
        request = self.pages.get(page_id, {}).get(selector_id)
        if request is not None:
            return request
        if group_id is not None and child_id is not None:
            request = (
                self.grouped_pages.get(group_id, {})
                .get(child_id, {})
                .get(selector_id)
            )
            if request is not None:
                return request
        return ExportSelectorRequest()


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
                    f"{field_name}.{page_id} must be 'default', 'all', or a list of child ids."
                )
            entries.append(DashboardPageConfigEntry(page_id=page_id, mode=token))
        elif isinstance(raw_children, list):
            child_ids: list[str] = []
            for raw_child_id in raw_children:
                if not isinstance(raw_child_id, str):
                    raise ValueError(
                        f"{field_name}.{page_id} entries must be strings."
                    )
                child_id = raw_child_id.strip().lower()
                if not child_id or child_id in child_ids:
                    continue
                child_ids.append(child_id)
            if not child_ids:
                raise ValueError(f"{field_name}.{page_id} resolved to no child ids.")
            entries.append(
                DashboardPageConfigEntry(
                    page_id=page_id,
                    mode="explicit",
                    child_page_ids=tuple(child_ids),
                )
            )
        else:
            raise ValueError(
                f"{field_name}.{page_id} must be 'default', 'all', or a list of child ids."
            )
        seen_page_ids.add(page_id)

    return entries


def _normalize_export_page_entries(
    raw_value,
    *,
    field_name: str,
) -> tuple[
    list[ExportPageConfigEntry],
    dict[str, dict[str, ExportSelectorRequest]],
    dict[str, dict[str, dict[str, ExportSelectorRequest]]],
]:
    """Normalize export page config into page entries plus flat/group selector maps."""
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping.")

    entries: list[ExportPageConfigEntry] = []
    flat_selectors: dict[str, dict[str, ExportSelectorRequest]] = {}
    grouped_selectors: dict[str, dict[str, dict[str, ExportSelectorRequest]]] = {}

    for raw_page_id, raw_page_cfg in raw_value.items():
        page_id = str(raw_page_id).strip().lower()
        if not page_id:
            raise ValueError(f"{field_name} contains an empty page id.")
        if not isinstance(raw_page_cfg, dict):
            raise ValueError(f"{field_name}.{page_id} must be a mapping.")

        if "children" not in raw_page_cfg and "selection" not in raw_page_cfg:
            # Support a shorthand grouped-page form where child page ids map
            # directly to selector mappings, e.g.:
            #   long_term_choices:
            #     individual_choices: {}
            #     mandatory_location_choice:
            #       geography_level: all
            #
            # This is unambiguous because flat page selector requests are
            # strings/lists, not nested mappings.
            if raw_page_cfg and all(
                isinstance(raw_child_cfg, dict)
                for raw_child_cfg in raw_page_cfg.values()
            ):
                child_page_ids: list[str] = []
                normalized_child_selector_cfg: dict[
                    str, dict[str, ExportSelectorRequest]
                ] = {}
                for raw_child_id, raw_child_cfg in raw_page_cfg.items():
                    child_id = str(raw_child_id).strip().lower()
                    if not child_id:
                        raise ValueError(
                            f"{field_name}.{page_id} contains an empty child id."
                        )
                    child_page_ids.append(child_id)
                    normalized_selector_cfg: dict[str, ExportSelectorRequest] = {}
                    for raw_selector_id, raw_selector_cfg in raw_child_cfg.items():
                        selector_id = str(raw_selector_id).strip().lower()
                        if not selector_id:
                            raise ValueError(
                                f"{field_name}.{page_id}.{child_id} contains an empty selector id."
                            )
                        normalized_selector_cfg[selector_id] = (
                            _normalize_export_selector_request(
                                raw_selector_cfg,
                                field_name=f"{field_name}.{page_id}.{child_id}.{selector_id}",
                            )
                        )
                    normalized_child_selector_cfg[child_id] = normalized_selector_cfg

                entries.append(
                    ExportPageConfigEntry(
                        page_id=page_id,
                        mode="explicit",
                        child_page_ids=tuple(child_page_ids),
                    )
                )
                grouped_selectors[page_id] = normalized_child_selector_cfg
                continue

            normalized_selector_cfg: dict[str, ExportSelectorRequest] = {}
            for raw_selector_id, raw_selector_cfg in raw_page_cfg.items():
                selector_id = str(raw_selector_id).strip().lower()
                if not selector_id:
                    raise ValueError(
                        f"{field_name}.{page_id} contains an empty selector id."
                    )
                normalized_selector_cfg[selector_id] = _normalize_export_selector_request(
                    raw_selector_cfg,
                    field_name=f"{field_name}.{page_id}.{selector_id}",
                )
            entries.append(ExportPageConfigEntry(page_id=page_id))
            flat_selectors[page_id] = normalized_selector_cfg
            continue

        if set(raw_page_cfg) - {"children", "selection"}:
            invalid_keys = ", ".join(
                repr(str(key)) for key in sorted(set(raw_page_cfg) - {"children", "selection"})
            )
            raise ValueError(
                f"{field_name}.{page_id} only supports 'selection' and 'children' for grouped pages. Invalid keys: {invalid_keys}"
            )

        selection = raw_page_cfg.get("selection", "explicit")
        mode = "explicit"
        child_page_ids: list[str] = []
        if isinstance(selection, str):
            token = selection.strip().lower()
            if token in {"default", "all"}:
                mode = token
            elif token not in {"", "explicit"}:
                raise ValueError(
                    f"{field_name}.{page_id}.selection must be 'default', 'all', or omitted."
                )
        elif selection is not None:
            raise ValueError(
                f"{field_name}.{page_id}.selection must be 'default', 'all', or omitted."
            )

        raw_children_cfg = raw_page_cfg.get("children", {})
        if raw_children_cfg is None:
            raw_children_cfg = {}
        if not isinstance(raw_children_cfg, dict):
            raise ValueError(f"{field_name}.{page_id}.children must be a mapping.")

        normalized_child_selector_cfg: dict[str, dict[str, ExportSelectorRequest]] = {}
        for raw_child_id, raw_child_cfg in raw_children_cfg.items():
            child_id = str(raw_child_id).strip().lower()
            if not child_id:
                raise ValueError(
                    f"{field_name}.{page_id}.children contains an empty child id."
                )
            if not isinstance(raw_child_cfg, dict):
                raise ValueError(
                    f"{field_name}.{page_id}.children.{child_id} must be a mapping."
                )
            child_page_ids.append(child_id)
            normalized_selector_cfg = {}
            for raw_selector_id, raw_selector_cfg in raw_child_cfg.items():
                selector_id = str(raw_selector_id).strip().lower()
                if not selector_id:
                    raise ValueError(
                        f"{field_name}.{page_id}.children.{child_id} contains an empty selector id."
                    )
                normalized_selector_cfg[selector_id] = _normalize_export_selector_request(
                    raw_selector_cfg,
                    field_name=f"{field_name}.{page_id}.children.{child_id}.{selector_id}",
                )
            normalized_child_selector_cfg[child_id] = normalized_selector_cfg

        entries.append(
            ExportPageConfigEntry(
                page_id=page_id,
                mode=mode,
                child_page_ids=tuple(child_page_ids),
            )
        )
        grouped_selectors[page_id] = normalized_child_selector_cfg

    return entries, flat_selectors, grouped_selectors


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
    person_type_labels: Optional[dict[str, str]]

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
        geo_enabled = bool(geo.get("enabled", False))
        geo_mapping = None
        if geo_enabled and "mapping" in geo:
            geo_mapping = {str(k): str(v) for k, v in geo["mapping"].items()}

        skim_cfg = raw.get("skim", {})
        if not isinstance(skim_cfg, dict):
            raise ValueError("skim must be a mapping when provided.")
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

        export_html_cfg = visualizer_cfg.get("export_html") or {}
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

        dashboard_cfg = export_html_cfg.get("dashboard")
        if dashboard_cfg is None:
            dashboard_cfg = {}
        elif not isinstance(dashboard_cfg, dict):
            raise ValueError("visualizer.export_html.dashboard must be a mapping.")

        pages_cfg = export_html_cfg.get("pages")
        pages_configured = pages_cfg is not None
        if pages_cfg is None:
            pages_cfg = {}
        (
            normalized_page_entries,
            normalized_pages,
            normalized_grouped_pages,
        ) = _normalize_export_page_entries(
            pages_cfg,
            field_name="visualizer.export_html.pages",
        )

        export_html = ExportHTMLSettings(
            dashboard=ExportDashboardSettings(
                weighting=_normalize_export_html_selection(
                    dashboard_cfg.get("weighting"),
                    field_name="visualizer.export_html.dashboard.weighting",
                    default=[weighting_modes[0]],
                    allowed=weighting_modes,
                ),
                values=_normalize_export_html_selection(
                    dashboard_cfg.get("values"),
                    field_name="visualizer.export_html.dashboard.values",
                    default=["percent"],
                    allowed=["percent", "count"],
                ),
            ),
            page_entries=normalized_page_entries,
            pages=normalized_pages,
            grouped_pages=normalized_grouped_pages,
            pages_configured=pages_configured,
        )

        dashboard_title = visualizer_cfg.get("dashboard_title")
        if dashboard_title is None:
            dashboard_title = raw.get("dashboard_title", "ActivitySim Visualizer")
        run_colors = visualizer_cfg.get("run_colors", list(_DEFAULT_RUN_COLORS))
        if not isinstance(run_colors, list):
            raise ValueError("visualizer.run_colors must be a list when provided.")
        missing_data_display = str(
            visualizer_cfg.get("missing_data_display", "card")
        ).strip().lower()
        if missing_data_display not in {"card", "blank"}:
            raise ValueError(
                "visualizer.missing_data_display must be either 'card' or 'blank'."
            )

        person_type_labels = {
            str(k): str(v) for k, v in raw.get("person_types", {}).items()
        } or None

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
                default=["EMPLOY_TOT", "TOTEMP", "total_employment", "employment"],
            ),
            person_type_labels=person_type_labels,
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
            geography_payload["landuse_col"] = self.geography_landuse_col
            geography_payload["mapping"] = (
                {
                    key: self.geography_mapping[key]
                    for key in sorted(self.geography_mapping)
                }
                if self.geography_mapping
                else None
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
            },
            "zones": {
                "use_maz": self.use_maz,
                "maz_col": self.maz_col,
                "taz_col": self.taz_col,
            },
            "geography": geography_payload,
            "skim": {"matrix": self.skim_matrix},
        }

    def summary_signature_payload(self) -> dict[str, Any]:
        """Return the config subset that changes summary cache contents."""
        geography_payload: dict[str, Any] = {"enabled": self.geography_enabled}
        if self.geography_enabled:
            geography_payload["landuse_col"] = self.geography_landuse_col
            geography_payload["mapping"] = (
                {
                    key: self.geography_mapping[key]
                    for key in sorted(self.geography_mapping)
                }
                if self.geography_mapping
                else None
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
            },
            "person_type_labels": (
                {
                    key: self.person_type_labels[key]
                    for key in sorted(self.person_type_labels)
                }
                if self.person_type_labels
                else None
            ),
            "zones": {
                "use_maz": self.use_maz,
                "maz_col": self.maz_col,
                "taz_col": self.taz_col,
            },
            "geography": geography_payload,
            "skim": {"matrix": self.skim_matrix},
            "modes": {
                "order": list(self.mode_order) if self.mode_order else None,
                "groups": (
                    [
                        (group_name, list(mode_names))
                        for group_name, mode_names in self.mode_groups.items()
                    ]
                    if self.mode_groups
                    else None
                ),
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
                        "child_page_ids": list(entry.child_page_ids),
                    }
                    for entry in self.dashboard_pages
                ]
                if self.dashboard_pages is not None
                else None
            ),
            "run_colors": list(self.run_colors),
            "missing_data_display": self.missing_data_display,
            "export_html": {
                "dashboard": {
                    "weighting": list(self.export_html.dashboard.weighting),
                    "values": list(self.export_html.dashboard.values),
                },
                "pages_configured": self.export_html.pages_configured,
                "page_entries": [
                    {
                        "page_id": entry.page_id,
                        "mode": entry.mode,
                        "child_page_ids": list(entry.child_page_ids),
                    }
                    for entry in self.export_html.page_entries
                ],
                "pages": [
                    {
                        "page_id": page_id,
                        "selectors": {
                            selector_id: {
                                "mode": request.mode,
                                "values": list(request.values),
                            }
                            for selector_id, request in selectors.items()
                        },
                    }
                    for page_id, selectors in self.export_html.pages.items()
                ],
                "grouped_pages": [
                    {
                        "page_id": page_id,
                        "children": {
                            child_id: {
                                selector_id: {
                                    "mode": request.mode,
                                    "values": list(request.values),
                                }
                                for selector_id, request in selectors.items()
                            }
                            for child_id, selectors in children.items()
                        },
                    }
                    for page_id, children in self.export_html.grouped_pages.items()
                ],
            },
        }

    def run_color(self, idx: int) -> str:
        """Return the configured display color for one run index."""
        return self.run_colors[idx % len(self.run_colors)]

    def ordered_modes(self, modes_in_data: list[str]) -> list[str]:
        """Return modes in display order. Unknown modes appended at end."""
        if not self.mode_order:
            return modes_in_data
        ordered = [mode for mode in self.mode_order if mode in modes_in_data]
        remaining = [mode for mode in modes_in_data if mode not in ordered]
        return ordered + remaining

    def apply_geo_mapping(self, series: pl.Series) -> pl.Series:
        """Apply geography mapping (value->name) to a string series."""
        if not self.geography_mapping:
            return series.cast(pl.Utf8)
        mapping = self.geography_mapping
        return series.cast(pl.Utf8).map_elements(
            lambda value: (
                mapping.get(str(value), str(value)) if value is not None else None
            ),
            return_dtype=pl.Utf8,
        )

    def person_type_label(self, value) -> str:
        """Return the display label for a person type value."""
        value_str = str(value)
        if self.person_type_labels and value_str in self.person_type_labels:
            return self.person_type_labels[value_str]
        return value_str
