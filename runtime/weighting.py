"""Versioned weighting-mode definitions and extension discovery."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from importlib import import_module, metadata
import re
from types import MappingProxyType, ModuleType
from typing import Any, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from processor.models import RunData
    from runtime.config.models import Config


WeightingTransform = Callable[["RunData", "Config | None"], "RunData"]
ExternalSummaryPolicy = Literal["copy", "reject"]

_COLUMN_MODE_TABLES = {
    "households": "hh",
    "persons": "per",
    "trips": "trips",
}


@dataclass(frozen=True)
class WeightingModeDefinition:
    """One weighting mode's stable identity and prepared-run transform."""

    mode_id: str
    label: str
    transform: WeightingTransform
    version: str
    required_columns: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    external_summary_policy: ExternalSummaryPolicy = "reject"
    default_enabled: bool = False

    def __post_init__(self) -> None:
        mode_id = str(self.mode_id).strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", mode_id):
            raise ValueError(
                "weighting mode_id must start with a letter and contain only "
                "lowercase letters, digits, underscores, or hyphens."
            )
        label = str(self.label).strip()
        if not label:
            raise ValueError(f"weighting mode {mode_id!r} requires a non-empty label.")
        version = str(self.version).strip()
        if not version:
            raise ValueError(
                f"weighting mode {mode_id!r} requires a non-empty version."
            )
        if not callable(self.transform):
            raise TypeError(f"weighting mode {mode_id!r} transform must be callable.")
        if self.external_summary_policy not in {"copy", "reject"}:
            raise ValueError(
                f"weighting mode {mode_id!r} external_summary_policy must be "
                "'copy' or 'reject'."
            )

        if not isinstance(self.required_columns, Mapping):
            raise TypeError(
                f"weighting mode {mode_id!r} required_columns must be a mapping."
            )
        normalized_requirements: dict[str, tuple[str, ...]] = {}
        for table_name, columns in self.required_columns.items():
            normalized_table = str(table_name).strip()
            if not normalized_table:
                raise ValueError(
                    f"weighting mode {mode_id!r} contains an empty required table name."
                )
            if isinstance(columns, (str, bytes)):
                raise TypeError(
                    f"weighting mode {mode_id!r} required columns for "
                    f"{normalized_table!r} must be a sequence, not a string."
                )
            normalized_columns = tuple(
                dict.fromkeys(
                    str(column).strip() for column in columns if str(column).strip()
                )
            )
            if normalized_columns:
                normalized_requirements[normalized_table] = normalized_columns

        object.__setattr__(self, "mode_id", mode_id)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "version", version)
        object.__setattr__(
            self,
            "required_columns",
            MappingProxyType(normalized_requirements),
        )

    def validate_run(self, run: "RunData") -> None:
        """Fail clearly when a mode's source columns are not available."""
        for table_name, columns in self.required_columns.items():
            table = getattr(run, table_name, None)
            if table is None or not hasattr(table, "columns"):
                raise ValueError(
                    f"Weighting mode {self.mode_id!r} requires prepared table "
                    f"{table_name!r}, but the table is unavailable."
                )
            missing = [column for column in columns if column not in table.columns]
            if missing:
                raise ValueError(
                    f"Weighting mode {self.mode_id!r} requires columns on "
                    f"{table_name!r}: {', '.join(missing)}"
                )

    def apply(self, run: "RunData", config: "Config | None") -> "RunData":
        self.validate_run(run)
        transformed = self.transform(run, config)
        from processor.models import RunData

        if not isinstance(transformed, RunData):
            raise TypeError(
                f"Weighting mode {self.mode_id!r} transform returned "
                f"{type(transformed).__name__}; expected RunData."
            )
        return transformed

    def signature_payload(self) -> dict[str, object]:
        return {
            "mode_id": self.mode_id,
            "version": self.version,
            "required_columns": {
                table_name: list(columns)
                for table_name, columns in sorted(self.required_columns.items())
            },
            "external_summary_policy": self.external_summary_policy,
        }


