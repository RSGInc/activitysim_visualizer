# 30 - Output Visualizer

The Output Visualizer reads processor outputs and presents them as either a
live Panel dashboard or a standalone HTML export.

```text
summary caches + optional prepared tables
  -> dashboard state
  -> registered pages
  -> live Panel app or serialized HTML export
```

The main code lives under [`dashboard/`](../dashboard).

## Visualizer Responsibilities

The visualizer is responsible for:

- loading summary runs
- loading prepared tables only for pages that request them
- applying global dashboard state such as weighting mode and value mode
- resolving enabled page groups
- rendering figures, tables, cards, and widgets
- exporting supported page states to standalone HTML

It should not rebuild summaries. If a summary is missing, run the processor
workflow first.

## Live Dashboard

The live dashboard is assembled in
[`dashboard/app.py`](../dashboard/app.py). It creates:

- run colors and run legend
- `DashboardState`
- global weighting and value controls
- registered page instances
- grouped navigation tabs

Configure live mode:

```yaml
pipeline:
  steps: [summarize, dashboard]
  dashboard_mode: live
```

Then run the normal config command:

```bash
uv run activitysim-viz --config local_config.yaml
```

## HTML Export

HTML export uses the same page registry, but serializes supported page content
into one self-contained HTML document. Export only includes states and selector
variants generated at export time.

Configure `pipeline.dashboard_mode: export` and an output path:

```yaml
pipeline:
  steps: [summarize, dashboard]
  dashboard_mode: export

dashboard:
  export:
    output_path: exports/dashboard.html
```

The same normal config command then writes the export. For details, read
[34 - HTML Export](34-html-export.md).

## Dashboard State

`DashboardState` centralizes the global state pages react to:

- loaded run labels
- selected weighting mode
- selected value mode, usually percent or count
- optional segmentation type and visibility
- prepared-data provider state

Pages should read state through the `DashboardPage` helpers instead of
duplicating cache or run-selection logic.

## Extension Path

The [Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md) shows
complete page, page-group, selector, widget, table, and figure examples.

When adding visual output:

1. Confirm the summary table or prepared table exists.
2. Decide whether the output belongs on an existing page or a new page.
3. Use shared helper modules before adding page-local utilities.
4. Register selectors and sections through the page API when the output is
   interactive.
5. Declare summary and prepared-table requirements in the page definition.
6. Add export support only through registered selectors and sections.
7. Regenerate wiki catalogs if page definitions changed.

## Related Chapters

- [31 - Dashboard Pages](31-dashboard-pages.md)
- [32 - Figures and Widgets](32-figures-and-widgets.md)
- [33 - Dashboard Page Recipes](33-dashboard-page-recipes.md)
- [34 - HTML Export](34-html-export.md)
- [45 - Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md)
