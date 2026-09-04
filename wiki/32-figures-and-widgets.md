# 32 - Figures And Widgets

Pages use one authoring model for data access, selectors, refreshable sections,
and figures. The framework controls widget synchronization, query identity,
missing-data diagnostics, and export metadata.

## Page Lifecycle

Each page subclasses `DashboardPage` and implements `build_page()`, which
declares selectors and sections once and returns a stable Panel layout.

`DashboardPage.__init__()` creates `self.data`, page state, and the component
registries before calling `build_page()`. A standard page therefore does not
need its own `__init__`. If special initialization is necessary, create any
attributes needed by `build_page()` before calling
`super().__init__(state, config)`. Keep declarations in `build_page()` and never
put an `__init__` method in an implementation mixin.

The main author-facing objects are:

- `self.data` for summary and prepared `RunTables`
- `self.select(...)` for standard selection lists, including dynamic options
- `self.selector(...)` only for custom widgets
- `self.section(...)` for refreshable visible regions
- `self.feature(...)` for a namespaced group of selectors and sections
- `self.query(...)` for repeated or expensive transformations
- `self.plot` for figures and tables


## Data And Figures

For complete examples of a standard chart, a Plotly customization, a new shared
figure type, a custom widget, and a table, use the
[Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md).
For the complete chart-method, count/share, table, and figure-testing API, see
the [Plotting Reference](35-plotting-reference.md).

Load only the required data through `self.data.summary(...)` or
`self.data.summaries(...)`. `RunTables` applies the same Polars operation to
each run. It keeps labels and availability issues. It supports operations
such as `where`, `with_columns`, `group`, `select`, `sort`, `join`, `map`,
`requiring`, and `drop_empty`.

A `RunTables` value is true when at least one run has a nonempty compatible
table. Iteration excludes runs with a missing table, schema mismatch, failure,
or empty input. `data.issues` describes these runs. `data.partial` means that
there are usable and excluded runs. Query operations keep these issues. A
filter can make a frame empty without removal. Call `.drop_empty()` when later
code must ignore these runs.

The `columns=` argument to `summary()` and `prepared()` is a compatibility
check. The system excludes a run that is missing a named column. It also adds a
schema diagnostic. The argument does not select columns in the returned frames.
Use `.select(...)` to select a smaller schema.

Pass `RunTables` to `self.plot` methods when possible. Figures, tables, layout,
and plotter logic are in `dashboard/rendering/`. Shared page helpers are in
`dashboard/helpers/`.

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

The page-facing data API is:

| API | Result |
|---|---|
| `self.data.summary(id, weighting=None, columns=(), required=None)` | One summary across usable runs. `columns` performs a schema compatibility check. |
| `self.data.summaries(*ids, columns=None, required=None)` | A dictionary of summary ID to `RunTables`. |
| `self.data.prepared(table, columns=(), weighting_mode=None)` | One declared prepared table across loaded runs. |
| `self.data.prepared_runs(weighting_mode=None)` | Direct `RunData` access for features that require matrices or other non-table state. |
| `self.data.summary_series(id, weighting=None)` | Specialized skim-summary view that retains summary-series metadata. |

For `summary()` and `summaries()`, `required` has these exact meanings:

| Value | Behavior when no run is usable |
|---|---|
| `None` | Required when the ID appears in the page definition's `required_summary_ids`; optional otherwise. |
| `True` | Record the selection and emit the page's required-summary warning even when the decorator did not declare it. |
| `False` | Record diagnostics but suppress the required-summary warning. Use this for an independent optional feature. |

`required` does not make the lookup raise and does not render a card by itself.
The section must still test the returned `RunTables` and choose its standard
unavailable or optional-feature fallback. `columns=` is evaluated per run, so
one compatible run can render while other runs appear in `data.issues`.

`RunTables` is iterable and indexable as `(run_label, DataFrame)` pairs. Its
public query interface is:

| API | Behavior |
|---|---|
| `.where(column=value, ...)` | Equality filter; list, tuple, set, or frozenset values use membership. |
| `.with_columns(*exprs)` / `.select(*exprs)` / `.sort(*by)` | Apply the corresponding Polars operation to every run. |
| `.group(by, *aggs, **named_aggs)` | Group and aggregate every run. |
| `.join(other, on=..., how="left", coalesce=None)` | Join matching run labels and merge availability issues/source IDs. |
| `.map(transform)` | Apply a DataFrame-to-DataFrame transform to every run. |
| `.requiring(*columns)` | Keep frames containing all named columns. Prefer the lookup `columns=` check when exclusions should produce schema diagnostics. |
| `.drop_empty()` | Remove frames made empty by a previous operation. |
| `.values(column)` | Distinct non-null values in first-seen run order. |
| `.scalar(column, default=None)` | First value for each usable run. |
| `.to_list()` | Materialize tuples for an external API that cannot consume `RunTables`. |
| `.available`, `.partial`, `.issues`, `.source_ids` | Availability and provenance metadata retained through fluent operations. |

Each issue contains `label`, `status`, `detail`, `source_kind`, `source_id`,
`missing_columns`, and available run/cache identity. Plotting a partial
`RunTables` value renders only its usable runs and keeps the exclusions in page
and export diagnostics. Do not replace it with `.to_list()` before the normal
render boundary unless an external API requires tuples; that discards the
structured availability object from subsequent fluent operations.

## Query Cache Contract

`self.query(factory)` accepts one zero-argument callable and returns the
callable's result. On a cache miss it executes `factory`; on a hit it returns
the stored value. Its identity contains:

- page ID;
- current global dashboard state, including weighting, Values, and segment
  presentation state;
- active section ID;
- current values of selectors declared by that section;
- callable module, qualified name, file, and first line; and
- simple closure/default/keyword-default values. Complex captured objects are
  represented by type, so capture the scalar values that actually change the
  calculation.

