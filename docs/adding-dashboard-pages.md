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

Each page module declares one `DashboardPage` subclass with the
`@dashboard_page(...)` decorator. Metadata and implementation therefore live at
one declaration site.

The decorator accepts the intentionally narrow page definition fields:

- `page_id`
- `title`
- `order`
- `group_id`
- `default_enabled`
- `prepared_data_mode`
- `required_summary_ids`
- `optional_summary_ids`
- `required_prepared_tables`

Grouped navigation is declared in a sibling `GROUP = DashboardGroupDefinition(...)` inside the package `__init__.py`.

`DashboardGroupDefinition` now uses `default_page_id`, not `default_child_id`.

There is no `child_id`.

Use `required_summary_ids` for tables that must be present before the page can
render its primary workflow. Use `optional_summary_ids` for add-on sections or
demo/external summaries that should be retained when available but should not
make ordinary dashboard/cache loading fail when missing.

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
- avoid heavy data reshaping or cross-run filtering work

`sync_controls()` is optional. It runs before every refresh pass and is the right place to:

- populate selector options from current data availability
- reset invalid widget values to safe defaults
- keep selector value/bootstrap logic out of `render_*()` methods

`on_global_state_changed()` is optional. Use it for page-local cache invalidation when weighting mode, value mode, or available runs change.

## Target Structure

When adding or refactoring a page, aim for this shape:

1. `build_page()`
   - declare widgets
   - register selectors
   - register sections
   - return the stable root layout

2. `sync_controls()`
   - compute selector options from current dashboard state
   - keep selector defaults valid

3. `render_*()` section methods
   - one logical section per render method
   - narrow control flow
   - prefer pure helper functions for chart-ready reshaping

4. shared helpers
   - use `dashboard/helpers/` for logic that appears in multiple pages
   - keep page-local helpers only for truly page-specific business rules

As a rule of thumb:

- `build_page()` should read like layout assembly
- `sync_controls()` should read like selector synchronization
- `render_*()` should read like "load data, handle missing state, render views"

## Reference Pages

Use the current pages below as implementation references when possible:

- `dashboard/pages/overview.py`
  - simplest summary-only page
  - good reference for straightforward section rendering
- `dashboard/pages/raw_trip_demo.py`
  - smallest prepared-data page
  - good reference for `resolve_prepared_visualization(...)`
- `dashboard/pages/trip_summaries/trip_mode.py`
  - good reference for one-selector, one-section chart pages
- `dashboard/pages/long_term_choices/mandatory_location_choice.py`
  - good reference for multi-section geography-driven pages
  - also the main complexity target when refactoring shared geography helpers
- `dashboard/pages/skim_summaries/trip_skims.py`
  - strongest current example of selector sync plus independently refreshed sections
- `dashboard/pages/skim_summaries/tour_skims.py`
  - strongest current example of sectioned live distributions with non-exportable controls

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

## Shared Helper Map

When page logic starts repeating, prefer one of the existing helper modules before
adding page-local utility functions:

- `dashboard/helpers/category_helpers.py`
  - selector option building
  - config-ordered category values
  - config-driven label columns
  - category completion for charts and tables
- `dashboard/helpers/geography_helpers.py`
  - geography column normalization
  - geography level and geography id selector domains
  - geography-level and geography-id filtering
  - all-geographies and all-within-level handling
- `dashboard/helpers/person_type_helpers.py`
  - person-type selector domains
  - person-type filtering
  - total-person-type rollups and weights
- `dashboard/helpers/time_distance_helpers.py`
  - time-bin labels and durations
  - distance-bin sorting
- `dashboard/helpers/comparison_helpers.py`
  - percent-error formatting
  - base-run percent-difference tables
  - weighted average lookups for comparison tables
- `dashboard/pages/skim_summaries/_shared.py`
  - skim-page-specific shared logic that should stay local to skim pages

If a transform is clearly reusable across unrelated pages, move it into
`dashboard/helpers/`. If it only makes sense for one page family, keep it close
to that family, as with the skim shared module or a page-local support module.

## Minimal Example

```python
from __future__ import annotations

import panel as pn

from dashboard import DashboardPage, dashboard_page
from dashboard.page_base import SectionContent


@dashboard_page(
    page_id="my_new_page",
    title="My New Page",
    order=120,
    required_summary_ids=("my_summary_table",),
)
class MyNewPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        self.purpose_sel = self.select(
            "purpose",
            "Purpose",
            options=["Total"],
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
```

## Authoring Rules

Do:

- create widgets in `build_page()`
- use `select(...)` for dropdowns and register other interactive controls with `selector(...)`
- register every refreshable content area with `section(...)`
- return content from section render functions
- keep expensive reshaping work behind `get_filtered_view(...)`
- prefer `require_summaries(...)`, `optional_summary(...)`, `resolve_summary_visualization(...)`, and `resolve_prepared_visualization(...)` over repeated ad hoc state lookups in render code
- add a concise module docstring that explains what the page shows
- add short docstrings to helper functions when they encode a business rule that is not obvious from the function name

Do not:

- assign `section.objects = ...` directly from page code
- declare page-local selector metadata in `@dashboard_page`
- declare export regions in `@dashboard_page`
- use `child_id`
- put large data-transformation blocks inline in `build_page()`
- let `render_*()` methods become catch-all implementations for the entire page

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
2. Add or update the class's `@dashboard_page(...)` metadata.
3. If the page belongs to a group, set `group_id` in the decorator and keep the package `GROUP` aligned with `default_page_id`.
4. Implement `build_page()`.
5. Register selectors and sections.
6. Keep selector option logic in `sync_controls()`.
7. Keep section renderers short and move reusable transforms into shared helpers.
8. Declare the summary/prepared-data contract in `@dashboard_page(...)`.
9. Add or update tests covering selector refresh and missing-data behavior.
10. If the page should export interactively, add an export-focused test slice too.

## Short Recipe

For most new pages, the fastest safe workflow is:

1. Start from a nearby reference page with similar selectors and data shape.
2. Keep `build_page()` limited to widget creation, selector registration, section registration, and layout.
3. Move selector domain logic into `sync_controls()`.
4. Keep each `render_*()` method focused on one section.
5. Extract chart-ready reshaping into a small helper or shared helper module.
6. Use `get_filtered_view(...)` around any repeated cross-run filtering or aggregation.
7. Add one live refresh test and, if the page exports, one export-oriented test slice.
