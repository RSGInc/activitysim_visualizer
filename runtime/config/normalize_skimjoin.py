"""Skimjoin config loading and run override resolution."""

from __future__ import annotations

from dataclasses import replace
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
    return


def load_resolved_skimjoin_settings(
    *,
    config_path: str,
    skim_files_override: tuple[str, ...] = (),
    network_los_file_override: str | None = None,
    create_hypothetical_skim_tables: bool = False,
    failure_policy: str = "record",
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
        create_hypothetical_skim_tables=bool(create_hypothetical_skim_tables),
        failure_policy=failure_policy,
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
    if "generate_hypothetical_sidecars" in raw_value:
        raise ValueError(
            f"{field_name}.generate_hypothetical_sidecars was renamed to "
            f"{field_name}.create_hypothetical_skim_tables."
        )

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
    create_hypothetical_skim_tables = raw_value.get("create_hypothetical_skim_tables")
    if create_hypothetical_skim_tables is not None and not isinstance(
        create_hypothetical_skim_tables, bool
    ):
        raise ValueError(
            f"{field_name}.create_hypothetical_skim_tables must be true or false when provided."
        )
    return RunSkimjoinOverrides(
        config_path=config_path,
        skim_files=skim_files,
        network_los_file=network_los_file,
        create_hypothetical_skim_tables=create_hypothetical_skim_tables,
    )


def normalize_skimjoin_settings(
    raw_value,
    *,
    config_dir: Path,
    field_name: str = "skimjoin",
    default_enabled: bool | None = None,
) -> SkimjoinSettings:
    if raw_value is None:
        return SkimjoinSettings(enabled=bool(default_enabled))
    if not isinstance(raw_value, dict):
        raise ValueError(f"{field_name} must be a mapping when provided.")
    if "generate_hypothetical_sidecars" in raw_value:
        raise ValueError(
            f"{field_name}.generate_hypothetical_sidecars was renamed to "
            f"{field_name}.create_hypothetical_skim_tables."
        )

    defaults_raw = raw_value.get("defaults")
    defaults = None
    if defaults_raw is not None:
        if not isinstance(defaults_raw, dict):
            raise ValueError(f"{field_name}.defaults must be a mapping when provided.")
        defaults = defaults_raw

    enabled_default = default_enabled if default_enabled is not None else False
    if defaults is not None and default_enabled is None:
        enabled_default = True

    enabled = raw_value.get("enabled", enabled_default)
    if not isinstance(enabled, bool):
        raise ValueError(f"{field_name}.enabled must be true or false when provided.")
    create_hypothetical_skim_tables = raw_value.get(
        "create_hypothetical_skim_tables",
        False,
    )
    if not isinstance(create_hypothetical_skim_tables, bool):
        raise ValueError(
            f"{field_name}.create_hypothetical_skim_tables must be true or false when provided."
        )
    failure_policy = str(raw_value.get("failure_policy", "record")).strip().lower()
    if failure_policy not in {"record", "error"}:
        raise ValueError(
            f"{field_name}.failure_policy must be either 'record' or 'error'."
        )
    config_path_raw = (
        defaults.get("config_path")
        if defaults is not None and "config_path" in defaults
        else raw_value.get("config_path")
    )
    resolved_config_path = normalize_optional_path_string(
        config_path_raw,
        field_name=(
            f"{field_name}.defaults.config_path"
            if defaults is not None and "config_path" in defaults
            else f"{field_name}.config_path"
        ),
        config_dir=config_dir,
    )
    skim_files = ()
    if defaults is not None:
        skim_files = tuple(
            normalize_string_list(
                defaults.get("skim_files"),
                field_name=f"{field_name}.defaults.skim_files",
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
    network_los_file = (
        normalize_optional_path_string(
            defaults.get("network_los_file"),
            field_name=f"{field_name}.defaults.network_los_file",
            config_dir=config_dir,
        )
        if defaults is not None
        else None
    )

    if not enabled:
        return SkimjoinSettings(
            enabled=False,
            config_path=resolved_config_path,
            create_hypothetical_skim_tables=create_hypothetical_skim_tables,
            failure_policy=failure_policy,
        )

    if resolved_config_path is None:
        return SkimjoinSettings(
            enabled=True,
            config_path=None,
            create_hypothetical_skim_tables=create_hypothetical_skim_tables,
            failure_policy=failure_policy,
        )
    return load_resolved_skimjoin_settings(
        config_path=resolved_config_path,
        skim_files_override=skim_files,
        network_los_file_override=network_los_file,
        create_hypothetical_skim_tables=create_hypothetical_skim_tables,
        failure_policy=failure_policy,
        context_label="global",
    )


def resolve_run_skimjoin_settings(config: Config, run_entry: dict[str, Any]) -> SkimjoinSettings:
    if not config.skimjoin_step_enabled():
        return replace(
            config.skimjoin,
            enabled=False,
            config_digest=None,
            normalized_config=None,
            resolved_skim_files=(),
            resolved_network_los_file=None,
        )

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
        and overrides.create_hypothetical_skim_tables is None
        and config.skimjoin.config_path == effective_config_path
        and config.skimjoin.normalized_config is not None
    ):
        return config.skimjoin

    create_hypothetical_skim_tables = (
        config.skimjoin.create_hypothetical_skim_tables
        if overrides.create_hypothetical_skim_tables is None
        else overrides.create_hypothetical_skim_tables
    )
    return load_resolved_skimjoin_settings(
        config_path=effective_config_path,
        skim_files_override=overrides.skim_files,
        network_los_file_override=overrides.network_los_file,
        create_hypothetical_skim_tables=create_hypothetical_skim_tables,
        failure_policy=config.skimjoin.failure_policy,
        context_label=f"run '{run_label}'",
    )
