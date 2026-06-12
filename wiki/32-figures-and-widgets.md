# 32 - Figures And Widgets

Figures, widgets, and sections are the building blocks of dashboard pages.

## Page Lifecycle

`DashboardPage` subclasses use three main hooks:

| Hook | Use |
|---|---|
| `build_page()` | Create widgets, register selectors/sections, and return a stable root layout. |
| `sync_controls()` | Populate widget options and reset invalid values before refresh. |
| `on_global_state_changed()` | Clear page-local caches when global state changes. |

Keep heavy reshaping out of `build_page()`. Treat it as layout assembly.

## Figures

Prefer shared chart helpers from `dashboard/components.py` when possible. Page
methods should:

1. load the required summary or prepared table through `DashboardPage` helpers
2. filter based on widget/global state
3. convert to chart-ready data
4. return a Panel viewable

Common helpers:

- `bar_chart`
- `kpi_box`
- `format_numeric_frame_for_display`
- `data_not_available_card`
- `resolve_summary_visualization`
- `resolve_prepared_visualization`

## Widgets And Selectors

Use page-local widgets for page-local choices, then register them as selectors:

```python
self.purpose_selector = pn.widgets.Select(name="Purpose", options=[])
self.selector(
    "purpose",
    widget=self.purpose_selector,
    label="Purpose",
)
```

Selector registration lets the framework:

- watch widget changes
- refresh affected sections
- derive export metadata
- serialize selector variants for HTML export

Use `exportable=False` for controls that should exist only in live mode.

## Sections

Sections define stable refresh/export regions:

```python
self.section(
    "purpose_chart",
    selectors=("purpose",),
    render=self.render_purpose_chart,
)
```

A section should have one clear render method. That render method should return
a Panel viewable for the current state.

## Shared Helpers

Before adding page-local helpers, check:

| Helper module | Use |
|---|---|
| `dashboard/helpers/category_helpers.py` | Category ordering, labels, and completion. |
| `dashboard/helpers/comparison_helpers.py` | Base-run comparisons and percent differences. |
| `dashboard/helpers/geography_helpers.py` | Geography levels and filters. |
| `dashboard/helpers/person_type_helpers.py` | Person-type selectors and filters. |
| `dashboard/helpers/time_distance_helpers.py` | Time and distance bins. |

## Export Considerations

HTML export can only reproduce interactions that are registered through the
public page API. A page can work in live mode and still be partially exportable
if widgets or dynamic regions are not registered.

To make an interaction exportable:

1. Register the widget with `self.selector(...)`.
2. Register every affected content region with `self.section(...)`.
3. Keep render methods deterministic for each selector combination.
4. Avoid depending on live-only Python callbacks outside the page API.

## Related Chapters

- [33 - Dashboard Page Recipes](33-dashboard-page-recipes.md)
- [34 - HTML Export](34-html-export.md)

