from __future__ import annotations

from pathlib import Path

import yaml


def load_network_los_period_mapping(path: str | Path) -> dict[str, str]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    skim_time_periods = data.get("skim_time_periods")
    if not isinstance(skim_time_periods, dict):
        raise ValueError("network_los_file is missing skim_time_periods.")

    periods = skim_time_periods.get("periods")
    labels = skim_time_periods.get("labels")
    if not isinstance(periods, list) or not isinstance(labels, list):
        raise ValueError("skim_time_periods must define list-valued periods and labels.")
    if len(periods) < 2:
        raise ValueError("skim_time_periods.periods must contain at least two breakpoints.")
    if len(labels) != len(periods) - 1:
        raise ValueError("skim_time_periods.labels must have exactly len(periods) - 1 entries.")

    mapping: dict[str, str] = {}
    for idx, label in enumerate(labels):
        start = periods[idx]
        end = periods[idx + 1]
        try:
            start_int = int(start)
            end_int = int(end)
        except (TypeError, ValueError) as exc:
            raise ValueError("skim_time_periods.periods must contain integers.") from exc
        # ActivitySim trip-side period buckets are treated as 1..48 rather than 0..47.
        # The network_los breakpoints remain zero-based, so shift each covered bucket by +1.
        for period_number in range(start_int, end_int):
            mapping[str(period_number + 1)] = str(label)
    return mapping
