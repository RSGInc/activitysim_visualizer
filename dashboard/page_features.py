"""Composable, page-local feature blocks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import panel as pn
    from dashboard.page_declarations import (
        DefaultPolicy,
        SectionContent,
        SelectorOptions,
    )
    from dashboard.page_lifecycle import DashboardPage


class PageFeature:
    """A coherent block of selectors, queries, and sections within one page.

    Feature ids prefix component ids, so a large page can be assembled from small
    domain objects without creating another page type or managing cache keys.
    """

    def __init__(self, page: DashboardPage, feature_id: str) -> None:
        self.page = page
        self.feature_id = feature_id

    def component_id(self, local_id: str) -> str:
        return f"{self.feature_id}.{local_id}"

    def select(
        self,
        local_id: str,
        label: str,
        *,
        options: SelectorOptions | Callable[[], SelectorOptions],
        default: DefaultPolicy = "first",
        **widget_options,
    ) -> pn.widgets.Select:
        return self.page.select(
            self.component_id(local_id),
            label,
            options=options,
            default=default,
            **widget_options,
        )

    def section(
        self,
        local_id: str,
        *,
        selectors: tuple[str, ...] = (),
        render: Callable[[], SectionContent],
        **options,
    ) -> pn.Column:
        return self.page.section(
            self.component_id(local_id),
            selectors=tuple(
                selector
                if selector in self.page._registered_selectors
                else self.component_id(selector)
                for selector in selectors
            ),
            render=render,
            **options,
        )

    def query(self, factory: Callable):
        return self.page.query(factory)


__all__ = ["PageFeature"]
