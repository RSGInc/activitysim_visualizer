"""Explicit values exchanged between runtime workflow operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from processor.models import RunData


@dataclass(frozen=True)
class WorkflowPlan:
    """Resolved pipeline intent shared by the CLI and workflow operations."""

    logical_steps: tuple[str, ...]
    runtime_steps: tuple[str, ...]
    dashboard_mode: str = "none"
    overwrite: bool = False

    @classmethod
    def from_config(cls, config: Any) -> "WorkflowPlan":
        return cls.for_steps(config, config.pipeline.steps)

    @classmethod
    def for_steps(cls, config: Any, steps: Any) -> "WorkflowPlan":
        """Resolve runtime operations for an explicit logical step sequence."""
        logical_steps = tuple(steps)
        runtime_steps: list[str] = []
        if any(step in logical_steps for step in ("prepare", "skimjoin")):
            runtime_steps.append("prepare")
        if any(step in logical_steps for step in ("summarize", "segment")):
            runtime_steps.append("summarize")
        if "dashboard" in logical_steps:
            runtime_steps.append("dashboard")
        return cls(
            logical_steps=logical_steps,
            runtime_steps=tuple(runtime_steps),
            dashboard_mode=str(config.pipeline.dashboard_mode).lower(),
            overwrite=bool(config.pipeline.overwrite),
        )

    def includes(self, step: str) -> bool:
        return step in self.logical_steps


@dataclass
class PreparedRunsArtifact:
    """Prepared tables and their stable run identities."""

    runs: list[tuple[str, RunData]] = field(default_factory=list)
    by_key: dict[str, tuple[str, RunData]] = field(default_factory=dict)
    run_keys: list[str] = field(default_factory=list)
    fingerprints_by_key: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass
class SummaryRunsArtifact:
    """Summary tables plus the prepared artifact used to build them."""

    runs: list[Any] = field(default_factory=list)
    prepared: PreparedRunsArtifact = field(default_factory=PreparedRunsArtifact)


@dataclass(frozen=True)
class SummaryCacheInspection:
    """Reusable cached summaries and the table ids that still need rebuilding."""

    runs: tuple[Any, ...] = ()
    reusable_summary_ids: tuple[str, ...] = ()
    stale_summary_ids: tuple[str, ...] = ()
