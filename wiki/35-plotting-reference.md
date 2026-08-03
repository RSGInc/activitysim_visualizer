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
