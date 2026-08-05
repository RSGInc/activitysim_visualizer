# 45 - Dashboard Extension Cookbook

This chapter gives examples for a page, page group, selector, custom widget,
table, and reusable figure. The examples use the declarative page lifecycle.
Selectors control option domains. Sections control refresh dependencies. Pages
read data through `self.data`.

## Worked Example: Add A Page To An Existing Group

In this example, the registered summary `trips_by_mode` has `trip_mode` and
`trip_count` columns. Create one discoverable final module:

```text
dashboard/pages/trip_summaries/trip_mode_totals.py
```

The complete first version can be small:

```python
from __future__ import annotations

import panel as pn

from dashboard import DashboardPage, dashboard_page


@dashboard_page(
    page_id="trip_mode_totals",
    title="Trip Mode Totals",
    group_id="trip_summaries",
    order=90,
    required_summary_ids=("trips_by_mode",),
)
class TripModeTotalsPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        body = self.section("body", render=self.render_body)
        return self.new_section(
            pn.pane.Markdown("## Trip Mode Totals"),
            body,
        )

    def render_body(self):
        data = self.data.summary(
            "trips_by_mode",
            columns=("trip_mode", "trip_count"),
        )
        if not data:
            return self.summary_only_unavailable_card()
        return self.plot.bar(
            data,
            x="trip_mode",
            y="trip_count",
            title="Trips By Mode",
            x_title="Trip Mode",
            y_title="Trips",
        )
```

Discovery imports public child modules automatically. Do not edit a central
page list. The decorator defines the identity and data requirements.

Enable the page explicitly while developing:

```yaml
dashboard:
  live:
    pages:
      - trip_summaries:
          - trip_mode_totals
```

## Add A Dynamic Selector

In this example, the summary contains `tour_purpose`, `trip_mode`, and
`trip_count`. Add a purpose list with options from the loaded data:

```python
from dashboard.helpers.category_helpers import column_options
from dashboard.rendering import selector_row


def build_page(self):
    self.purpose = self.select(
        "purpose",
        "Tour Purpose",
        options=self.purpose_options,
    )
    body = self.section(
        "body",
        selectors=("purpose",),
        render=self.render_body,
    )
    return self.new_section(
        pn.pane.Markdown("## Trip Mode Totals"),
        selector_row(self.purpose),
        body,
    )


def purpose_options(self):
    data = self.data.summary("trips_by_mode_and_purpose")
    options, self._purpose_by_label = column_options(
        data.to_list(),
        "tour_purpose",
        category_id="tour_purpose",
        config=self.config,
    )
    return options
```

The option provider executes before the framework renders a dependent section. If
available options change, the framework uses the `default` policy to repair an
invalid selection.

Use the raw value for the filter. Do not use its display label:

```python
raw_purpose = self._purpose_by_label[self.purpose.value]
data = self.data.summary("trips_by_mode_and_purpose")
chart_data = self.query(
    lambda: data.where(tour_purpose=raw_purpose).select(
        "trip_mode", "trip_count"
    )
)
```

`self.query()` gets its cache identity from global state, the active section,
declared selectors, callable location, and captured values. Do not create a
page-local cache key.

## Add A Custom Widget

Use `self.select()` for ordinary dropdowns. For a checkbox, slider, or other
Panel widget, register it with `self.selector()`:

```python
self.hide_auto = self.selector(
    "hide_auto",
    widget=pn.widgets.Checkbox(value=False),
    label="Hide Auto Modes",
)

body = self.section(
    "body",
    selectors=("purpose", "hide_auto"),
    render=self.render_body,
)
```

Then use its value in the section query:

```python
if self.hide_auto.value:
    chart_data = chart_data.map(
        lambda frame: frame.filter(
            ~pl.col("trip_mode").is_in(["DRIVEALONE", "SHARED2", "SHARED3"])
        )
    )
```

Registration connects the widget to refresh and HTML export. A widget created
directly in the layout is not part of this lifecycle. Register it with
`self.select()` or `self.selector()`.

## Add A Figure With The Existing Plotter

Pages must usually use `self.plot`:

```python
chart = self.plot.bar(
    chart_data,
    x="trip_mode",
    y="trip_count",
    title="Trips By Mode",
    x_title="Trip Mode",
    y_title="Trips",
    category_order=mode_labels,
)
```

This method applies run colors, count or share state, layout rules, and hover
behavior. The shared types are `bar`, `line`, `density`, and `scatter`.

If one page requires a Plotly customization, build the figure through the
figure API. Change it and put it in a Panel pane:

```python
figure = self.plot.figure.bar(
    chart_data,
    x="trip_mode",
    y="trip_count",
    title="Trips By Mode",
)
figure.update_layout(legend_title_text="Model Run")
return self.plot.panel(figure)
```

Set standard titles, axes, modes, category order, and size with shared
arguments. Do not make these changes separately on each page.

## Add A Reusable Figure Type

When several pages require a new chart contract, add it to the shared renderer.
Do not copy the Plotly construction.

For an area chart:

1. add `area_figure(context, data, *, x, y, ...)` to
   `dashboard/rendering/figures.py`;
2. add `FigureBuilder.area()` and `Plotter.area()` in
   `dashboard/rendering/plotter.py`;
3. use `RenderContext` for colors and value mode;
4. validate required columns with the same clear errors as other builders; and
5. test the Plotly figure before testing Panel wrapping.

This is a complete small builder for `dashboard/rendering/figures.py`. It uses
the existing internal helpers with the other builders:

