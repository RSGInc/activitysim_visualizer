# 33 - Dashboard Page Recipes

Use these recipes when adding or refactoring pages. Start with the simplest
recipe that fits the behavior.

## Recipe 1: Simple Summary Page

Use when the page displays one or more existing summaries with no page-local
widgets.

Checklist:

1. Create a module under `dashboard/pages/`.
2. Subclass `DashboardPage`.
3. Add a module-level `PAGE = DashboardPageDefinition(...)`.
4. Set `required_summary_ids`.
5. In `build_page()`, register sections or return a stable layout.
6. In render methods, use `require_summary(...)` or
   `resolve_summary_visualization(...)`.

Reference: `dashboard/pages/overview.py`.

## Recipe 2: One-Widget Summary Page

Use when a selector filters one chart or table.

Checklist:

1. Create the widget in `build_page()`.
2. Register it with `self.selector(...)`.
3. Register the affected view with `self.section(...)`.
4. Populate valid widget options in `sync_controls()`.
5. Render from the current widget value.

Reference: `dashboard/pages/trip_summaries/trip_mode.py`.

## Recipe 3: Multi-Section Page

Use when multiple charts share selectors or refresh independently.

Checklist:

1. Register each selector once.
2. Register each logical output section separately.
3. Keep each render method narrow.
4. Use shared helpers for repeated filtering.
5. Mark only affected sections stale when a live-only action requires it.

Reference: `dashboard/pages/long_term_choices/mandatory_location_choice.py`.

## Recipe 4: Prepared-Data Page

Use when a page needs disaggregate prepared rows rather than summary tables.

Checklist:

1. Set `prepared_data_mode` to `required` or `optional`.
2. Set `required_prepared_tables`.
3. Use `resolve_prepared_visualization(...)`.
4. Handle unavailable prepared data with an explicit message.
5. Keep prepared-data use limited; prefer summaries for repeated aggregate
   dashboard views.

Reference: `dashboard/pages/raw_trip_demo.py`.

## Recipe 5: Export-Aware Page

Use when a page-local widget should work in standalone HTML export.

Checklist:

1. Register exportable selectors with stable selector IDs.
2. Register sections with selector dependencies.
3. Avoid live-only callbacks for exported behavior.
4. Add export config examples if the page has expensive selector domains.
5. Test live rendering and HTML export rendering.

Reference: `dashboard/pages/skim_summaries/trip_skims.py`.

## Adding A New Page Group

Create a package under `dashboard/pages/` and add a `GROUP` definition in its
`__init__.py`:

```python
GROUP = DashboardGroupDefinition(
    group_id="my_group",
    title="My Group",
    order=90,
    default_page_id="my_first_page",
)
```

Every child page must set `group_id="my_group"`.

## Page Review Checklist

- Page ID is stable and config-friendly.
- Title is user-facing.
- Required summary IDs exist in the generated summary catalog.
- Prepared-data requirements are declared only when needed.
- Selectors and sections are registered for exportable interactions.
- Missing data produces a useful page message.
- Tests or smoke checks cover the page's expected data path.
- Run `python scripts/generate_wiki_catalogs.py`.

## Related Chapters

- [31 - Dashboard Pages](31-dashboard-pages.md)
- [32 - Figures and Widgets](32-figures-and-widgets.md)
- [34 - HTML Export](34-html-export.md)

