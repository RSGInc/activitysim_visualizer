"""Shared helpers for skim summary dashboard pages."""

from __future__ import annotations

import numpy as np
import polars as pl

from dashboard.data_access import DashboardSummarySeries
from processor.models import RunData
from runtime.config import Config, resolve_run_skimjoin_settings

TRIP_STATS_SUMMARY_ID = "skimjoin_trip_component_stats"
TOUR_STATS_SUMMARY_ID = "skimjoin_tour_component_stats"
TRIP_ECDF_SUMMARY_ID = "skimjoin_trip_component_ecdf"
TOUR_ECDF_SUMMARY_ID = "skimjoin_tour_component_ecdf"
DEFAULT_BIN_COUNT = 500
DIRECTION_SUFFIXES = ("_outbound", "_inbound")
ALL_MODES = "All Modes"
SKIM_FAMILY_ORDER = (
    "Auto Skims",
    "Transit Skims",
    "Walk Skims",
    "Bike Skims",
    "Other Skims",
)
SKIM_FAMILY_MODE_MAP = {
    "Auto Skims": ("SOV", "HOV2", "HOV3"),
    "Transit Skims": ("WALK_TRANSIT", "PNR_TRANSIT", "KNR_TRANSIT"),
    "Walk Skims": ("WALK",),
    "Bike Skims": ("BIKE", "EBIKE", "ESCOOTER", "BIKE_TRANSIT"),
}
SUMMARY_METRIC_COLUMNS = [
    "n_total",
    "n_valid",
    "mean",
    "std",
    "min",
    "max",
    "median",
    "mode",
    "zero_share",
    "missing_share",
]


def nonempty(
    data_list: list[tuple[str, pl.DataFrame]] | None,
) -> list[tuple[str, pl.DataFrame]]:
    normalized: list[tuple[str, pl.DataFrame]] = []
    for item in data_list or []:
        if len(item) == 2:
            label, df = item
        elif len(item) == 3:
            label, _, df = item
        else:
            continue
        if df is not None and not df.is_empty():
            normalized.append((label, df))
    return normalized


def component_options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
) -> list[str]:
    components: list[str] = []
    for _, df in nonempty(data_list):
        if "component" not in df.columns:
            continue
        filtered = df
        if "n_valid" in filtered.columns:
            filtered = filtered.filter(pl.col("n_valid").cast(pl.Float64) > 0)
        if filtered.is_empty():
            continue
        for value in (
            filtered.select(pl.col("component").cast(pl.Utf8))
            .drop_nulls()
            .unique()
            .sort("component")
            .get_column("component")
            .to_list()
        ):
            if value not in components:
                components.append(value)
    return components or ["No components available"]


def tour_component_base_options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
) -> list[str]:
    bases: list[str] = []
    for component in component_options(data_list):
        base = strip_direction_suffix(component)
        if base not in bases:
            bases.append(base)
    return bases or ["No components available"]


def strip_direction_suffix(component: str) -> str:
    for suffix in DIRECTION_SUFFIXES:
        if component.endswith(suffix):
            return component[: -len(suffix)]
    return component


def directional_component_name(component_base: str, direction: str) -> str:
    return f"{component_base}_{direction}"