```python
def area_figure(
    context: RenderContext,
    data: ChartTables,
    *,
    x: str,
    y: str,
    title: str = "",
    x_title: str = "",
    y_title: str = "Count",
    value_mode: ChartValueMode = "dashboard",
    height: int = 350,
) -> go.Figure:
    _require_columns(data, "area", x, y)
    share = _share_mode(context, value_mode)
    figure = go.Figure()

    for index, (label, frame) in enumerate(data):
        values = np.asarray(frame[y].to_list(), dtype=float)
        if share and values.sum() > 0:
            values = values / values.sum() * 100.0
        figure.add_trace(
            go.Scatter(
                name=str(label),
                x=frame[x].to_list(),
                y=values.tolist(),
                mode="lines",
                fill="tozeroy",
                line=dict(
                    color=context.color(str(label), index),
                    width=2,
                ),
            )
        )

    _layout(
        figure,
        title=title,
        x_title=x_title,
        y_title=_y_title(y_title, share),
        height=height,
    )
    return figure
```

That module already uses `ChartTables`, `ChartValueMode`, `go`, and `np`. The
explicit `value_mode` keeps `"dashboard"`, count, and share behavior consistent
with existing figure types. `_require_columns` gives an error for the applicable
run. `RenderContext.color()` keeps the configured run-color mapping.

The adapter shape is:

```python
class FigureBuilder:
    def area(self, data, **kwargs):
        return figures.area_figure(self.context, data, **kwargs)


class Plotter:
    def area(self, data, **kwargs) -> pn.pane.Plotly:
        return self.panel(self.figure.area(data, **kwargs))
```

A focused test must examine traces and layout:

```python
def test_area_figure_uses_run_labels_and_colors():
    data = [("Base", pl.DataFrame({"period": [1, 2], "trips": [3.0, 5.0]}))]

    figure = Plotter(RenderContext()).figure.area(
        data, x="period", y="trips"
    )

    assert figure.data[0].name == "Base"
    assert list(figure.data[0].x) == [1, 2]
    assert figure.data[0].fill == "tozeroy"
    assert figure.data[0].line.color == RenderContext().color("Base", 0)


def test_area_figure_honors_dashboard_share_mode():
    data = [("Base", pl.DataFrame({"period": [1, 2], "trips": [1.0, 3.0]}))]

    figure = Plotter(RenderContext(value_mode="share")).figure.area(
        data,
        x="period",
        y="trips",
        y_title="Trips",
    )

    assert list(figure.data[0].y) == [25.0, 75.0]
    assert figure.layout.yaxis.title.text == "Percent of Trips (%)"
```

## Add A Table

Tables use `data_table()` rather than the figure plotter:

```python
from dashboard.rendering import data_table


return data_table(
    chart_data,
    title="Trip Mode Totals",
    height=280,
    numeric_precision_by_column={"trip_count": 0},
)
```

It creates one run tab for each frame. It applies shared column titles and
numeric formatting. Use a page-local `Tabulator` only when the shared table
contract cannot supply the required interaction.

## Add A New Page Group

Create a public package and one public module per child page:

```text
dashboard/pages/emissions/
  __init__.py
  regional_emissions.py
  household_emissions.py
```

In `__init__.py`:

```python
from dashboard.page_definitions import DashboardGroupDefinition


GROUP = DashboardGroupDefinition(
    group_id="emissions",
    title="Emissions",
    order=85,
    default_page_id="regional_emissions",
    default_enabled=False,
)
```

Each child page declares `group_id="emissions"`. `default_page_id` must specify
one of these children. Start private helper package and module names with `_`.
Discovery ignores these names.

Users can enable the default group pages or select child pages:

```yaml
dashboard:
  live:
    pages:
      - emissions
      # Or:
      # - emissions:
      #     - regional_emissions
```

## Test The Extension

Test pure transforms separately from lifecycle connections. Then add focused
checks for declarations:

```python
def test_trip_mode_page_declares_its_runtime_contract():
    definition = TripModeTotalsPage.definition

    assert definition.page_id == "trip_mode_totals"
    assert definition.group_id == "trip_summaries"
    assert definition.required_summary_ids == ("trips_by_mode",)
```

For selector behavior, create a small test page with `DashboardState`. Change
the option provider domain and refresh the page. Verify that the framework
repairs invalid values. For figures, test `Plotter(RenderContext()).figure`.
This keeps failures independent of Panel. The full registry tests verify
discovery, unique IDs, requirements, and export protocol support.

Use at least these commands:

```bash
uv run python scripts/generate_wiki_catalogs.py
uv run --with pytest pytest --basetemp .pytest_tmp tests/test_page_authoring.py tests/test_page_registry_contract.py
uv run --with pytest pytest --basetemp .pytest_tmp tests/test_figure_builders.py tests/test_export_payload.py
```

## Review Checklist

- One public leaf module contains one decorated page class.
- Page and group IDs are stable, unique, and config-friendly.
- Required and optional data match the visible workflows.
- Summary reads declare the columns they consume.
- Selectors own options; sections list every selector dependency.
- Register custom widgets. Do not insert them directly.
- Pure transforms do not depend on Panel state.
- Use existing shared figures and tables before you add renderers.
- Missing data produces a standard diagnostic card.
- Live and export behavior use the same declarations.
- Catalogs and focused tests are current.

## Related Chapters

- [31 - Dashboard Pages](31-dashboard-pages.md)
- [32 - Figures And Widgets](32-figures-and-widgets.md)
- [33 - Dashboard Page Recipes](33-dashboard-page-recipes.md)
- [34 - HTML Export](34-html-export.md)
- [44 - Summary Function Cookbook](44-summary-function-cookbook.md)
