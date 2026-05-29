# Adding Dashboard Pages

This guide covers the new public dashboard page authoring API.

Use it when the summary table you need already exists and you want to add or refactor a page under `dashboard/pages/`.

If the summary does not exist yet, start with [adding-summaries.md](adding-summaries.md).

## Mental Model

A dashboard page now has one source of truth for page-local interactivity:

1. register selectors once
2. register sections once
3. render section content from pure-ish render functions

The framework takes care of:

- widget watchers
- stable section containers
- rerendering only the affected sections when a selector changes
- rerendering all sections when the global dashboard state changes
- deriving export selector and export region metadata from those same registrations

## Registration Objects

Each page module still exports a module-level `PAGE = DashboardPageDefinition(...)`.

`DashboardPageDefinition` is intentionally narrow:

- `page_id`
- `title`
- `page_cls`
- `order`
- `group_id`
- `default_enabled`
- `prepared_data_mode`
- `required_summary_ids`
- `required_prepared_tables`

Grouped navigation is declared in a sibling `GROUP = DashboardGroupDefinition(...)` inside the package `__init__.py`.

`DashboardGroupDefinition` now uses `default_page_id`, not `default_child_id`.

There is no `child_id`.

## Page Lifecycle

Page authors subclass `DashboardPage`.

The public lifecycle hooks are:

- `build_page(self) -> pn.viewable.Viewable`
- `sync_controls(self) -> None`
- `on_global_state_changed(self) -> None`

`build_page()` is required. It should:

- create widgets
- register selectors
- register sections
- return one stable root view

`sync_controls()` is optional. It runs before every refresh pass and is the right place to:

- populate selector options from current data availability
- reset invalid widget values to safe defaults

`on_global_state_changed()` is optional. Use it for page-local cache invalidation when weighting mode, value mode, or available runs change.

## Public Helpers

The core authoring helpers are:

```python
self.selector(
    selector_id,
    widget=...,
    label="...",
    exportable=True,
)

self.section(
    section_id,
    selectors=("selector_a", "selector_b"),
    export=True,
    render=self.render_section_name,
)

self.section_view("section_id")
self.mark_section_stale("section_id")
```

The most commonly used data helpers remain available on `DashboardPage`:

- `resolve_summary_visualization(...)`
- `resolve_prepared_visualization(...)`
- `require_summary(...)`
- `require_summaries(...)`
- `optional_summary(...)`
- `unavailable_visualization(...)`
- `data_not_available_card(...)`
- `get_filtered_view(...)`
- `clear_filtered_view_cache(...)`
- `as_percent`
- `weighting_key`

## Minimal Example

```python
from __future__ import annotations

import panel as pn

from dashboard.page_base import DashboardPage, SectionContent
from dashboard.page_definitions import DashboardPageDefinition


class MyNewPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        self.purpose_sel = self.selector(
            "purpose",
            widget=pn.widgets.Select(name="Purpose", options=["Total"], value="Total"),
            label="Purpose",
        )

        summary_section = self.section(
            "summary",
            selectors=("purpose",),
            render=self.render_summary,
        )

        return pn.Column(
            pn.pane.Markdown("## My New Page"),
            pn.Row(pn.pane.Markdown("**Purpose:**"), self.purpose_sel),
            summary_section,
            sizing_mode="stretch_width",
        )

    def sync_controls(self) -> None:
        options = self._purpose_options()
        self.purpose_sel.options = options
        if self.purpose_sel.value not in options:
            self.purpose_sel.value = options[0]

    def render_summary(self) -> SectionContent:
        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            return [
                self.data_not_available_card(
                    detail="This page depends on precomputed summaries.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
        return [pn.pane.Markdown(f"Current purpose: {self.purpose_sel.value}")]


PAGE = DashboardPageDefinition(
    page_id="my_new_page",
    title="My New Page",
    order=120,
    page_cls=MyNewPage,
    required_summary_ids=("my_summary_table",),
)

MyNewPage.definition = PAGE
```

## Authoring Rules

Do:

- create widgets in `build_page()`
- register every page-local interactive control with `selector(...)`
- register every refreshable content area with `section(...)`
- return content from section render functions
- keep expensive reshaping work behind `get_filtered_view(...)`

Do not:

- call `_watch_widget(...)` on newly authored pages
- assign `section.objects = ...` directly from page code
- declare page-local selector metadata in `PAGE`
- declare export regions in `PAGE`
- use `child_id`

## Refresh Semantics

The runtime now refreshes at section granularity.

Selector change:

- only sections that depend on that selector rerender

Global state change:

- all sections rerender

Sections declared with `selectors=()` only rerender on global refresh unless you explicitly call `mark_section_stale(...)`.

## Grouped Pages

Grouped pages are identified only by leaf `page_id`.

Live config uses leaf page ids inside a group:

```yaml
dashboard:
  live:
    pages:
      - overview
      - tours:
        - tour_summary
        - tour_mode
```

The group package defines:

```python
GROUP = DashboardGroupDefinition(
    group_id="tours",
    title="Tours",
    order=30,
    default_page_id="tour_summary",
)
```

## Export

Export metadata is derived from runtime selector and section registration.

That means:

- registered selectors become export selector metadata
- registered exportable sections become export regions
- section selector dependencies define which selector combinations need pre-rendered variants

Grouped export config uses leaf page ids:

```yaml
dashboard:
  export:
    pages:
      trip_summaries:
        children:
          trip_mode:
            tour_purpose: all
```

## Checklist

1. Add or update the page module under `dashboard/pages/`.
2. Add or update the module-level `PAGE`.
3. If the page belongs to a group, set `group_id` on `PAGE` and keep the package `GROUP` aligned with `default_page_id`.
4. Implement `build_page()`.
5. Register selectors and sections.
6. Declare the summary/prepared-data contract in `PAGE`.
7. Add or update tests covering selector refresh and missing-data behavior.
8. If the page should export interactively, add an export-focused test slice too.