def component_display_name(
    component: str,
    *,
    strip_direction: bool = True,
) -> str:
    value = strip_direction_suffix(component) if strip_direction else component
    special_labels = {
        "skim_auto_time": "Drive Time",
        "skim_auto_distance": "Drive Distance",
        "skim_auto_cost": "Drive Cost",
        "skim_walk_distance": "TAZ Skim Walk Distance",
        "skim_walk_time": "Total Walk Access/Egress Time",
        "skim_walk_maz_distance": "MAZ Network Walk Distance",
        "skim_walk_maz_actual": "MAZ Actual Walk Time",
        "skim_transit_tiv": "Transit In-Vehicle Time",
        "skim_transit_auxiliary_walk_time": "Transit Auxiliary Walk Time",
        "skim_transit_first_wait_time": "Transit First Wait Time",
        "skim_transit_transfer_wait_time": "Transit Transfer Wait Time",
        "skim_transit_num_transfers": "Transit Number of Transfers",
        "skim_transit_fare": "Transit Fare",
        "skim_transit_brt_ivtt": "BRT In-Vehicle Time",
        "skim_transit_bus_ivtt": "Bus In-Vehicle Time",
        "skim_transit_commuter_rail_ivtt": "Commuter Rail In-Vehicle Time",
        "skim_transit_light_rail_ivtt": "Light Rail In-Vehicle Time",
        "skim_transit_o_maz_stop_walk_bus": "Origin Walk Distance to Local Bus Stop",
        "skim_transit_d_maz_stop_walk_bus": "Destination Walk Distance from Local Bus Stop",
        "skim_transit_o_maz_stop_walk_premium": "Origin Walk Distance to Premium Transit Stop",
        "skim_transit_d_maz_stop_walk_premium": "Destination Walk Distance from Premium Transit Stop",
        "skim_auto_time_outbound": "Drive Time",
        "skim_auto_time_inbound": "Drive Time",
        "skim_auto_distance_outbound": "Drive Distance",
        "skim_auto_distance_inbound": "Drive Distance",
        "skim_auto_cost_outbound": "Drive Cost",
        "skim_auto_cost_inbound": "Drive Cost",
        "skim_walk_time_outbound": "Total Walk Access/Egress Time",
        "skim_walk_time_inbound": "Total Walk Access/Egress Time",
        "skim_transit_tiv_outbound": "Transit In-Vehicle Time",
        "skim_transit_tiv_inbound": "Transit In-Vehicle Time",
    }
    if value in special_labels:
        return special_labels[value]
    for prefix in ("skim_auto_", "skim_walk_", "skim_transit_", "skim_"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    tokens = [token for token in value.split("_") if token]
    acronym_tokens = {
        "ivtt",
        "brt",
        "bus",
        "crt",
        "lrt",
        "tiv",
        "vot",
        "maz",
        "pnr",
        "knr",
    }
    formatted_tokens = [
        token.upper()
        if token.lower() in acronym_tokens
        else token.replace("-", " ").title()
        for token in tokens
    ]
    return " ".join(formatted_tokens) if formatted_tokens else value


def nonempty_series(
    series_list: list[tuple[str, DashboardSummarySeries, pl.DataFrame]] | None,
) -> list[tuple[str, DashboardSummarySeries, pl.DataFrame]]:
    return [
        (label, series, df)
        for label, series, df in (series_list or [])
        if df is not None and not df.is_empty()
    ]


def skim_family_for_mode(mode: str) -> str | None:
    mode_str = str(mode)
    for family, modes in SKIM_FAMILY_MODE_MAP.items():
        if mode_str in modes:
            return family
    return None


def _available_modes_from_data(
    data_list: list[tuple[str, DashboardSummarySeries, pl.DataFrame]] | None,
    *,
    mode_column: str,
) -> list[str]:
    modes: list[str] = []
    for _, _, df in nonempty_series(data_list):
        if mode_column not in df.columns:
            continue
        for mode in (
            df.select(pl.col(mode_column).cast(pl.Utf8))
            .drop_nulls()
            .unique()
            .get_column(mode_column)
            .to_list()
        ):
            mode_str = str(mode)
            if mode_str == ALL_MODES or mode_str in modes:
                continue
            modes.append(mode_str)
    return modes


def _matching_run_entry(
    config: Config,
    series: DashboardSummarySeries,
) -> dict | None:
    series_run_dir = str(series.source_run_dir or "").strip().lower().replace("\\", "/")
    series_label = str(series.label).strip().lower()
    for entry in config.runs:
        entry_dir = str(entry.get("dir") or "").strip().lower().replace("\\", "/")
        entry_label = str(entry.get("label") or "").strip().lower()
        if series_run_dir and entry_dir and series_run_dir == entry_dir:
            return entry
        if series_label and entry_label and series_label == entry_label:
            return entry
    return None


def _configured_outputs_by_mode(
    config: Config,
    series: DashboardSummarySeries,
    *,
    target_table: str,
) -> dict[str, set[str]]:
    run_entry = _matching_run_entry(config, series)
    skimjoin_settings = (
        resolve_run_skimjoin_settings(config, run_entry)
        if run_entry is not None
        else config.skimjoin
    )
    normalized = getattr(skimjoin_settings, "normalized_config", None)
    if normalized is None:
        return {}
    lookup_attr = "trip_lookups" if target_table == "trips" else "tour_lookups"
    lookups = list(getattr(normalized, lookup_attr, []) or [])
    outputs_by_mode: dict[str, set[str]] = {}
    for rule in lookups:
        outputs_by_mode.setdefault(str(rule.mode), set()).add(str(rule.output))
    return outputs_by_mode


def _skim_family_definitions(
    config: Config,
    data_list: list[tuple[str, DashboardSummarySeries, pl.DataFrame]] | None,
    *,
    mode_column: str,
    target_table: str,
) -> dict[str, dict[str, dict[str, tuple[str, ...]]]]:
    definitions: dict[str, dict[str, dict[str, tuple[str, ...]]]] = {}
    for label, series, df in nonempty_series(data_list):
        configured_outputs = _configured_outputs_by_mode(
            config,
            series,
            target_table=target_table,
        )
        available_modes = _available_modes_from_data(
            [(label, series, df)],
            mode_column=mode_column,
        )
        family_definitions: dict[str, dict[str, tuple[str, ...]]] = {}
        if configured_outputs and available_modes:
            all_modes = [
                mode
                for mode in configured_outputs
                if mode != ALL_MODES and mode in available_modes
            ]
            all_modes.extend(
                mode
                for mode in available_modes
                if mode not in all_modes and mode != ALL_MODES
            )
        elif configured_outputs:
            all_modes = [mode for mode in configured_outputs if mode != ALL_MODES]
        else:
            all_modes = list(available_modes)

        assigned_modes: set[str] = set()
        for family in SKIM_FAMILY_ORDER:
            if family == "Other Skims":
                continue
            family_modes = tuple(
                mode
                for mode in SKIM_FAMILY_MODE_MAP.get(family, ())
                if mode in all_modes
            )
            if not family_modes:
                continue
            assigned_modes.update(family_modes)
            outputs = tuple(
                sorted(
                    {
                        output
                        for mode in family_modes
                        for output in configured_outputs.get(mode, set())
                    }
                )
            )
            family_definitions[family] = {"modes": family_modes, "outputs": outputs}

        # other_modes = tuple(sorted(mode for mode in all_modes if mode not in assigned_modes))
        # if other_modes:
        #     outputs = tuple(
        #         sorted(
        #             {
        #                 output
        #                 for mode in other_modes
        #                 for output in configured_outputs.get(mode, set())
        #             }
        #         )
        #     )
        #     family_definitions["Other Skims"] = {"modes": other_modes, "outputs": outputs}
        definitions[label] = family_definitions
    return definitions


def skim_family_options(
    config: Config,
    data_list: list[tuple[str, DashboardSummarySeries, pl.DataFrame]] | None,
    *,
    mode_column: str,
    target_table: str,
) -> list[str]:
    available: list[str] = []
    definitions_by_label = _skim_family_definitions(
        config,
        data_list,
        mode_column=mode_column,
        target_table=target_table,
    )
    for family_definitions in definitions_by_label.values():
        for family in family_definitions:
            if family not in available:
                available.append(family)
    ordered = [family for family in SKIM_FAMILY_ORDER if family in available]
    return ordered or ["No skim families available"]


def skim_direction_options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
) -> list[str]:
    available: list[str] = []
    for _, df in nonempty(data_list):
        if "component" not in df.columns:
            continue
        components = (
            df.select(pl.col("component").cast(pl.Utf8))
            .drop_nulls()
            .unique()
            .get_column("component")
            .to_list()
        )
        if any(str(component).endswith("_outbound") for component in components):
            available.append("Outbound")
        if any(str(component).endswith("_inbound") for component in components):
            available.append("Inbound")
        if len(available) == 2:
            break
    ordered = [
        direction for direction in ("Outbound", "Inbound") if direction in available
    ]
    return ordered or ["Outbound"]


