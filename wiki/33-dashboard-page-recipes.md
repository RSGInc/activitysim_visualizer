# 33 - Dashboard Page Recipes

Use the smallest page shape that fits the behavior. Each discoverable page
module contains one class decorated with `@dashboard_page(...)`.

## Recipe 1: Simple Summary Page

```python
import panel as pn

from dashboard import DashboardPage, dashboard_page


@dashboard_page(
    page_id="my_summary",
    title="My Summary",
    order=120,
    required_summary_ids=("my_summary_table",),
)
class MySummaryPage(DashboardPage):
    def build_page(self):
        body = self.section("body", render=self.render_body)
        return pn.Column(pn.pane.Markdown("## My Summary"), body)

    def render_body(self):
        data = self.data.summary("my_summary_table")
        if not data:
            return self.summary_only_unavailable_card()
        return self.plot.table(data)
```

Use `required_summary_ids` for the page's primary workflow and
`optional_summary_ids` for independent add-on features.

## Recipe 2: Dynamic Selector

Declare the option provider, selector, dependency, and render method:

```python
def build_page(self):
    self.purpose = self.select(
        "purpose", "Purpose", options=self.purpose_options
    )
    chart = self.section(
        "chart", selectors=("purpose",), render=self.render_chart
    )
    return pn.Column(selector_row(self.purpose), chart)
```

The framework refreshes options and dependent sections. Use
`self.selector(...)` only for a genuinely custom widget.

## Recipe 3: Multi-Workflow Page

Create one `PageFeature` per coherent user workflow:

```python
comparison = self.feature("comparison")
self.metric = comparison.select("metric", "Metric", options=["Count", "Share"])
comparison_body = comparison.section(
    "body", selectors=("metric",), render=self.render_comparison
)
```

When the Python controller itself becomes difficult to navigate, keep the
registered page as a small facade and split implementation mixins into a
private `_<page>/` package. Current examples include tour mode, mandatory
location choice, escorted tours, VMT, and traffic validation.

## Recipe 4: Prepared-Data Page

Declare prepared-data requirements in the decorator:

```python
@dashboard_page(
    page_id="raw_trip_demo",
    title="Raw Trip Demo",
    prepared_data_mode="required",
    required_prepared_tables=("trips",),
    default_enabled=False,
)
```

Load prepared data through `self.data`, handle an unavailable selection with a
standard card, and keep disaggregate use limited. Prefer summaries for repeated
aggregate views. `raw_trip_demo.py`, the skim pages, and parking location show
the current required/optional patterns.

## Adding A New Page Group

Create a package under `dashboard/pages/` and define `GROUP` in `__init__.py`:

```python
from dashboard.page_definitions import DashboardGroupDefinition

GROUP = DashboardGroupDefinition(
    group_id="my_group",
    title="My Group",
    order=90,
    default_page_id="my_first_page",
)
```

Every child decorator sets `group_id="my_group"`. Discovery rejects duplicate
IDs, missing definitions, unknown groups, and invalid summary or prepared-table
requirements.

## Page Review Checklist

- Decorator IDs are stable and config-friendly.
- Required and optional data declarations match rendered workflows.
- Selectors declare option providers and sections declare dependencies.
- Repeated transformations use `self.query(...)` without authored cache keys.
- Large pages use features and focused mixins only where they improve ownership.
- Missing data produces a standard, useful diagnostic card.
- Live and export behavior derive from the same component declarations.
- Focused page-authoring and figure tests pass.
- `python scripts/generate_wiki_catalogs.py` leaves catalogs current.

## Related Chapters

- [31 - Dashboard Pages](31-dashboard-pages.md)
- [32 - Figures and Widgets](32-figures-and-widgets.md)
- [34 - HTML Export](34-html-export.md)
