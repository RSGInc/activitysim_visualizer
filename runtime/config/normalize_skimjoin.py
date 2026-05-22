"""Skimjoin config loading and run override resolution."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .common import (
    normalize_optional_path_string,
    normalize_string_list,
)
from .models import RunSkimjoinOverrides, SkimjoinSettings

if TYPE_CHECKING:
    from .models import Config


def validate_integrated_skim_files(
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


def validate_required_period_mappings(
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


def load_resolved_skimjoin_settings(
    *,
    config_path: str,
    skim_files_override: tuple[str, ...] = (),
    network_los_file_override: str | None = None,
    context_label: str,
) -> SkimjoinSettings:
    from .signatures import digest_payload
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
    validate_required_period_mappings(
        normalized_config,
        context_label=context_label,
    )
    skim_files = list(normalized_config.skim_files)
    validate_integrated_skim_files(skim_files, context_label=context_label)
    project = explicit_config.project
    return SkimjoinSettings(
        enabled=True,
        config_path=str(resolved_config_path),
        config_digest=digest_payload(normalized_config.model_dump(mode="python")),
        normalized_config=normalized_config,
        resolved_skim_files=tuple(skim_files),
        resolved_network_los_file=(None if project is None else project.network_los_file),
    )


def normalize_run_skimjoin_overrides(
    raw_value,
    *,
    field_name: str,
    config_dir: Path,
) -> RunSkimjoinOverrides:
    if raw_value in (None, {}):
        return RunSkimjoinOverrides()
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")

    config_path = normalize_optional_path_string(
        raw_value.get("config_path"),
        field_name=f"{field_name}.config_path",
        config_dir=config_dir,
    )
    skim_files = tuple(
        normalize_string_list(
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
    network_los_file = normalize_optional_path_string(
        raw_value.get("network_los_file"),
        field_name=f"{field_name}.network_los_file",
        config_dir=config_dir,
    )
    return RunSkimjoinOverrides(
        config_path=config_path,
        skim_files=skim_files,
        network_los_file=network_los_file,
    )


def normalize_skimjoin_settings(
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
    resolved_config_path = normalize_optional_path_string(
        raw_value.get("config_path"),
        field_name="skimjoin.config_path",
        config_dir=config_dir,
    )

    if not enabled:
        return SkimjoinSettings(enabled=False, config_path=resolved_config_path)

    if resolved_config_path is None:
        return SkimjoinSettings(enabled=True, config_path=None)
    return load_resolved_skimjoin_settings(
        config_path=resolved_config_path,
        context_label="global",
    )


def resolve_run_skimjoin_settings(config: Config, run_entry: dict[str, Any]) -> SkimjoinSettings:
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
        overrides = normalize_run_skimjoin_overrides(
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

    return load_resolved_skimjoin_settings(
        config_path=effective_config_path,
        skim_files_override=overrides.skim_files,
        network_los_file_override=overrides.network_los_file,
        context_label=f"run '{run_label}'",
    )
