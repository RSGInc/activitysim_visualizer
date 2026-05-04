"""Builder contract helpers for resilient summary execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping

import polars as pl

from processor.models import RunData

SummarySchema = Mapping[str, pl.DataType]


@dataclass(frozen=True)
class SummaryContract:
    """Static contract metadata attached to one summary builder."""

    schema: SummarySchema
    required_tables: tuple[str, ...] = ()
    required_columns: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(self.schema.keys())


def summary_contract(
    *,
    schema: SummarySchema,
    required_tables: tuple[str, ...] = (),
    required_columns: dict[str, tuple[str, ...]] | None = None,
) -> Callable[[Callable], Callable]:
    """Attach output-shape and prerequisite metadata to a builder."""
    contract = SummaryContract(
        schema=dict(schema),
        required_tables=tuple(required_tables),
        required_columns={
            table_name: tuple(columns)
            for table_name, columns in (required_columns or {}).items()
        },
    )

    def decorator(builder: Callable) -> Callable:
        setattr(builder, "_summary_contract", contract)
        return builder

    return decorator


def get_summary_contract(builder: Callable) -> SummaryContract | None:
    """Return the contract attached to ``builder`` when present."""
    contract = getattr(builder, "_summary_contract", None)
    return contract if isinstance(contract, SummaryContract) else None


def empty_summary_frame(builder: Callable) -> pl.DataFrame:
    """Return the typed empty fallback frame for ``builder``."""
    contract = get_summary_contract(builder)
    if contract is None:
        return pl.DataFrame()
    return pl.DataFrame(schema=dict(contract.schema))


def summary_output_columns(builder: Callable) -> tuple[str, ...]:
    """Return the ordered output columns declared by ``builder``."""
    contract = get_summary_contract(builder)
    if contract is None:
        return ()
    return contract.columns


def missing_summary_inputs(
    builder: Callable,
    rd: RunData,
) -> dict[str, str]:
    """Return missing-input diagnostics for ``builder``.

    Contracts only express safe, mechanical preflight checks.
    Builders may still apply more nuanced domain-specific validation.
    """
    contract = get_summary_contract(builder)
    if contract is None:
        return {}

    missing: dict[str, str] = {}
    for table_name in contract.required_tables:
        if table_name == "skim":
            if rd.skim_matrix is None:
                missing[table_name] = "required skim data is unavailable"
            continue

        table = getattr(rd, table_name, None)
        if table is None:
            missing[table_name] = "required table is unavailable"

    for table_name, required_columns in contract.required_columns.items():
        if table_name == "skim":
            if rd.skim_matrix is None:
                missing[table_name] = "required skim data is unavailable"
            continue

        table = getattr(rd, table_name, None)
        if table is None:
            missing[table_name] = "required table is unavailable"
            continue

        missing_columns = [
            column for column in required_columns if column not in table.columns
        ]
        if missing_columns:
            missing[table_name] = "missing required columns: " + ", ".join(
                sorted(missing_columns)
            )

    return missing


__all__ = [
    "SummaryContract",
    "empty_summary_frame",
    "get_summary_contract",
    "missing_summary_inputs",
    "summary_contract",
    "summary_output_columns",
]
