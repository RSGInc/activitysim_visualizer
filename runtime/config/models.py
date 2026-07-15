"""Normalized config contracts and config-domain behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

import polars as pl

from .common import normalize_run_selector_key


@dataclass(frozen=True)
class DashboardPageConfigEntry:
    """Normalized dashboard page-selection entry from config."""

    page_id: str
    mode: str = "explicit"
    page_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExportSelectorRequest:
    """Requested export values for one page-level selector."""

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
    """Normalized HTML export configuration."""

    enabled: bool = False
    output_path: str | None = None
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
        request = self.page_override(page_id, group_id=group_id).selector_requests.get(
            selector_id
        )
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
class PipelineSettings:
    """Canonical default workflow controls resolved from config."""

    steps: tuple[str, ...] = ("summarize", "dashboard")
    dashboard_mode: Literal["none", "live", "export", "host"] = "live"
    overwrite: bool = False

    def has_step(self, step: str) -> bool:
        return step in self.steps


@dataclass(frozen=True)
class SkimjoinSettings:
    """Optional runtime wiring for skim enrichment."""

    enabled: bool = False
    config_path: str | None = None
    config_digest: str | None = None
    normalized_config: Any | None = None
    resolved_skim_files: tuple[str, ...] = ()
    resolved_network_los_file: str | None = None
    create_hypothetical_skim_tables: bool = False
    failure_policy: Literal["record", "error"] = "record"


@dataclass(frozen=True)
class RunSkimjoinOverrides:
    """Optional per-run skimjoin overrides resolved from the main config."""

    config_path: str | None = None
    skim_files: tuple[str, ...] = ()
    network_los_file: str | None = None
    create_hypothetical_skim_tables: bool | None = None


@dataclass(frozen=True)
class PrepareVotBinsSettings:
    """Optional run-aware VOT normalization applied during prepare."""

    enabled: bool = False
    source_column: str = "income_segment"
    output_column: str = "vot_bin"
    fallback_value: str | None = None
    mappings: dict[str, dict[str, str]] = field(default_factory=dict)

    def mapping_for_run(self, run_label: str) -> dict[str, str] | None:
        return self.mappings.get(normalize_run_selector_key(run_label))


@dataclass(frozen=True)
class PrepareAutoSufficiencySettings:
    """Configurable household comparison basis for AUTOSUFF derivation."""

    basis: Literal["licensed_drivers", "workers", "adults"] = "licensed_drivers"


@dataclass(frozen=True)
class PrepareTimePeriodsSettings:
    """Optional prepared trip/tour period-label derivation."""

    enabled: bool = False
    network_los_file: str | None = None
    network_los_digest: str | None = None
    trip_period_number_column: str = "depart"
    tour_start_period_number_column: str = "start"
    tour_end_period_number_column: str = "end"


@dataclass(frozen=True)
class PrepareNonMotorizedDistanceSkimSettings:
    """Optional non-motorized distance lookup applied during prepare."""

    enabled: bool = False
    file: str | None = None
    file_digest: str | None = None
    matrix: str | None = None
    source_type: Literal["csv", "omx"] | None = None
    value_column: str = "DISTWALK"


@dataclass(frozen=True)
class CategorySpec:
    """Canonical display labels and ordering rules for one categorical domain."""

    mapping_items: tuple[tuple[str, str], ...] = ()
    labels_by_raw: dict[str, str] = field(default_factory=dict)
    raw_values_in_order: tuple[str, ...] = ()
    fallback_order: str = "data"


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


@dataclass
class Config:
    """Normalized runtime configuration shared by summarize and dashboard code."""

    config_path: str
    config_digest: str
    prepare_config_digest: str
    summary_config_digest: str
    presentation_config_digest: str
    name: str
    dashboard_title: str
    log_level: str
    pipeline: PipelineSettings
    dashboard_pages: list[DashboardPageConfigEntry] | None
    enable_maz_geographies: bool
    run_colors: list[str]
    missing_data_display: str
    bar_hover_mode: Literal["closest", "all"]
    density_hover_mode: Literal["closest", "all"]
    summary_root: str
    weighting_modes: list[str]
    export_html: ExportHTMLSettings
    skimjoin: SkimjoinSettings
    prepare_vot_bins: PrepareVotBinsSettings
    prepare_auto_sufficiency: PrepareAutoSufficiencySettings
    prepare_time_periods: PrepareTimePeriodsSettings
    prepare_non_motorized_distance_skim: PrepareNonMotorizedDistanceSkimSettings
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
    col_home_zone_id: list[str]
    col_workplace_zone_id: list[str]
    col_school_zone_id: list[str]
    col_has_license: list[str]
    col_mandatory_tour_frequency: list[str]
    col_is_student: list[str]
    col_is_university: list[str]
    col_school_segment: list[str]
    col_schg: list[str]
    col_pstudent: list[str]
    col_tour_origin: list[str]
    col_tour_destination: list[str]
    col_trip_origin: list[str]
    col_trip_destination: list[str]
    col_stop_frequency: list[str]
    col_trip_outbound: list[str]
    col_trip_num: list[str]
    col_pnr_zone_id: list[str]
    col_pnr_lot_capacity: list[str]
    col_is_worker: list[str]
    col_adult: list[str]
    col_day_id: list[str]
    col_day_weight: list[str]
    col_vehicle_id: list[str]
    col_vehicle_num: list[str]
    col_vehicle_type: list[str]
    col_school_esc_outbound: list[str]
    col_school_esc_inbound: list[str]
    col_num_escortees: list[str]
    col_out_escorted_tour_ids: list[str]
    col_inb_escorted_tour_ids: list[str]
    col_out_escorting_type: list[str]
    col_inb_escorting_type: list[str]
    col_out_chauffeur_tour_id: list[str]
    col_inb_chauffeur_tour_id: list[str]
    summary_categories: dict[str, CategorySpec]
    dashboard_labels: dict[str, CategorySpec]
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
    mode_groups: Optional[dict[str, list[str]]]
    pnr_tour_modes: list[str]
    runs: list[dict]
    summary_failure_policy: Literal["record", "error"] = "record"

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        from .loader import load_config_from_yaml

        return load_config_from_yaml(path, cls=cls)

    def prepare_signature_payload(self) -> dict[str, Any]:
        from .signatures import prepare_signature_payload

        return prepare_signature_payload(self)

    def summary_signature_payload(self) -> dict[str, Any]:
        from .signatures import summary_signature_payload

        return summary_signature_payload(self)

    def presentation_signature_payload(self) -> dict[str, Any]:
        from .signatures import presentation_signature_payload

        return presentation_signature_payload(self)

    def run_color(self, idx: int) -> str:
        return self.run_colors[idx % len(self.run_colors)]

    def skimjoin_step_enabled(self) -> bool:
        """Return whether the active pipeline includes integrated skimjoin."""
        return self.pipeline.has_step("skimjoin")

    def summary_category_spec(self, category_id: str) -> CategorySpec | None:
        return self.summary_categories.get(str(category_id))

    def dashboard_label_spec(self, category_id: str) -> CategorySpec | None:
        return self.dashboard_labels.get(str(category_id))

    def normalize_escort_value(self, raw_value) -> str:
        from .normalize_categories import escort_normalization_key

        normalized = escort_normalization_key(raw_value)
        if normalized is None:
            return str(raw_value).strip()
        return normalized

    def normalize_summary_value(self, category_id: str, raw_value) -> str:
        raw_value_str = str(raw_value)
        spec = self.summary_category_spec(category_id)
        if spec is not None and raw_value_str in spec.labels_by_raw:
            return spec.labels_by_raw[raw_value_str]
        return raw_value_str

    def escort_display_labels(self) -> dict[str, str]:
        return {
            token: self.label_value("escort", token)
            for token in ("not_escorted", "pure_escort", "ride_share")
        }

    def label_value(self, category_id: str, raw_value) -> str:
        raw_value_str = str(raw_value)
        spec = self.dashboard_label_spec(category_id)
        if spec is not None and raw_value_str in spec.labels_by_raw:
            return spec.labels_by_raw[raw_value_str]
        aggregate_defaults = {
            "all_person_types": "All Person Types",
            "all_tour_purposes": "All Tour Purposes",
            "all_geographies": "All Geographies",
        }
        if raw_value_str in aggregate_defaults:
            return aggregate_defaults[raw_value_str]
        return raw_value_str

    def ordered_values(self, category_id: str, raw_values: list[str]) -> list[str]:
        values = [str(value) for value in raw_values]
        seen: set[str] = set()
        unique_values: list[str] = []
        for value in values:
            if value in seen:
                continue
            unique_values.append(value)
            seen.add(value)

        spec = self.dashboard_label_spec(category_id)
        if spec is None:
            return unique_values

        ordered = [value for value in spec.raw_values_in_order if value in seen]
        extras = [value for value in unique_values if value not in ordered]
        if spec.fallback_order == "ascending":
            extras = sorted(extras)
        elif spec.fallback_order == "descending":
            extras = sorted(extras, reverse=True)
        return ordered + extras

    def ordered_labels(self, category_id: str, raw_values: list[str]) -> list[str]:
        return [
            self.label_value(category_id, raw_value)
            for raw_value in self.ordered_values(category_id, raw_values)
        ]

    def ordered_modes(self, modes_in_data: list[str]) -> list[str]:
        return self.ordered_values("mode", modes_in_data)

    def apply_geo_mapping(self, series: pl.Series) -> pl.Series:
        spec = self.summary_category_spec("geography")
        if spec is None:
            return series.cast(pl.Utf8)
        return series.cast(pl.Utf8).map_elements(
            lambda value: (
                self.normalize_summary_value("geography", value)
                if value is not None
                else None
            ),
            return_dtype=pl.Utf8,
        )

    def person_type_label(self, value) -> str:
        return self.label_value("person_type", value)

    def transit_subsidy_label(self, value) -> str:
        return self.label_value("transit_subsidy", value)

    @staticmethod
    def _lookup_label(value, labels: dict[str, str] | None) -> str:
        value_str = str(value)
        if labels and value_str in labels:
            return labels[value_str]
        return value_str