def _skim_name_expr(*, strip_direction: bool) -> pl.Expr:
    return (
        pl.col("component")
        .map_elements(
            lambda value: component_display_name(
                str(value), strip_direction=strip_direction
            ),
            return_dtype=pl.Utf8,
        )
        .alias("skim_name")
    )


def family_stats_table(
    config: Config,
    data_list: list[tuple[str, DashboardSummarySeries, pl.DataFrame]] | None,
    *,
    family: str,
    mode_column: str,
    target_table: str,
    direction: str | None = None,
) -> list[tuple[str, pl.DataFrame]]:
    family_definitions_by_label = _skim_family_definitions(
        config,
        data_list,
        mode_column=mode_column,
        target_table=target_table,
    )
    direction_suffix = None if direction is None else f"_{direction.lower()}"
    target_columns = ["skim_name", mode_column, *SUMMARY_METRIC_COLUMNS]
    filtered_list: list[tuple[str, pl.DataFrame]] = []
    for label, _, df in nonempty_series(data_list):
        family_definition = family_definitions_by_label.get(label, {}).get(family)
        family_modes = family_definition.get("modes", ()) if family_definition else ()
        configured_outputs = (
            set(family_definition.get("outputs", ())) if family_definition else set()
        )
        if "component" not in df.columns or mode_column not in df.columns:
            filtered_list.append((label, pl.DataFrame()))
            continue
        filtered = df.with_columns(
            pl.col("component").cast(pl.Utf8),
            pl.col(mode_column).cast(pl.Utf8),
        ).filter(
            pl.col(mode_column).is_in(list(family_modes))
            & (pl.col(mode_column) != ALL_MODES)
        )
        if configured_outputs:
            filtered = filtered.filter(
                pl.col("component").is_in(list(configured_outputs))
            )
        if direction_suffix is not None:
            filtered = filtered.filter(
                pl.col("component").str.ends_with(direction_suffix)
            )
        if filtered.is_empty():
            filtered_list.append((label, pl.DataFrame()))
            continue
        filtered = filtered.with_columns(
            _skim_name_expr(strip_direction=direction is not None)
        )
        if target_table == "tours" and family == "Auto Skims":
            filtered = filtered.with_columns(
                pl.col("skim_name").str.replace(r"^Drive\s+", "")
            )
        filtered = filtered.select(
            [column for column in target_columns if column in filtered.columns]
        ).sort([mode_column, "skim_name"])
        filtered_list.append((label, filtered))
    return filtered_list