class WeightingModeRegistry:
    """Ordered registry shared by config, processor, dashboard, and export."""

    def __init__(self) -> None:
        self._definitions: OrderedDict[str, WeightingModeDefinition] = OrderedDict()

    def register(self, definition: WeightingModeDefinition) -> WeightingModeDefinition:
        if not isinstance(definition, WeightingModeDefinition):
            raise TypeError(
                "weighting registry entries must be WeightingModeDefinition objects."
            )
        if definition.mode_id in self._definitions:
            raise ValueError(f"Duplicate weighting mode id {definition.mode_id!r}.")
        duplicate_label = next(
            (
                existing.mode_id
                for existing in self._definitions.values()
                if existing.label.casefold() == definition.label.casefold()
            ),
            None,
        )
        if duplicate_label is not None:
            raise ValueError(
                f"Weighting mode label {definition.label!r} is already used by "
                f"{duplicate_label!r}."
            )
        self._definitions[definition.mode_id] = definition
        return definition

    def get(self, mode_id: str) -> WeightingModeDefinition:
        normalized = str(mode_id).strip().lower()
        try:
            return self._definitions[normalized]
        except KeyError as exc:
            registered = ", ".join(self._definitions) or "(none)"
            raise ValueError(
                f"Unsupported weighting mode {mode_id!r}. Registered modes: {registered}"
            ) from exc

    def definitions(self) -> tuple[WeightingModeDefinition, ...]:
        return tuple(self._definitions.values())

    def ids(self, *, default_only: bool = False) -> tuple[str, ...]:
        return tuple(
            definition.mode_id
            for definition in self._definitions.values()
            if not default_only or definition.default_enabled
        )

    def normalize(
        self,
        modes: Sequence[str] | None,
        *,
        field_name: str = "weighting modes",
    ) -> list[str]:
        if modes is not None and (
            isinstance(modes, (str, bytes)) or not isinstance(modes, Sequence)
        ):
            raise ValueError(f"{field_name} must be a list of registered mode ids.")
        if modes is None or len(modes) == 0:
            modes = self.ids(default_only=True)

        normalized: list[str] = []
        invalid: list[str] = []
        for raw_mode in modes:
            mode = str(raw_mode).strip().lower()
            if not mode:
                continue
            if mode not in self._definitions:
                invalid.append(mode)
            elif mode not in normalized:
                normalized.append(mode)
        if invalid:
            registered = ", ".join(self._definitions)
            raise ValueError(
                f"Unsupported {field_name} values: "
                + ", ".join(repr(mode) for mode in invalid)
                + f". Registered modes: {registered}"
            )
        if not normalized:
            defaults = list(self.ids(default_only=True))
            if not defaults:
                raise ValueError(f"{field_name} resolved to no modes.")
            return defaults
        return normalized

    def definitions_for(
        self,
        modes: Sequence[str] | None,
        *,
        field_name: str = "weighting modes",
    ) -> tuple[WeightingModeDefinition, ...]:
        return tuple(
            self.get(mode_id)
            for mode_id in self.normalize(modes, field_name=field_name)
        )


def _registry_with(
    additional_definitions: Iterable[WeightingModeDefinition] = (),
) -> WeightingModeRegistry:
    registry = WeightingModeRegistry()
    for definition in WEIGHTING_MODES.definitions():
        registry.register(definition)
    for definition in additional_definitions:
        if definition.mode_id in registry.ids():
            existing = registry.get(definition.mode_id)
            if existing is definition or existing == definition:
                continue
        registry.register(definition)
    return registry


def _with_weight_column(frame: Any, source_column: str) -> Any:
    import polars as pl

    return frame.with_columns(
        pl.col(source_column).cast(pl.Float64).alias("finalweight")
    )


def _inherit_weight(
    frame: Any,
    source: Any,
    *,
    key: str,
) -> Any:
    """Attach source weights when both prepared tables expose the join key."""
    import polars as pl

    if (
        frame.is_empty()
        or source.is_empty()
        or key not in frame.columns
        or key not in source.columns
        or "finalweight" not in source.columns
    ):
        return frame
    inherited = "_named_weighting_mode_weight"
    result = frame.join(
        source.select(key, pl.col("finalweight").alias(inherited)),
        on=key,
        how="left",
    )
    fallbacks = [pl.col(inherited)]
    if "finalweight" in frame.columns:
        fallbacks.append(pl.col("finalweight"))
    fallbacks.append(pl.lit(1.0))
    return result.with_columns(
        pl.coalesce(fallbacks).cast(pl.Float64).alias("finalweight")
    ).drop(inherited)


