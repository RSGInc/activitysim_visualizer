from __future__ import annotations

from pathlib import Path

import polars as pl
import yaml

from processor.skimjoin.config.schema import NormalizedConfig


def write_normalized_config(path: str | Path, normalized: NormalizedConfig) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(normalized.model_dump(mode="python"), sort_keys=False), encoding="utf-8")


def write_validation_report(path: str | Path, normalized: NormalizedConfig) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    status = "failed" if normalized.failures else "passed"
    lines = [
        f"validation_status: {status}",
        f"number of lookup rules: {len(normalized.lookups)}",
        f"number of referenced matrices: {len(normalized.referenced_matrices)}",
        f"number of ActivitySim modes covered: {len(sorted({rule.mode for rule in normalized.lookups}))}",
        f"number of ignored modes: {len(normalized.ignore_modes)}",
        f"number of output columns: {len(sorted({rule.output for rule in normalized.lookups}))}",
    ]
    if normalized.failures:
        lines.append("")
        lines.append("failures:")
        lines.extend(f"- {failure}" for failure in normalized.failures)
    if normalized.warnings:
        lines.append("")
        lines.append("warnings:")
        lines.extend(f"- {warning}" for warning in normalized.warnings)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_validation_failure_report(
    path: str | Path,
    message: str,
    normalized: NormalizedConfig | None = None,
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["validation_status: failed"]
    if normalized is not None:
        lines.extend(
            [
                f"number of lookup rules: {len(normalized.lookups)}",
                f"number of ignored modes: {len(normalized.ignore_modes)}",
            ]
        )
    lines.append("")
    lines.append("failures:")
    lines.extend(f"- {line}" for line in str(message).splitlines() if line.strip())
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_table(path: str | Path, table: pl.DataFrame) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    table.write_csv(target)
