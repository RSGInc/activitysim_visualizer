"""Shared page/group definition types for dashboard page registration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from processor.models import PreparedTableName

if TYPE_CHECKING:
    from dashboard.page_base import DashboardPage

PreparedDataMode = Literal["none", "optional", "required"]
DashboardPageSelectionMode = Literal["default", "all", "explicit"]


@dataclass(frozen=True)
class DashboardPageDefinition:
    """Register one dashboard page for live mode and HTML export."""

    page_id: str
    title: str
    page_cls: type["DashboardPage"] | None = None
    order: int = 0
    group_id: str | None = None
    child_order: int = 0
    default_enabled: bool = True
    prepared_data_mode: PreparedDataMode = "none"
    required_summary_ids: tuple[str, ...] = field(default_factory=tuple)
    optional_summary_ids: tuple[str, ...] = field(default_factory=tuple)
    required_prepared_tables: tuple[PreparedTableName, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        """Attach metadata to the page class at its single declaration site."""
        if self.page_cls is not None:
            self.page_cls.definition = self


@dataclass(frozen=True)
class DashboardDataRequirements:
    """Aggregated summary/prepared-table requirements for a page set."""

    prepared_data_mode: PreparedDataMode = "none"
    required_summary_ids: tuple[str, ...] = field(default_factory=tuple)
    optional_summary_ids: tuple[str, ...] = field(default_factory=tuple)
    required_prepared_tables: tuple[PreparedTableName, ...] = field(
        default_factory=tuple
    )

    @property
    def summary_ids_for_pruning(self) -> tuple[str, ...]:
        """Return all summary IDs that pages may render."""
        merged: list[str] = []
        seen: set[str] = set()
        for summary_id in (*self.required_summary_ids, *self.optional_summary_ids):
            if summary_id in seen:
                continue
            merged.append(summary_id)
            seen.add(summary_id)
        return tuple(merged)


@dataclass(frozen=True)
class DashboardGroupDefinition:
    """Register one top-level dashboard navigation group."""

    group_id: str
    title: str
    order: int = 0
    default_enabled: bool = True
    default_page_id: str | None = None


@dataclass(frozen=True)
class DashboardPageConfigEntry:
    """Normalized dashboard page-selection entry from config."""

    page_id: str
    mode: DashboardPageSelectionMode = "explicit"
    page_ids: tuple[str, ...] = field(default_factory=tuple)