def _apply_column_weighting(
    run: "RunData",
    columns: Mapping[str, str],
) -> "RunData":
    """Apply named source columns and propagate them through prepared relations."""
    import polars as pl

    hh = run.hh
    per = run.per
    day = run.day
    tours = run.tours
    trips = run.trips
    vehicles = run.vehicles

    household_source = columns.get("households")
    person_source = columns.get("persons")
    trip_source = columns.get("trips")

    household_changed = household_source is not None
    person_changed = person_source is not None or household_changed

    if household_source is not None:
        hh = _with_weight_column(hh, household_source)

    if person_source is not None:
        per = _with_weight_column(per, person_source)
    elif household_changed:
        per = _inherit_weight(per, hh, key="household_id")

    if trip_source is not None:
        trips = _with_weight_column(trips, trip_source)
    elif person_changed:
        inherited = _inherit_weight(trips, per, key="person_id")
        if inherited is trips and household_changed:
            inherited = _inherit_weight(trips, hh, key="household_id")
        trips = inherited

    if trip_source is not None and "tour_id" in trips.columns:
        tour_weights = trips.group_by("tour_id").agg(
            pl.col("finalweight").mean().alias("finalweight")
        )
        tours = _inherit_weight(tours, tour_weights, key="tour_id")
    elif person_changed:
        inherited = _inherit_weight(tours, per, key="person_id")
        if inherited is tours and household_changed:
            inherited = _inherit_weight(tours, hh, key="household_id")
        tours = inherited

    if person_changed:
        inherited = _inherit_weight(day, per, key="person_id")
        if inherited is day and household_changed:
            inherited = _inherit_weight(day, hh, key="household_id")
        day = inherited

    if household_changed:
        vehicles = _inherit_weight(vehicles, hh, key="household_id")

    trip_hypothetical_skims = run.trip_hypothetical_skims
    if trip_source is not None or person_changed:
        trip_hypothetical_skims = _inherit_weight(
            trip_hypothetical_skims,
            trips,
            key="trip_id",
        )
    tour_hypothetical_skims = run.tour_hypothetical_skims
    if trip_source is not None or person_changed:
        tour_hypothetical_skims = _inherit_weight(
            tour_hypothetical_skims,
            tours,
            key="tour_id",
        )

    return replace(
        run,
        hh=hh,
        per=per,
        day=day,
        tours=tours,
        trips=trips,
        vehicles=vehicles,
        trip_hypothetical_skims=trip_hypothetical_skims,
        tour_hypothetical_skims=tour_hypothetical_skims,
    )


def column_weighting_mode_definitions(
    value: object,
    *,
    field_name: str = "weighting.modes",
) -> tuple[WeightingModeDefinition, ...]:
    """Parse config-defined modes that select columns on prepared run tables."""
    if value is None:
        return ()
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    definitions: list[WeightingModeDefinition] = []
    for raw_mode_id, raw_definition in value.items():
        mode_id = str(raw_mode_id).strip().lower()
        mode_field = f"{field_name}.{raw_mode_id}"
        if not isinstance(raw_definition, Mapping):
            raise ValueError(f"{mode_field} must be a mapping.")
        unknown = sorted(
            set(raw_definition) - {"label", "columns"},
            key=str,
        )
        if unknown:
            raise ValueError(
                f"Unknown {mode_field} config keys: "
                + ", ".join(repr(key) for key in unknown)
            )
        raw_columns = raw_definition.get("columns")
        if not isinstance(raw_columns, Mapping) or not raw_columns:
            raise ValueError(f"{mode_field}.columns must be a non-empty mapping.")
        unknown_tables = sorted(
            set(raw_columns) - set(_COLUMN_MODE_TABLES),
            key=str,
        )
        if unknown_tables:
            supported = ", ".join(_COLUMN_MODE_TABLES)
            raise ValueError(
                f"Unknown {mode_field}.columns table names: "
                + ", ".join(repr(key) for key in unknown_tables)
                + f". Supported names: {supported}."
            )
        columns: dict[str, str] = {}
        for table_name, raw_column in raw_columns.items():
            if not isinstance(raw_column, str):
                raise ValueError(
                    f"{mode_field}.columns.{table_name} must be a column-name string."
                )
            column = raw_column.strip()
            if not column:
                raise ValueError(
                    f"{mode_field}.columns.{table_name} must be a non-empty column name."
                )
            columns[str(table_name)] = column

        raw_label = raw_definition.get(
            "label",
            mode_id.replace("_", " ").replace("-", " ").title(),
        )
        if not isinstance(raw_label, str):
            raise ValueError(f"{mode_field}.label must be a string when provided.")
        label = raw_label.strip()
        required_columns = {
            _COLUMN_MODE_TABLES[table_name]: (column,)
            for table_name, column in columns.items()
        }

        def transform(
            run: "RunData",
            config: "Config | None",
            *,
            selected_columns: Mapping[str, str] = MappingProxyType(dict(columns)),
        ) -> "RunData":
            return _apply_column_weighting(run, selected_columns)

        definitions.append(
            WeightingModeDefinition(
                mode_id=mode_id,
                label=label,
                transform=transform,
                version="column-v1",
                required_columns=required_columns,
                external_summary_policy="reject",
            )
        )

    # Reuse registry validation for duplicate IDs/labels and built-in conflicts.
    _registry_with(definitions)
    return tuple(definitions)


