"""Versioned weighting-mode definitions and extension discovery."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module, metadata
import re
from types import MappingProxyType, ModuleType
from typing import Any, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from processor.models import RunData
    from runtime.config.models import Config


WeightingTransform = Callable[["RunData", "Config | None"], "RunData"]
ExternalSummaryPolicy = Literal["copy", "reject"]


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
) -> list[str]:
    return WEIGHTING_MODES.normalize(modes, field_name=field_name)


def weighting_mode_definitions(
    modes: Sequence[str] | None,
    *,
    field_name: str = "weighting modes",
) -> tuple[WeightingModeDefinition, ...]:
    return WEIGHTING_MODES.definitions_for(modes, field_name=field_name)


__all__ = [
    "WEIGHTING_MODES",
    "WeightingModeDefinition",
    "WeightingModeRegistry",
    "load_weighting_mode_extensions",
    "normalize_weighting_modes",
    "weighting_mode_definitions",
]
