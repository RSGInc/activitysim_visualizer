"""Prepared-table relationship validation helpers."""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from processor.models import RunData
from processor.prepare.availability import (
    TABLE_STATE_FAILED,
    TABLE_STATE_UNAVAILABLE,
    table_availability,
)


@dataclass(frozen=True)
class PreparedRelationshipCheck:
    """Static definition for one foreign-key relationship check."""

    source_attr: str
    source_table_id: str
    source_key: str
    target_attr: str
    target_table_id: str
    target_key: str


@dataclass(frozen=True)
class PreparedRelationshipCheckResult:
    """Outcome of one prepared-table relationship validation check."""

    check: PreparedRelationshipCheck
    state: str
    orphan_count: int = 0
    message: str | None = None
    skip_reason: str | None = None


@dataclass(frozen=True)
class PreparedRelationshipValidationResult:
    """Aggregate relationship-validation result for one prepared run."""

    run_label: str
    checks: tuple[PreparedRelationshipCheckResult, ...]

    @property
    def failed_checks(self) -> tuple[PreparedRelationshipCheckResult, ...]:
        return tuple(check for check in self.checks if check.state == "failed")

    @property
    def failed_check_count(self) -> int:
        return len(self.failed_checks)

    @property
    def passed(self) -> bool:
        return self.failed_check_count == 0


class PreparedRelationshipValidationError(RuntimeError):
    """Raised when prepared-table relationship validation is configured as fatal."""


PREPARED_RELATIONSHIP_CHECKS: tuple[PreparedRelationshipCheck, ...] = (
    PreparedRelationshipCheck(
        source_attr="per",
        source_table_id="persons",
        source_key="household_id",
        target_attr="hh",
        target_table_id="households",
        target_key="household_id",
    ),
    PreparedRelationshipCheck(
        source_attr="day",
        source_table_id="day",
        source_key="household_id",
        target_attr="hh",
        target_table_id="households",
        target_key="household_id",
    ),
    PreparedRelationshipCheck(
        source_attr="day",
        source_table_id="day",
        source_key="person_id",
        target_attr="per",
        target_table_id="persons",
        target_key="person_id",
    ),
    PreparedRelationshipCheck(
        source_attr="tours",
        source_table_id="tours",
        source_key="household_id",
        target_attr="hh",
        target_table_id="households",
        target_key="household_id",
    ),
    PreparedRelationshipCheck(
        source_attr="tours",
        source_table_id="tours",
        source_key="person_id",
        target_attr="per",
        target_table_id="persons",
        target_key="person_id",
    ),
    PreparedRelationshipCheck(
        source_attr="trips",
        source_table_id="trips",
        source_key="household_id",
        target_attr="hh",
        target_table_id="households",
        target_key="household_id",
    ),
    PreparedRelationshipCheck(
        source_attr="trips",
        source_table_id="trips",
        source_key="person_id",
        target_attr="per",
        target_table_id="persons",
        target_key="person_id",
    ),
    PreparedRelationshipCheck(
        source_attr="trips",
        source_table_id="trips",
        source_key="tour_id",
        target_attr="tours",
        target_table_id="tours",
        target_key="tour_id",
    ),
    PreparedRelationshipCheck(
        source_attr="vehicles",
        source_table_id="vehicles",
        source_key="household_id",
        target_attr="hh",
        target_table_id="households",
        target_key="household_id",
    ),
    PreparedRelationshipCheck(
        source_attr="joint_participants",
        source_table_id="joint_tour_participants",
        source_key="person_id",
        target_attr="per",
        target_table_id="persons",
        target_key="person_id",
    ),
    PreparedRelationshipCheck(
        source_attr="joint_participants",
        source_table_id="joint_tour_participants",
        source_key="tour_id",
        target_attr="tours",
        target_table_id="tours",
        target_key="tour_id",
    ),
)