def _identity_weighting(run: "RunData", config: "Config | None") -> "RunData":
    return run


def _unweighted_run(run: "RunData", config: "Config | None") -> "RunData":
    import polars as pl

    from processor.models import map_run_data_tables

    return map_run_data_tables(
        run,
        lambda _table_name, frame: (
            frame.with_columns(pl.lit(1.0).alias("finalweight"))
            if "finalweight" in frame.columns
            else frame
        ),
        clear_weight_columns=True,
    )


WEIGHTING_MODES = WeightingModeRegistry()
WEIGHTING_MODES.register(
    WeightingModeDefinition(
        mode_id="weighted",
        label="Weighted",
        transform=_identity_weighting,
        version="1",
        external_summary_policy="copy",
        default_enabled=True,
    )
)
WEIGHTING_MODES.register(
    WeightingModeDefinition(
        mode_id="unweighted",
        label="Unweighted",
        transform=_unweighted_run,
        version="1",
        external_summary_policy="copy",
        default_enabled=True,
    )
)


_LOADED_MODULES: set[tuple[int, str]] = set()
_LOADED_ENTRY_POINTS: set[tuple[int, str]] = set()


def _register_extension_object(
    value: object,
    *,
    registry: WeightingModeRegistry,
    source: str,
) -> None:
    if isinstance(value, WeightingModeDefinition):
        registry.register(value)
        return
    if isinstance(value, ModuleType):
        hook = getattr(value, "register_weighting_modes", None)
        if hook is None:
            raise ValueError(
                f"Weighting extension {source} must define register_weighting_modes(registry)."
            )
        value = hook
    if callable(value):
        value(registry)
        return
    raise TypeError(
        f"Weighting extension {source} must load a WeightingModeDefinition, "
        "registration callable, or module with register_weighting_modes(registry)."
    )


def load_weighting_mode_extensions(
    module_names: Iterable[str] = (),
    *,
    registry: WeightingModeRegistry = WEIGHTING_MODES,
    discover_entry_points: bool = True,
) -> None:
    """Load installed and project-local weighting extensions exactly once."""
    if discover_entry_points:
        discovered = metadata.entry_points()
        entry_points = (
            discovered.select(group="activitysim_visualizer.weighting_modes")
            if hasattr(discovered, "select")
            else discovered.get("activitysim_visualizer.weighting_modes", ())
        )
        for entry_point in sorted(
            entry_points, key=lambda item: (item.name, item.value)
        ):
            key = (id(registry), f"{entry_point.name}:{entry_point.value}")
            if key in _LOADED_ENTRY_POINTS:
                continue
            try:
                loaded = entry_point.load()
                _register_extension_object(
                    loaded,
                    registry=registry,
                    source=f"entry point {entry_point.name!r}",
                )
            except Exception as exc:
                raise ValueError(
                    f"Failed to load weighting entry point {entry_point.name!r}: {exc}"
                ) from exc
            _LOADED_ENTRY_POINTS.add(key)

    for raw_name in module_names:
        module_name = str(raw_name).strip()
        if not module_name:
            continue
        key = (id(registry), module_name)
        if key in _LOADED_MODULES:
            continue
        try:
            module = import_module(module_name)
            _register_extension_object(
                module,
                registry=registry,
                source=f"module {module_name!r}",
            )
        except Exception as exc:
            raise ValueError(
                f"Failed to load weighting extension module {module_name!r}: {exc}"
            ) from exc
        _LOADED_MODULES.add(key)


def normalize_weighting_modes(
    modes: Sequence[str] | None,
    *,
    field_name: str = "weighting modes",
    additional_definitions: Iterable[WeightingModeDefinition] = (),
) -> list[str]:
    return _registry_with(additional_definitions).normalize(
        modes,
        field_name=field_name,
    )


def weighting_mode_definitions(
    modes: Sequence[str] | None,
    *,
    field_name: str = "weighting modes",
    additional_definitions: Iterable[WeightingModeDefinition] = (),
) -> tuple[WeightingModeDefinition, ...]:
    return _registry_with(additional_definitions).definitions_for(
        modes,
        field_name=field_name,
    )


__all__ = [
    "WEIGHTING_MODES",
    "WeightingModeDefinition",
    "WeightingModeRegistry",
    "column_weighting_mode_definitions",
    "load_weighting_mode_extensions",
    "normalize_weighting_modes",
    "weighting_mode_definitions",
]
