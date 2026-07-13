"""Shared page/group definition types for dashboard page registration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, TypeVar

from processor.models import PreparedTableName

if TYPE_CHECKING:
    from dashboard.page_base import DashboardPage

PageT = TypeVar("PageT", bound="DashboardPage")

PreparedDataMode = Literal["none", "optional", "required"]


@dataclass(frozen=True)
class DashboardPageDefinition:
    """Register one dashboard page for live mode and HTML export."""

    page_id: str
    title: str
    page_cls: type["DashboardPage"] | None = None
    order: int = 0
    group_id: str | None = None
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


def dashboard_page(
    *,
    page_id: str,
    title: str,
    order: int = 0,
    group_id: str | None = None,
    default_enabled: bool = True,
    prepared_data_mode: PreparedDataMode = "none",
    required_summary_ids: tuple[str, ...] = (),
    optional_summary_ids: tuple[str, ...] = (),
    required_prepared_tables: tuple[PreparedTableName, ...] = (),
):
    """Declare a dashboard page and attach its discovery metadata to the class."""

    def decorate(page_cls: type[PageT]) -> type[PageT]:
        DashboardPageDefinition(
            page_id=page_id,
            title=title,
            page_cls=page_cls,
            order=order,
            group_id=group_id,
            default_enabled=default_enabled,
            prepared_data_mode=prepared_data_mode,
            required_summary_ids=required_summary_ids,
            optional_summary_ids=optional_summary_ids,
            required_prepared_tables=required_prepared_tables,
        )
        return page_cls

    return decorate


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