def skim_summary_precision_overrides() -> dict[str, int]:
    return {
        "n_total": 0,
        "n_valid": 0,
    }


def mode_options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    mode_column: str,
    component: str | None,
) -> list[str]:
    options: list[str] = []
    for _, df in nonempty(data_list):
        filtered = df
        if (
            component
            and component != "No components available"
            and "component" in df.columns
        ):
            filtered = filtered.filter(pl.col("component").cast(pl.Utf8) == component)
        if "n_valid" in filtered.columns:
            filtered = filtered.filter(pl.col("n_valid").cast(pl.Float64) > 0)
        if filtered.is_empty() or mode_column not in filtered.columns:
            continue
        values = (
            filtered.select(pl.col(mode_column).cast(pl.Utf8))
            .drop_nulls()
            .unique()
            .sort(mode_column)
            .get_column(mode_column)
            .to_list()
        )
        for value in values:
            if value == ALL_MODES:
                continue
            if value not in options:
                options.append(value)
    if not options:
        return ["No modes available"]
    return [ALL_MODES, *options]


def tour_mode_options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    mode_column: str,
    component_base: str | None,
) -> list[str]:
    options: list[str] = []
    for _, df in nonempty(data_list):
        filtered = df
        if component_base and component_base != "No components available":
            outbound = directional_component_name(component_base, "outbound")
            inbound = directional_component_name(component_base, "inbound")
            filtered = filtered.filter(
                pl.col("component").cast(pl.Utf8).is_in([outbound, inbound])
            )
        if "n_valid" in filtered.columns:
            filtered = filtered.filter(pl.col("n_valid").cast(pl.Float64) > 0)
        if filtered.is_empty() or mode_column not in filtered.columns:
            continue
        values = (
            filtered.select(pl.col(mode_column).cast(pl.Utf8))
            .drop_nulls()
            .unique()
            .sort(mode_column)
            .get_column(mode_column)
            .to_list()
        )
        for value in values:
            if value == ALL_MODES:
                continue
            if value not in options:
                options.append(value)
    if not options:
        return ["No modes available"]
    return [ALL_MODES, *options]


def filter_stats(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    component: str,
    mode_column: str,
    mode_value: str,
) -> list[tuple[str, pl.DataFrame]]:
    filtered_list: list[tuple[str, pl.DataFrame]] = []
    for label, df in nonempty(data_list):
        filtered = df.with_columns(
            pl.col("component").cast(pl.Utf8),
            pl.col(mode_column).cast(pl.Utf8),
        ).filter(pl.col("component") == component)
        filtered = filtered.filter(pl.col(mode_column) == mode_value)
        filtered = filtered.select(
            [column for column in SUMMARY_METRIC_COLUMNS if column in df.columns]
        )
        filtered_list.append((label, filtered))
    return filtered_list


