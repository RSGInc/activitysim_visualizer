# 35 - Plotting Reference

Dashboard pages use one plotting surface: `self.plot`. It accepts the same
`RunTables` object returned by `self.data`, applies the session's run colors and
count/share mode, and returns a Panel view ready for a section.

## The normal path

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

Every chart argument after `data` is keyword-only. The short names (`x`, `y`,
`x_title`, and `y_title`) are the complete public vocabulary; the former
`x_col`, `y_col`, and `xaxis_title` aliases are not supported.

## Chart types

Use:

- `self.plot.bar(...)` for discrete categories;
- `self.plot.density(...)` for ordered distributions such as time or distance;
- `self.plot.line(...)` for an unfilled profile; and
- `self.plot.scatter(...)` for observed-versus-modeled comparisons.

All four validate their required columns before calling Plotly. An error names
the chart type, run, and missing columns.

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
`category_order=[...]` when the configured display order matters or missing
categories must keep a stable axis position.

### Keyword Reference

All figure builders accept `x`, `y`, `title`, `x_title`, `y_title`, and
`height`. Additional chart-specific keywords are:

| Chart | Keywords |
|---|---|
| `bar` | `barmode="group"`, `share_y=None`, `value_mode="dashboard"`, `category_order=None`, `show_legend=None` |
| `line` | `value_mode="dashboard"` |
| `density` | `value_mode="dashboard"`, `x_range=None`, `category_order=None`, `tick_values=None`, `tick_text=None`, `hover_x_title=None` |
| `scatter` | `drop_zero_y=False`, `fit_overlays=None`, `fit_annotation="annotation"`, `one_to_one=False`, `legend_on_right=False` |

`self.plot.scatter(...)` additionally accepts `panel_aspect_ratio`; this sizes
the returned Panel pane and is not passed to the Plotly figure builder.

For fitted scatterplots, `fit_overlays` is another `RunTables` or iterable of
run/frame pairs. Each fit frame must contain the same `x` and `y` columns used
by the scatter and may contain the column named by `fit_annotation`. That text
is shown when the fitted line is hovered. `one_to_one=True` adds a dashed 1:1
line, gives both axes the same range, and locks their scale. The validation
pages use this API for per-run equations, R-squared values, and sample sizes.

Run labels are presentation-safe without changing their underlying identity.
Long labels are shortened to unique legend/tab labels, while Plotly hovers and
exported tab tooltips retain the full label. Scatter point and fit hovers also
include the owning run name.

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

If a summary already contains a specifically defined share, provide that
column with `share_y`. The renderer selects it only in share mode:

```python
return self.plot.bar(
    data,
    x="mode",
    y="trip_count",
    share_y="trip_count_percent",
)
```

Use `share_y` when the denominator has domain meaning that cannot be recovered
by summing `y`. Do not select between count and percent columns in the page just
to follow the global toggle. There are no `as_percent`, `normalize`,
`percent_y_col`, or `pct_col` plotting arguments.

## Figure-first escape hatch

The core builders return `plotly.graph_objects.Figure`, which is useful for
testing or for adding a genuinely page-specific annotation:

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

Prefer the normal `self.plot.*` methods when no figure customization is needed.
They use the same immutable `RenderContext` as export, so live and exported
charts receive identical colors, labels, hover policy, and value mode without
module-global setup.

## Tables and layout

Display helpers are grouped by responsibility under `dashboard.rendering`:

```python
from dashboard.rendering import data_table, selector_row
```

`data_table(data, title)` accepts `RunTables` directly. Page KPI values should
use `self.plot.kpi(...)`, which shares the same run context as charts. Selector
rows, missing-data cards, legends, and other layout helpers live in
`dashboard.rendering.layout`; numeric and column formatting lives in
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

This keeps plot tests fast and isolates data/query behavior from Panel.

Use the focused plotting target during development:

```bash
pytest tests/test_figure_builders.py
```

Page query behavior belongs in `tests/test_page_authoring.py`; the complete
HTML export suite is a separate release-boundary check.

## Related Chapters

- [32 - Figures And Widgets](32-figures-and-widgets.md)
- [45 - Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md)
- [46 - Testing](46-testing.md)
