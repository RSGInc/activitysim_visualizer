from __future__ import annotations

from fnmatch import fnmatch
from typing import Any, Literal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MissingPolicy = Literal["error", "warn", "set_null"]
AggregationMethod = Literal["sum", "mean", "min", "max", "first", "last"]


class DimensionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_column: str
    values: dict[str, str] = Field(default_factory=dict)

    @field_validator("values", mode="before")
    @classmethod
    def _normalize_values(cls, value: Any) -> dict[str, str]:
        if value in (None, {}):
            return {}
        if not isinstance(value, dict):
            raise TypeError("Dimension values must be a mapping.")
        return {str(key): str(mapped) for key, mapped in value.items()}


class ActivitySimConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trips_table: str
    tours_table: str | None = None
    mode_column: str = "trip_mode"
    tour_id_column: str = "tour_id"
    outbound_column: str = "outbound"


class DefaultsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: str = "origin"
    destination: str = "destination"
    output_prefix: str = "skim_"
    missing_matrix_policy: MissingPolicy = "error"
    missing_od_policy: MissingPolicy = "error"


class ZoneMappingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lookup_name: str | None = None
    file_lookup_names: dict[str, str] = Field(default_factory=dict)
    missing_zone_policy: MissingPolicy = "error"

    @field_validator("file_lookup_names", mode="before")
    @classmethod
    def _normalize_file_lookup_names(cls, value: Any) -> dict[str, str]:
        if value in (None, {}):
            return {}
        if not isinstance(value, dict):
            raise TypeError("zone_mapping.file_lookup_names must be a mapping.")
        return {str(pattern): str(name) for pattern, name in value.items()}

    def resolve_lookup_name(self, file_path: str | None) -> str | None:
        if not file_path:
            return self.lookup_name
        path_text = str(file_path)
        file_name = Path(path_text).name
        for pattern, lookup_name in self.file_lookup_names.items():
            if fnmatch(path_text, pattern) or fnmatch(file_name, pattern):
                return lookup_name
        return self.lookup_name


class TourAggregationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["aggregate_trips"] = "aggregate_trips"
    aggregations: dict[str, AggregationMethod] = Field(default_factory=dict)
    directional_outputs: dict[str, bool] = Field(default_factory=dict)


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skim_files: list[str] = Field(default_factory=list)
    trips_table: str | None = None
    tours_table: str | None = None
    network_los_file: str | None = None
    output_dir: str | None = None


class ExplicitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: ProjectConfig | None = None
    skim_files: list[str]
    activitysim: ActivitySimConfig
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    zone_mapping: ZoneMappingConfig = Field(default_factory=ZoneMappingConfig)
    dimensions: dict[str, DimensionConfig] = Field(default_factory=dict)
    ignore_modes: list[str] = Field(default_factory=list)
    modes: dict[str, dict[str, Any]]
    tour_aggregation: TourAggregationConfig = Field(default_factory=TourAggregationConfig)

    @field_validator("ignore_modes", mode="before")
    @classmethod
    def _normalize_ignore_modes(cls, value: Any) -> list[str]:
        if value in (None, []):
            return []
        if not isinstance(value, list):
            raise TypeError("ignore_modes must be a list.")
        return [str(item) for item in value]

    @model_validator(mode="before")
    @classmethod
    def _promote_project_paths(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        project = dict(data.get("project") or {})
        if "skim_files" not in data and project.get("skim_files"):
            data["skim_files"] = list(project["skim_files"])
        activitysim = dict(data.get("activitysim") or {})
        if "trips_table" not in activitysim and project.get("trips_table") is not None:
            activitysim["trips_table"] = project["trips_table"]
        if "tours_table" not in activitysim and project.get("tours_table") is not None:
            activitysim["tours_table"] = project["tours_table"]
        data["activitysim"] = activitysim
        return data


class NormalizedLookupRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    mode: str
    component: str
    output: str
    matrix: str
    origin: str
    destination: str
    when: dict[str, Any] = Field(default_factory=dict)
    dimensions_used: list[str] = Field(default_factory=list)
    dimensions: dict[str, DimensionConfig] = Field(default_factory=dict)
    missing_matrix_policy: MissingPolicy = "error"
    missing_od_policy: MissingPolicy = "error"


class NormalizedConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skim_files: list[str]
    activitysim: ActivitySimConfig
    defaults: DefaultsConfig
    zone_mapping: ZoneMappingConfig
    ignore_modes: list[str]
    tour_aggregation: TourAggregationConfig
    lookups: list[NormalizedLookupRule]
    segment_validations: dict[str, dict[str, Any]] = Field(default_factory=dict)
    failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    referenced_matrices: list[str] = Field(default_factory=list)