def prepared_component_values(
    prepared_runs: list[tuple[str, RunData]] | None,
    *,
    table_name: str,
    mode_column: str,
    mode_value: str,
    component: str,
) -> list[tuple[str, np.ndarray, np.ndarray]]:
    resolved: list[tuple[str, np.ndarray, np.ndarray]] = []
    for label, run in prepared_runs or []:
        df = getattr(run, table_name)
        if df is None or df.is_empty():
            continue
        required_columns = {mode_column, component}
        if not required_columns.issubset(df.columns):
            continue
        filtered = df.with_columns(pl.col(mode_column).cast(pl.Utf8)).filter(
            pl.col(component).is_not_null()
        )
        if mode_value != ALL_MODES:
            filtered = filtered.filter(pl.col(mode_column) == mode_value)
        filtered = filtered.select(
            pl.col(component).cast(pl.Float64).alias(component),
            (
                pl.col("finalweight").cast(pl.Float64)
                if "finalweight" in df.columns
                else pl.lit(1.0)
            ).alias("finalweight"),
        )
        if filtered.is_empty():
            continue
        values = filtered.get_column(component).to_numpy()
        weights = filtered.get_column("finalweight").to_numpy()
        resolved.append((label, values, weights))
    return resolved


def distribution_bins(
    prepared_runs: list[tuple[str, RunData]] | None,
    *,
    table_name: str,
    mode_column: str,
    mode_value: str,
    component: str,
    x_range: tuple[float, float] | None = None,
    bin_count: int = DEFAULT_BIN_COUNT,
) -> list[tuple[str, pl.DataFrame]]:
    value_sets = prepared_component_values(
        prepared_runs,
        table_name=table_name,
        mode_column=mode_column,
        mode_value=mode_value,
        component=component,
    )
    if not value_sets:
        return []

    all_values = np.concatenate([values for _, values, _ in value_sets])
    if all_values.size == 0:
        return []
    min_value = float(np.min(all_values))
    max_value = float(np.max(all_values))

    if x_range is not None:
        min_value = float(x_range[0])
        max_value = float(x_range[1])

    if min_value == max_value:
        bin_mid = min_value
        return [
            (
                label,
                pl.DataFrame(
                    {
                        "bin_mid": [bin_mid],
                        "freq": [float(np.sum(weights))],
                    }
                ),
            )
            for label, _, weights in value_sets
        ]

    edges = np.linspace(min_value, max_value, num=bin_count + 1)
    mids = ((edges[:-1] + edges[1:]) / 2.0).tolist()
    distributions: list[tuple[str, pl.DataFrame]] = []
    for label, values, weights in value_sets:
        in_range = (values >= min_value) & (values <= max_value)
        histogram_values = values[in_range]
        histogram_weights = weights[in_range]
        if histogram_values.size == 0:
            hist = np.zeros(len(mids), dtype=float)
        else:
            hist, _ = np.histogram(
                histogram_values,
                bins=edges,
                weights=histogram_weights,
            )
        distributions.append(
            (
                label,
                pl.DataFrame(
                    {
                        "bin_mid": mids,
                        "freq": hist.astype(float).tolist(),
                    }
                ),
            )
        )
    return distributions


def distribution_data_bounds(
    prepared_runs: list[tuple[str, RunData]] | None,
    *,
    table_name: str,
    mode_column: str,
    mode_value: str,
    component: str,
) -> tuple[float, float] | None:
    value_sets = prepared_component_values(
        prepared_runs,
        table_name=table_name,
        mode_column=mode_column,
        mode_value=mode_value,
        component=component,
    )
    if not value_sets:
        return None
    all_values = np.concatenate(
        [values for _, values, _ in value_sets if values.size > 0]
    )
    if all_values.size == 0:
        return None
    return (float(np.min(all_values)), float(np.max(all_values)))


def resolve_distribution_range(
    min_value: float | None,
    max_value: float | None,
) -> tuple[float, float] | None:
    if min_value is None or max_value is None:
        return None
    if not np.isfinite(min_value) or not np.isfinite(max_value):
        return None
    if float(max_value) <= float(min_value):
        return None
    return (float(min_value), float(max_value))