def _table_state_skips(
    rd: RunData,
    check: PreparedRelationshipCheck,
) -> str | None:
    states = table_availability(rd)
    source_state = states.get(check.source_table_id)
    target_state = states.get(check.target_table_id)
    if source_state in {TABLE_STATE_UNAVAILABLE, TABLE_STATE_FAILED}:
        return f"source table {check.source_table_id!r} is {source_state}"
    if target_state in {TABLE_STATE_UNAVAILABLE, TABLE_STATE_FAILED}:
        return f"target table {check.target_table_id!r} is {target_state}"
    return None


def _missing_column_skip(
    df: pl.DataFrame,
    table_id: str,
    column: str,
) -> str | None:
    if column not in df.columns:
        return f"table {table_id!r} is missing column {column!r}"
    return None


def _orphan_count(
    *,
    source: pl.DataFrame,
    source_key: str,
    target: pl.DataFrame,
    target_key: str,
) -> int:
    source_keys = source.filter(pl.col(source_key).is_not_null()).select(source_key)
    if source_keys.is_empty():
        return 0
    target_keys = target.filter(pl.col(target_key).is_not_null()).select(target_key).unique()
    return int(
        source_keys.join(
            target_keys,
            left_on=source_key,
            right_on=target_key,
            how="anti",
        ).height
    )


def _failure_message(
    *,
    run_label: str,
    check: PreparedRelationshipCheck,
    orphan_count: int,
) -> str:
    return (
        f'Prepared-table relationship warning for run "{run_label}": '
        f"{orphan_count} {check.source_table_id} rows reference {check.source_key} "
        f"values not present in {check.target_table_id}.{check.target_key}. "
        f"Summaries that aggregate {check.source_table_id} directly may still count "
        f"them, while summaries that join {check.source_table_id} to "
        f"{check.target_table_id} may drop them."
    )


def validate_prepared_relationships(
    prepared_run: RunData,
) -> PreparedRelationshipValidationResult:
    """Check foreign-key consistency across canonical prepared tables."""
    checks: list[PreparedRelationshipCheckResult] = []
    for check in PREPARED_RELATIONSHIP_CHECKS:
        skip_reason = _table_state_skips(prepared_run, check)
        if skip_reason is not None:
            checks.append(
                PreparedRelationshipCheckResult(
                    check=check,
                    state="skipped",
                    skip_reason=skip_reason,
                )
            )
            continue

        source = getattr(prepared_run, check.source_attr)
        target = getattr(prepared_run, check.target_attr)
        source_skip = _missing_column_skip(source, check.source_table_id, check.source_key)
        if source_skip is not None:
            checks.append(
                PreparedRelationshipCheckResult(
                    check=check,
                    state="skipped",
                    skip_reason=source_skip,
                )
            )
            continue
        target_skip = _missing_column_skip(target, check.target_table_id, check.target_key)
        if target_skip is not None:
            checks.append(
                PreparedRelationshipCheckResult(
                    check=check,
                    state="skipped",
                    skip_reason=target_skip,
                )
            )
            continue

        orphan_count = _orphan_count(
            source=source,
            source_key=check.source_key,
            target=target,
            target_key=check.target_key,
        )
        if orphan_count:
            checks.append(
                PreparedRelationshipCheckResult(
                    check=check,
                    state="failed",
                    orphan_count=orphan_count,
                    message=_failure_message(
                        run_label=prepared_run.label,
                        check=check,
                        orphan_count=orphan_count,
                    ),
                )
            )
            continue
        checks.append(
            PreparedRelationshipCheckResult(
                check=check,
                state="passed",
            )
        )

    return PreparedRelationshipValidationResult(
        run_label=prepared_run.label,
        checks=tuple(checks),
    )


__all__ = [
    "PREPARED_RELATIONSHIP_CHECKS",
    "PreparedRelationshipCheck",
    "PreparedRelationshipCheckResult",
    "PreparedRelationshipValidationError",
    "PreparedRelationshipValidationResult",
    "validate_prepared_relationships",
]
