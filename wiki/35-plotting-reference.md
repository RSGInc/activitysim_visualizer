# 35 - Plotting Reference

Dashboard pages use one plotting interface: `self.plot`. It accepts the
`RunTables` object that `self.data` returns. It applies the session run colors
and count or share mode. It returns a Panel view for a section.

## Standard method

Fetch, query, and plot without converting the data to tuple lists:

```python
data = (
    self.data.summary(
        "trip_mode_by_purpose",
        columns=("purpose", "mode", "trip_count"),
    )
    .where(purpose=self.purpose_sel.value)
    .group("mode", pl.col("trip_count").sum())
    .sort("mode")
)

return self.plot.bar(
    data,
    x="mode",
    y="trip_count",
    title="Trip Mode",
    x_title="Mode",
    y_title="Trips",
)
```

Each chart argument after `data` is keyword-only. The public names are `x`, `y`,
`x_title`, and `y_title`. The interface does not support the former `x_col`,
`y_col`, and `xaxis_title` aliases.

## Chart types

Use:

- `self.plot.bar(...)` for discrete categories;
- `self.plot.density(...)` for ordered distributions such as time or distance;
- `self.plot.line(...)` for an unfilled profile; and
- `self.plot.scatter(...)` for observed-versus-modeled comparisons.

All four methods validate their required columns before they call Plotly. An
error identifies the chart type, run, and missing columns.

```python
return self.plot.density(
    data,
    x="distance_bin",
    y="tour_count",
    title="Tour Distance",
    x_title="Distance (miles)",
    y_title="Tours",
    x_range=(0, 40),
)
```

Sort ordered data in the query. For categorical bars, pass
`category_order=[...]` to use the configured display order. Also use it when
missing categories must keep a stable axis position.

### Keyword Reference

All figure builders accept `x`, `y`, `title`, `x_title`, `y_title`, and
`height`. Additional chart-specific keywords are:

| Chart | Keywords |
|---|---|
| `bar` | `barmode="group"`, `share_y=None`, `value_mode="dashboard"`, `category_order=None`, `show_legend=None` |
| `line` | `value_mode="dashboard"` |
| `density` | `value_mode="dashboard"`, `x_range=None`, `category_order=None`, `tick_values=None`, `tick_text=None`, `hover_x_title=None` |
| `scatter` | `drop_zero_y=False`, `fit_overlays=None`, `fit_annotation="annotation"`, `one_to_one=False`, `legend_on_right=False` |

`self.plot.scatter(...)` also accepts `panel_aspect_ratio`. This argument sets
the size of the returned Panel pane. It does not go to the Plotly figure builder.

For fitted scatterplots, `fit_overlays` is another `RunTables` object or an
iterable of run and frame pairs. Each fit frame must contain the scatter `x`
and `y` columns. It can contain the column specified by `fit_annotation`.
Hovering on the fitted line shows this text. `one_to_one=True` adds a dashed 1:1
line. It gives both axes the same range and locks their scale. Validation pages
use this API for run equations, R-squared values, and sample sizes.

The interface changes run labels for presentation without changing their
identity. It shortens long labels to unique legend and tab labels. Plotly hover
text and exported tab tooltips keep the full label. Scatter point and fit hover
text also include the run name.

## Count and share behavior

`value_mode` has three values:

- `"dashboard"` (the default) follows the Count/Share dashboard toggle;
- `"count"` always plots the supplied values; and
- `"share"` always normalizes each run to 100 percent.

```python
return self.plot.bar(
    data,
    x="mode",
    y="trip_count",
    value_mode="share",
)
```

If a summary contains a defined share, supply that column with `share_y`. The
renderer selects it only in share mode:

```python
return self.plot.bar(
    data,
    x="mode",
    y="trip_count",
    share_y="trip_count_percent",
)
```

Use `share_y` when the denominator has a special meaning that a sum of `y`
cannot reproduce. Do not select count or percent columns in the page only to
follow the global control. The plotting interface does not have `as_percent`,
`normalize`, `percent_y_col`, or `pct_col` arguments.

## Direct figure API

The core builders return `plotly.graph_objects.Figure`. Use this result for
tests or a page-specific annotation:

```python
figure = self.plot.figure.scatter(
    data,
    x="observed_volume",
    y="modeled_volume",
    one_to_one=True,
)
figure.add_vline(x=1000, line_dash="dot")
return self.plot.panel(figure)
```

Use the standard `self.plot.*` methods when a figure does not require a custom
change. They use the same fixed `RenderContext` as export. Thus, live and export
charts get identical colors, labels, hover policy, and value mode. They do not
require module-global setup.

## Tables and layout

Display helpers are grouped by responsibility under `dashboard.rendering`:

```python
from dashboard.rendering import data_table, selector_row
```

`data_table(data, title)` accepts `RunTables` directly. Use `self.plot.kpi(...)`
for page KPI values. It uses the same run context as charts. Selector rows,
missing-data cards, legends, and layout helpers are in
`dashboard.rendering.layout`. Numeric and column formatting are in
`dashboard.rendering.tables`.

The `dashboard.rendering` facade exports these non-plot helpers:

| API | Purpose |
|---|---|
| `data_table()`, `to_pandas()` | Render run-aware tables or convert supported Polars/Pandas input at the presentation boundary. |
| `format_numeric()`, `format_numeric_frame()` | Apply display-only numeric precision. |
| `drop_index_columns()`, `column_titles()` | Remove serialized index artifacts and create human-readable column titles. |
| `standardize_keys()` | Normalize a table iterable to common key/value column names. |
| `selector_row()`, `control_row()`, `control_row_spacer()` | Build consistent page control layouts. |
| `data_unavailable_card()` | Render the standard missing-data diagnostic card. |
| `run_legend_entries()`, `run_legend_panes()` | Build run/color legend metadata or panes. |

`column_title_metadata()` is available from
`dashboard.rendering.tables` for serializer-aware title metadata, but is not
part of the package-level facade.

## Testing charts

Test the figure instead of constructing a full Panel layout:

```python
context = RenderContext(
    run_colors=("#3366cc",),
    run_labels=("Base",),
)
figure = Plotter(context).figure.bar(data, x="mode", y="trip_count")

assert figure.data[0].name == "Base"
assert list(figure.data[0].x) == ["Walk", "Bike"]
```

This method keeps plot tests fast. It separates data and query behavior from Panel.

Use the focused plotting target during development:

```bash
pytest tests/test_figure_builders.py
```

Test page query behavior in `tests/test_page_authoring.py`. Execute the complete
HTML export suite as a separate release check.

## Related Chapters

- [32 - Figures And Widgets](32-figures-and-widgets.md)
- [45 - Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md)
- [46 - Testing](46-testing.md)
