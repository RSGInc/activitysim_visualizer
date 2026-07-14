# Adding Dashboard Pages

Dashboard pages declare intent: which data they need, which choices a user can
make, and how each visible section is rendered. Widget synchronization, query
cache keys, diagnostics, and export metadata belong to the framework.

If the required summary does not exist, start with
[adding-summaries.md](adding-summaries.md).

## The page model

Every page module contains one `@dashboard_page` class. A normal page uses four
author-facing objects:

- `self.data` loads summary or prepared tables as `RunTables`;
- `self.select(...)` declares a dropdown, including dynamic options;
- `self.section(...)` declares an independently refreshed visible section; and
- `self.plot` turns chart-ready tables into figures or Panel panes.

The only required lifecycle method is `build_page()`. It declares selectors and
sections once and returns a stable Panel layout.

```python
import panel as pn
import polars as pl

from dashboard import DashboardPage, dashboard_page
from dashboard.rendering import selector_row


@dashboard_page(
    page_id="trips_by_purpose",
    title="Trips by Purpose",
    order=120,
    required_summary_ids=("trip_mode_by_tour_purpose_and_tour_mode",),
)
class TripsByPurposePage(DashboardPage):
    def build_page(self):
        self.purpose = self.select(
            "purpose",
            "Purpose",
            options=self.purpose_options,
            default="first",
        )
        chart = self.section(
            "mode_chart",
            selectors=("purpose",),
            render=self.render_mode_chart,
        )
        return pn.Column(
            pn.pane.Markdown("## Trips by Purpose"),
            selector_row(self.purpose),
            chart,
        )

    def trips(self):
        return self.data.summary(
            "trip_mode_by_tour_purpose_and_tour_mode",
            columns=("tour_purpose", "trip_mode", "trip_count"),
        )

    def purpose_options(self):
        data = self.trips()
        return data.values("tour_purpose") if data else ["All"]

    def render_mode_chart(self):
        data = self.trips()
        if not data:
            return self.summary_only_unavailable_card()
        chart_data = self.query(
            lambda: data.where(tour_purpose=self.purpose.value).group(
                "trip_mode", pl.col("trip_count").sum()
            )
        )
        return self.plot.bar(
            chart_data,
            x="trip_mode",
            y="trip_count",
            title="Trips by Mode",
            x_title="Mode",
            y_title="Trips",
        )
```

## Dynamic selectors

Pass an option provider instead of manually implementing `sync_controls()`:

```python
self.geography = self.select(
    "geography",
    "Geography",
    options=self.available_geographies,
    default="first",
)
```

The provider is called before dependent sections render. The framework updates
the widget and repairs a stale value. `default` may be:

- `"first"` (the default);
- `"last"`; or
- a callable receiving the current options and returning a value.

Use `self.selector(...)` only for a custom widget such as a checkbox or numeric
input. Manual `sync_controls()` is reserved for controls with behavior beyond an
option domain, such as a pair of linked numeric range controls.

## Querying and memoization

`RunTables` applies the same Polars operation to every run while retaining run
labels and availability issues. It supports `where`, `with_columns`, `group`,
`select`, `sort`, `join`, `map`, `requiring`, and `drop_empty`.

Pass `RunTables` directly to plots and tables. Avoid loops over
`(run_label, dataframe)` pairs unless the calculation genuinely differs by run.

Use `self.query(lambda: ...)` around a repeated or expensive chart-data
transformation. Do not invent a cache name or repeat filter tuples. Cache
identity is derived from:

- page and global dashboard state;
- the active section;
- the section's declared selector dependencies;
- the query callable and its captured scalar arguments.

This makes the typical section read as lookup, query, render.

## Large pages and features

When a page contains several user-visible workflows, compose it from page-local
features:

```python
comparison = self.feature("comparison")
self.metric = comparison.select(
    "metric", "Metric", options=["Count", "Share"]
)
comparison_view = comparison.section(
    "body",
    selectors=("metric",),
    render=self.render_comparison,
)
```

The feature namespaces its component ids (`comparison.metric` and
`comparison.body`) and delegates lifecycle, diagnostics, and exporting to the
parent page. It is composition, not another page type.

Use one feature for one coherent user workflow. Current examples include:

- escorted tours: school escort, adult escort, direction, and distance;
- VMT: comparison, personal auto, non-motorized, external, commercial, bicycle;
- traffic: observed/model fit, facility summaries, link tables, screenlines;
- mandatory location: geography comparison, flows, distance, remote work; and
- skim pages: summary and live-distribution features.

Domain queries can live on the feature or beside it. A separate
`_<page>_data.py` file is optional; use one only when it makes the feature easier
to understand.

## Missing data

An unavailable input is an empty `RunTables`, so test it with `if not data`.
Per-run details stay on `data.issues` and feed the standard unavailable cards.

Useful helpers are:

```python
self.no_runs_message()
self.summary_only_unavailable_card()
self.data_not_available_card(detail="...", missing_items=["summary_id"])
```

Pages should not inspect diagnostic storage, dashboard caches, or raw summary
tables on `DashboardState`.

## Page metadata

`@dashboard_page(...)` accepts:

- `page_id`, `title`, `order`, and optional `group_id`;
- `default_enabled`;
- `required_summary_ids` and `optional_summary_ids`; and
- `prepared_data_mode` and `required_prepared_tables`.

Use required summaries for the primary workflow and optional summaries for
independent add-on features. Grouped navigation is declared with
`DashboardGroupDefinition` in the page package's `__init__.py`.

## Contributor checklist

- Declare each selector and its options once.
- Declare selector dependencies on the section that uses them.
- Keep sections short: load, handle unavailable data, query, render.
- Use `self.query(...)`; never author cache keys.
- Split unrelated workflows into `PageFeature` objects.
- Keep export behavior derived from the same selector and section declarations.
- Add focused query/figure tests before an end-to-end export test.

Run page authoring and query contracts while iterating:

```bash
pytest tests/test_page_authoring.py
```

Add `tests/test_figure_builders.py` when changing plot construction. Reserve
`tests/test_export_html.py` for release-boundary verification.
