"""Single-declaration contracts for summary builders."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import wraps
from typing import Callable, Mapping

import polars as pl

from processor.models import RunData

SummarySchema = Mapping[str, pl.DataType]


class SummaryResultError(ValueError):
    """Raised when a builder violates its declared output contract."""


@dataclass(frozen=True)
class SummaryContract:
    """Input and output shape for one summary builder."""

    schema: SummarySchema
    required_tables: tuple[str, ...] = ()
    required_columns: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(self.schema)


@dataclass(frozen=True)
class SummaryDefinition:
    """Complete registry metadata declared beside one builder."""

    summary_id: str
    filename: str
    builder: Callable
    contract: SummaryContract
    build_by_default: bool = True

    def empty(self) -> pl.DataFrame:
        return pl.DataFrame(schema=dict(self.contract.schema))


def _contract(
    *,
    schema: SummarySchema,
    required_tables: tuple[str, ...],
    required_columns: dict[str, tuple[str, ...]] | None,
) -> SummaryContract:
    return SummaryContract(
        schema=dict(schema),
        required_tables=tuple(required_tables),
        required_columns={
            table_name: tuple(columns)
            for table_name, columns in (required_columns or {}).items()
        },
    )


def validate_summary_result(
    definition: SummaryDefinition,
    result: object,
) -> pl.DataFrame:
    """Validate a successful builder result without silently reshaping it."""
    summary_id = definition.summary_id
    if not isinstance(result, pl.DataFrame):
        raise SummaryResultError(
            f"Summary {summary_id!r} returned {type(result).__name__}; expected polars.DataFrame."
        )

    expected_columns = list(definition.contract.schema)
    actual_columns = result.columns
    missing = [column for column in expected_columns if column not in actual_columns]
    unexpected = [column for column in actual_columns if column not in expected_columns]
    if missing or unexpected:
        details = []
        if missing:
            details.append("missing columns: " + ", ".join(missing))
        if unexpected:
            details.append("unexpected columns: " + ", ".join(unexpected))
        raise SummaryResultError(
            f"Summary {summary_id!r} returned an invalid schema ({'; '.join(details)})."
        )
    if actual_columns != expected_columns:
        raise SummaryResultError(
            f"Summary {summary_id!r} returned columns in the wrong order; "
            f"expected {expected_columns!r}, got {actual_columns!r}."
        )

    dtype_errors = [
        f"{column}: expected {expected}, got {result.schema[column]}"
        for column, expected in definition.contract.schema.items()
        if result.schema[column] != expected
    ]
    if dtype_errors:
        raise SummaryResultError(
            f"Summary {summary_id!r} returned invalid dtypes ("
            + "; ".join(dtype_errors)
            + ")."
        )
    return result


def summary(
    *,
    id: str | None = None,
    schema: SummarySchema,
    filename: str | None = None,
    build_by_default: bool = True,
    required_tables: tuple[str, ...] = (),
    required_columns: dict[str, tuple[str, ...]] | None = None,
) -> Callable[[Callable], Callable]:
    """Declare identity, prerequisites, and result schema in one place."""
    contract = _contract(
        schema=schema,
        required_tables=required_tables,
        required_columns=required_columns,
    )

    def decorator(builder: Callable) -> Callable:
        summary_id = str(id or builder.__name__)

        @wraps(builder)
        def checked(*args, **kwargs):
            run = args[0] if args else kwargs.get("rd") or kwargs.get("run")
            if isinstance(run, RunData) and missing_summary_inputs(checked, run):
                return checked.empty()
            return validate_summary_result(
                checked.summary_definition,
                builder(*args, **kwargs),
            )

        definition = SummaryDefinition(
            summary_id=summary_id,
            filename=str(filename or summary_id),
            builder=checked,
            contract=contract,
            build_by_default=bool(build_by_default),
        )
        checked.summary_definition = definition
        checked.empty = definition.empty
        return checked

    return decorator


def output_schema(*, schema: SummarySchema) -> Callable[[Callable], Callable]:
    """Attach a typed-empty schema to a non-registry helper."""
    contract = _contract(schema=schema, required_tables=(), required_columns=None)

    def decorator(builder: Callable) -> Callable:
        builder._output_contract = contract
        builder.empty = lambda: pl.DataFrame(schema=dict(contract.schema))
        return builder

    return decorator


def get_summary_definition(builder: Callable) -> SummaryDefinition | None:
    definition = getattr(builder, "summary_definition", None)
    return definition if isinstance(definition, SummaryDefinition) else None


def get_summary_contract(builder: Callable) -> SummaryContract | None:
    definition = get_summary_definition(builder)
    if definition is not None:
        return definition.contract
    contract = getattr(builder, "_output_contract", None)
    return contract if isinstance(contract, SummaryContract) else None


def empty_summary_frame(builder: Callable | SummaryDefinition) -> pl.DataFrame:
    """Return a typed empty frame for framework and diagnostic code."""
    if isinstance(builder, SummaryDefinition):
        return builder.empty()
    definition = get_summary_definition(builder)
    if definition is not None:
        return definition.empty()
    contract = get_summary_contract(builder)
    return pl.DataFrame(schema=dict(contract.schema)) if contract else pl.DataFrame()


def summary_output_columns(builder: Callable) -> tuple[str, ...]:
    contract = get_summary_contract(builder)
    return contract.columns if contract else ()


def missing_summary_inputs(builder: Callable, rd: RunData) -> dict[str, str]:
    """Return mechanical prerequisite failures for one builder and run."""
    contract = get_summary_contract(builder)
    if contract is None:
        return {}

    missing: dict[str, str] = {}
    for table_name in contract.required_tables:
        if table_name == "skim":
            if rd.skim_matrix is None:
                missing[table_name] = "required skim data is unavailable"
            continue
        if getattr(rd, table_name, None) is None:
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
        absent = [column for column in required_columns if column not in table.columns]
        if absent:
            missing[table_name] = "missing required columns: " + ", ".join(
                sorted(absent)
            )
    return missing


__all__ = [
    "SummaryContract",
    "SummaryDefinition",
    "SummaryResultError",
    "empty_summary_frame",
    "get_summary_contract",
    "get_summary_definition",
    "missing_summary_inputs",
    "output_schema",
    "summary",
    "summary_output_columns",
    "validate_summary_result",
]
