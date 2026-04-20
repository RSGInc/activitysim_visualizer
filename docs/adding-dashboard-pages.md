# Adding Dashboard Pages and Shared Components

This guide is for the common case where the summary table you need already exists and the remaining work is dashboard wiring.

There are two related jobs:

1. Add a new page under `dashboard/pages/`.
2. Add a new reusable chart helper in `dashboard/components.py` when multiple pages need the same plotting behavior.

If the summary table does not exist yet, start with [adding-summaries.md](adding-summaries.md).

## Mental Model

Each dashboard page follows the same flow:

1. Pull one or more summary tables from `DashboardState`.
2. Optionally filter or reshape them into chart-ready data.
3. Build Panel objects from that data.
4. Replace the contents of stable containers inside `_refresh()`.

Each reusable chart helper follows this flow:

1. Accept already-prepared data.
2. Build a Plotly figure.
3. Apply consistent layout and run colors.
4. Return a `pn.pane.Plotly`.

Pages own business logic and selector behavior. Shared components own presentation and repeated chart behavior.

## Part 1: Adding a New Dashboard Page

### What a Page Module Must Contain

A page module in `dashboard/pages/` usually contains:

- small helper functions for option lists or chart data prep
- one `DashboardPage` subclass
- one module-level `PAGE = DashboardPageDefinition(...)`
- one final line assigning `YourPageClass.definition = PAGE`

The registry imports every module under `dashboard/pages/`, looks for `PAGE`, validates it, and instantiates the controller class from the definition.

### The Smallest Useful Page

```python
from __future__ import annotations

import panel as pn

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from runtime.config import Config


class MyNewPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("My New Page", state, config)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## My New Page"),
            self._body,
            sizing_mode="stretch_width",
        )

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        summaries = self.require_summaries(*self.required_summary_ids)
        if summaries is None:
            self._body.objects = [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=list(self.required_summary_ids),
                )
            ]
            return

        chart_data = summaries["my_summary_table"]
        self._body.objects = [
            bar_chart(
                chart_data,
                x_col="category",
                y_col="freq",
                title="My Chart",
                xaxis_title="Category",
                yaxis_title="Count",
                as_percent=self.as_percent,
            )
        ]


PAGE = DashboardPageDefinition(
    page_id="my_new_page",
    title="My New Page",
    order=120,
    controller_cls=MyNewPage,
    required_summary_ids=("my_summary_table",),
)

MyNewPage.definition = PAGE
```

### Step-by-Step Page Checklist

#### 1. Create a file in `dashboard/pages/`

Name it after the stable page id you want, for example `dashboard/pages/my_new_page.py`.

The filename does not register the page directly, but keeping the filename, page id, and class name aligned makes the codebase easier to navigate.

#### 2. Subclass `DashboardPage`

Useful base-class features:

- `self.state`
- `self.config`
- `self.as_percent`
- `self.weighting_key`
- `require_summary(...)` and `require_summaries(...)`
- `get_filtered_view(...)`
- `_watch_widget(...)`
- `data_not_available_card(...)`

#### 3. Create stable containers in `__init__`

Create widgets and containers once in `__init__`, then replace only `.objects` in `_refresh()`.

That keeps widget instances stable while the user changes tabs, weighting mode, or percent/count mode.

Good examples in the repo:

- `dashboard/pages/overview.py`
- `dashboard/pages/destination.py`
- `dashboard/pages/joint_tours.py`

#### 4. Fetch summaries in `_refresh()`

For summary-backed pages, start with:

```python
summaries = self.require_summaries(*self.required_summary_ids)
if summaries is None:
    ...
```

Why this is preferred:

- missing-data behavior stays consistent
- warnings are logged once per missing summary
- the dependency contract stays visible in `PAGE.required_summary_ids`

#### 5. Transform summary tables into chart-ready data

Most pages do not pass raw summary tables straight into chart helpers. They first reshape them into the exact form the chart wants.

Common patterns:

- filter by selector value
- rename one of several measure columns to a common plotting column
- sort categories into a deliberate order
- fill missing categories with zero

If the transformation is expensive or depends on selector values, cache it with `get_filtered_view(...)`.

#### 6. Build the visible layout from Panel objects

The export path already handles these view types well:

- `pn.Column`
- `pn.Row`
- `pn.Card`
- `pn.Tabs`
- `pn.pane.Markdown`
- `pn.pane.HTML`
- `pn.widgets.Select`
- `pn.widgets.RadioButtonGroup`
- `pn.widgets.Tabulator`
- `pn.pane.Plotly`

The clean pattern is:

1. prepare data
2. build charts/tables
3. assign `self._body.objects = [...]` last

#### 7. Add selectors only when the page genuinely needs them