A selector affects query identity only when its ID appears in the active
section's `selectors=(...)` declaration. Always declare every selector that
changes the renderer. Global state or a declared selector change creates a new
identity automatically. Call `self.clear_query_cache()` only after mutable
external state changes outside those declared inputs; it clears this page's
memoized queries.

```python
def render_body(self):
    purpose = self._purpose_by_label[self.purpose.value]
    data = self.data.summary(
        "trip_mode_by_tour_purpose_and_tour_mode",
        columns=("tour_purpose", "trip_mode", "trip_count"),
    )
    return self.query(
        lambda: data.where(tour_purpose=purpose)
        .group("trip_mode", pl.col("trip_count").sum())
        .drop_empty()
    )
```

## Calculation Notes

Calculation notes are expandable HTML details below annotated charts and
tables. They have no external dependencies. To hide all notes, use:

```yaml
dashboard:
  include_notes: false
```

`dashboard/calculation_notes.yaml` contains the content. The top-level `methods`
mapping contains reusable method explanations. `notes` contains stable note
IDs. Each note requires `summary`, `method`, and a nonempty `sources` list. A
note can also contain `label`, `method_text`, `formula`, `source_filters`, and
grouped `details`. The loader validates unknown fields and method references.

Page authors attach a note to a registered selector-driven section with:

```python
body = self.section(
    "comparison",
    selectors=("facility_type",),
    render=self.render_comparison,
)
return self.noted_section("traffic.observed_model_fit", body)
```

Use `self.noted_view(note_id, view)` for an individual plot or table outside the
registered section container. `self.section_note(...)` is the low-level helper.
It rejects unregistered sections. Notes use the same page layout in live mode
and HTML export.

## Selectors

Declare a standard selection list and its option domain in one place:

```python
self.purpose = self.select(
    "purpose",
    "Purpose",
    options=self.purpose_options,
    default="first",
)
```

Before rendering dependent sections, the framework calls an option provider and
repairs stale values. `default` can be `"first"`, `"last"`, or a callable.
Use `self.selector(...)` only for a custom checkbox, numeric input, or other
widget that `select(...)` cannot define.

## Sections And Features

Sections declare exactly which selectors affect them:

```python
chart = self.section(
    "purpose_chart",
    selectors=("purpose",),
    render=self.render_mode_chart,
)
```

A section renderer can return one Panel `Viewable`, or a list or tuple of
`Viewable` objects. The lifecycle replaces the container content after each
render, so the renderer must not replace the stable section container itself.

For a large page, use `self.feature("comparison")` to give a name to one
workflow. Feature component IDs become `comparison.metric`, `comparison.body`,
and similar names. Features use the same lifecycle and export behavior as the
parent page.

Large controllers can also use private implementation mixins in a `_<page>/`
package. Mixins organize source responsibilities, while `PageFeature` organizes
live components; a page can use both. Give each mixin one purpose and no
`__init__` method. Keep pure transforms as functions, and preserve page and
component IDs during a source-only refactor.

### Large-Page Implementation Mixins

Keep the registered page module as the public facade and add only the private
modules that correspond to real responsibilities:

```text
pages/example.py
pages/_example/
  __init__.py
  contracts.py
  transforms.py
  composition.py
  selector_domains.py
  features.py
```

- `contracts.py` owns stable summary, category, option, and ordering IDs.
- `transforms.py` owns pure dataframe-to-dataframe calculations.
- `composition.py` owns selector, feature, section, and layout declaration.
- `selector_domains.py` owns dynamic options and display-to-raw mappings.
- `features.py` owns lookup/query/render methods grouped by visible workflow.

The public class may assemble those responsibilities with multiple inheritance:

```python
@dashboard_page(page_id="example", title="Example", group_id="group")
class ExamplePage(
    ExampleCompositionMixin,
    ExampleSelectorDomainsMixin,
    ExampleFeatureMixin,
    DashboardPage,
):
    pass
```

Each mixin method receives the final `ExamplePage` instance. Python resolves
methods from left to right through the declared bases, with `DashboardPage`
last. Mixins are not standalone pages and should not be instantiated.

Keep this pattern narrow:

- do not define `__init__` in an implementation mixin
- give each mixin one coherent responsibility
- do not define the same method in multiple mixins
- make cross-mixin calls clear from names and module boundaries
- keep stateless pure functions outside mixins
- preserve page, selector, section, and export IDs during source-only refactors

Mixins organize Python source, while `PageFeature` organizes registered live
components. Use one page class until the composition, domain, transformation,
and rendering boundaries are stable.

## Shared Helpers

Before you add page-local utilities, examine these modules:

| Module | Use |
|---|---|
| `dashboard/helpers/category_helpers.py` | Category ordering, labels, and completion. |
| `dashboard/helpers/comparison_helpers.py` | Base-run comparisons and percent differences. |
| `dashboard/helpers/distance_range.py` | Shared distance-range behavior. |
| `dashboard/helpers/geography_helpers.py` | Geography levels and filters. |
| `dashboard/helpers/person_type_helpers.py` | Person-type selectors and filters. |
| `dashboard/helpers/time_distance_helpers.py` | Time and distance bins. |

## Export Considerations

The same selectors and sections control live and export behavior. Make sure
that render methods give the same result for each selector state. Do not use
unregistered live-only callbacks. Export can include only selector values that
exist at export time.

## Related Chapters

- [31 - Dashboard Page Contract](31-dashboard-pages.md)
- [33 - Dashboard Page Recipes](33-dashboard-page-recipes.md)
- [34 - HTML Export](34-html-export.md)
- [35 - Plotting Reference](35-plotting-reference.md)
- [45 - Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md)
