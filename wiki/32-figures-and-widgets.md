# 32 - Figures And Widgets

Current pages declare data access, selectors, independently refreshable
sections, and figures through one shared authoring model. Framework code owns
widget synchronization, query identity, missing-data diagnostics, and export
metadata.

## Page Lifecycle

Every page subclasses `DashboardPage` and implements `build_page()`. That method
declares selectors and sections once and returns a stable Panel layout.

`DashboardPage.__init__()` calls `build_page()` after it creates `self.data`,
page state, and the component registries. Ordinary pages should therefore not
define their own `__init__`. If specialized initialization is unavoidable, it
must call `super().__init__(state, config)`, and attributes used by
`build_page()` must exist before that call. In practice, put declarations in
`build_page()` and keep implementation mixins free of `__init__` methods.

The main author-facing objects are:

- `self.data` for summary and prepared `RunTables`
- `self.select(...)` for ordinary dropdowns, including dynamic options
- `self.selector(...)` only for custom widgets
- `self.section(...)` for refreshable visible regions
- `self.feature(...)` for a namespaced group of selectors and sections
- `self.query(...)` for repeated or expensive transformations
- `self.plot` for figures and tables

Do not add routine `sync_controls()` or page-authored cache keys. Option
providers and section dependencies give the framework enough information to do
that work.

## Data And Figures

For end-to-end examples of an ordinary chart, a Plotly customization, a new
shared figure type, a custom widget, and a table, use the
[Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md).

Load the narrowest useful data selection through `self.data.summary(...)` or
`self.data.summaries(...)`. `RunTables` applies the same Polars operation across
runs while retaining labels and availability issues; it supports operations
such as `where`, `with_columns`, `group`, `select`, `sort`, `join`, `map`,
`requiring`, and `drop_empty`.

A `RunTables` value is truthy when at least one run has a non-empty compatible
table. Runs with a missing table, schema mismatch, failure, or empty input are
excluded from iteration and described in `data.issues`; consequently,
`data.partial` means there are both usable and excluded runs. Fluent operations
preserve those issues. Filtering can make a frame empty without removing it, so
call `.drop_empty()` when downstream code should ignore those runs.

The `columns=` argument to `summary()` and `prepared()` is a compatibility
check: a run missing any named column is excluded with a schema diagnostic. It
does **not** project the returned frames. Use `.select(...)` when a transform
needs a narrower schema.

Pass `RunTables` to `self.plot` methods where possible. Shared rendering lives
under `dashboard/rendering/`, including figures, tables, layout, and plotter
logic. Cross-page domain helpers live under `dashboard/helpers/`.

```python
def render_mode_chart(self):
    data = self.data.summary(
        "trip_mode_by_tour_purpose_and_tour_mode",
        columns=("tour_purpose", "trip_mode", "trip_count"),
    )
    if not data:
        return self.summary_only_unavailable_card()
    chart_data = self.query(
        lambda: data.where(tour_purpose=self.purpose.value)
        .group("trip_mode", pl.col("trip_count").sum())
        .drop_empty()
    )
    return self.plot.bar(chart_data, x="trip_mode", y="trip_count")
```

## Selectors

Declare a normal dropdown with its option domain in one place:

```python
self.purpose = self.select(
    "purpose",
    "Purpose",
    options=self.purpose_options,
    default="first",
)
```

An option provider is called before dependent sections render. The framework
repairs stale values. `default` may be `"first"`, `"last"`, or a callable.
Use `self.selector(...)` only when wrapping a custom checkbox, numeric input, or
another widget that `select(...)` cannot express.

## Sections And Features

Sections declare exactly which selectors affect them:

```python
chart = self.section(
    "purpose_chart",
    selectors=("purpose",),
    render=self.render_mode_chart,
)
```

A section renderer may return one Panel `Viewable`, or a list/tuple of
`Viewable` objects. It should not mutate the stable section container itself;
the lifecycle replaces that container's contents after each render.

For a large page, use `self.feature("comparison")` to namespace a coherent
workflow. Feature component IDs become `comparison.metric`, `comparison.body`,
and so on. Features participate in the same lifecycle and export behavior as
the parent page.

Large controllers may also use private implementation mixins under a
`_<page>/` package. Mixins organize source responsibilities; `PageFeature`
organizes live components. A refactored page commonly uses both. Keep mixins
focused, do not give them `__init__` methods, keep pure transforms as functions,
and preserve page/component IDs during source-only refactors.

## Shared Helpers

Check these before adding page-local utilities:

| Module | Use |
|---|---|
| `dashboard/helpers/category_helpers.py` | Category ordering, labels, and completion. |
| `dashboard/helpers/comparison_helpers.py` | Base-run comparisons and percent differences. |
| `dashboard/helpers/distance_range.py` | Shared distance-range behavior. |
| `dashboard/helpers/geography_helpers.py` | Geography levels and filters. |
| `dashboard/helpers/person_type_helpers.py` | Person-type selectors and filters. |
| `dashboard/helpers/time_distance_helpers.py` | Time and distance bins. |

## Export Considerations

Export behavior derives from the same selectors and sections used live. Keep
render methods deterministic for each selector state and avoid unregistered
live-only callbacks. Export can only include selector values generated at
export time.

## Related Chapters

- [31 - Dashboard Pages](31-dashboard-pages.md)
- [33 - Dashboard Page Recipes](33-dashboard-page-recipes.md)
- [34 - HTML Export](34-html-export.md)
- [45 - Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md)