If the page needs a local selector such as Purpose or Person Type:

- create it in `__init__`
- call `self._watch_widget(widget)`
- recompute available options in `_refresh()`
- reset invalid current values to a safe default

#### 8. Declare the page with `DashboardPageDefinition`

Important fields:

- `page_id`: stable config-facing identifier
- `title`: visible tab title
- `order`: default sort order
- `controller_cls`: the page controller class
- `required_summary_ids`: every summary the page needs
- `selectors`: optional `PageSelectorDefinition(...)` entries
- `raw_data_mode`: usually `"none"` for summary-backed pages

#### 9. Add the page to config if you want it enabled

The module is auto-discoverable once it exists, but it only appears live if it is enabled by config or included in the default-enabled set.

Example:

```yaml
visualizer:
  dashboard_pages:
    - overview
    - my_new_page
    - trip_mode
```

## Selector Support in HTML Export

If a page-local selector should work in exported HTML, declare it in `PAGE.selectors`.

Example:

```python
from dashboard.page_definitions import PageSelectorDefinition

PAGE = DashboardPageDefinition(
    ...,
    selectors=(
        PageSelectorDefinition(
            selector_id="purpose",
            widget_attr="purp_sel",
            label="Purpose",
        ),
    ),
)
```

Important details:

- `selector_id` is the stable config-facing name used under `visualizer.export_html.pages.<page_id>.<selector_id>`.
- `widget_attr` must match the attribute name on the page instance.
- Export only supports the widget types that `dashboard/export_html.py` knows how to serialize.

If you add a widget but do not declare it in `PAGE.selectors`, the live dashboard can still work, but the HTML export will treat it as a static control.

## Part 2: Adding a New Shared Chart Helper

Create a helper in `dashboard/components.py` when:

- multiple pages need the same chart behavior
- the chart needs shared layout, color, hover, or normalization logic
- you want one place to maintain a plotting style

Do not create a shared helper just because two pages both use Plotly. If the only repeated logic is page-specific data prep, keep that logic in the page module.

### What a Shared Helper Should Accept

Follow the pattern used by `bar_chart`, `line_chart`, and `density_chart`:

- input is already chart-ready
- input is passed as `list[tuple[str, pl.DataFrame]]`
- output is `pn.pane.Plotly`

That format matches the rest of the dashboard, which almost always compares multiple runs side by side.

### Example Skeleton

```python
def scatter_chart(
    data_list: list[tuple[str, pl.DataFrame]],
    x_col: str,
    y_col: str,
    title: str = "",
    xaxis_title: str = "",
    yaxis_title: str = "",
    height: int = 350,
) -> pn.pane.Plotly:
    fig = go.Figure()
    for i, (label, df) in enumerate(data_list):
        if df is None or len(df) == 0:
            continue
        fig.add_trace(
            go.Scatter(
                name=label,
                x=df[x_col].to_list(),
                y=df[y_col].to_list(),
                mode="markers",
                marker=dict(color=run_color(i), size=8),
            )
        )
    _layout(fig, title, xaxis_title, yaxis_title, height)
    return pn.pane.Plotly(fig, sizing_mode="stretch_width")
```

### Percent Mode

If the chart has a meaningful percent interpretation:

- add `as_percent: bool | None = None`
- call `_percent_mode(as_percent)`
- normalize y-values before plotting
- update the y-axis title accordingly

If the chart does not have a meaningful percent interpretation, leave percent support out.

### Export-Safe Rules

If you want the chart to export cleanly:

- return `pn.pane.Plotly`
- keep trace shapes stable for the same chart when selector values change, when practical
- avoid custom widgets or custom client-side JavaScript

## Common Mistakes

- forgetting to include the summary id in `required_summary_ids`
- creating widgets inside `_refresh()` instead of in `__init__`
- forgetting to call `_watch_widget(...)`
- passing raw summary tables into a chart helper when reshaping is still needed
- returning a Panel object type that `dashboard/export_html.py` does not serialize
- writing page-specific logic into `dashboard/components.py`

## How to Sanity-Check Your Work

After adding a page or shared component, check:

- the page appears under the expected tab title
- weighted/unweighted still works
- percent/count still works where it should
- selector changes refresh the page cleanly
- missing summaries show a friendly fallback
- `--export-html` still works if the page is part of export

## Good Files to Copy From

- `dashboard/pages/overview.py` for a simple summary-backed page
- `dashboard/pages/destination.py` for a selector plus one chart and one table
- `dashboard/pages/stop_timing.py` for selector-driven cached transformed views
- `dashboard/pages/joint_tours.py` for custom category ordering across multiple sections
- `dashboard/components.py` for the expected style of reusable chart helpers
