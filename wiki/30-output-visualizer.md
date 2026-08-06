# 30 - Output Visualizer

The Output Visualizer turns processor output into either a live Panel dashboard
or a standalone HTML file.

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

The visualizer does not rebuild summaries. If one is missing, run the processor
workflow first.

## Use The Live Dashboard

After the server starts, open the URL printed in the terminal. The default is
`http://localhost:5006`. The left rail identifies the loaded runs and provides
the dashboard-wide controls; the main area contains standalone page tabs and
group tabs such as Tour Summaries and Validation Summaries.

| Control | Effect |
|---|---|
| Runs Loaded | Shows the color and label used for each run. It is a legend, not a run filter. |
| Weighting | Selects one stored weighting mode. The control is disabled when only one mode is available. |
| Values: Percent | Shared distribution charts divide each run's values by the relevant plotted total. This supports shape comparison across runs of different sizes. |
| Values: Count | Shared distribution charts use stored weighted or unweighted values. |
| Page selectors | Filter or change only the registered sections that depend on them. Options come from usable data and can differ by configuration. |
| Calculation notes | Expand below supported output to show source summaries, filters, formulas, and aggregation details. |

Some outputs deliberately ignore the Percent/Count switch. Examples include
rates, averages, validation statistics, tables, and charts whose builder sets a
fixed value mode. Read the axis label and calculation note; do not assume every
number on a Percent dashboard is a share.

Configured segmented summaries appear as separate series such as
`Base (North)`. `segment.dashboard.visibility` determines whether the full run,
segments, or both are included, and `segmentation_type` selects the displayed
definition. These are configuration choices, not live sidebar controls.

## Read Comparisons Correctly

Use the following order when interpreting a chart:

1. Confirm the weighting and Values controls.
2. Read the chart title, axis units, and active page selectors.
3. Identify each run or segment by its rail color and full hover label.
4. Check whether the output is a count, share, rate, average, residual, or
   modeled-versus-observed comparison.
5. Expand the calculation note when available.

Percent mode normally normalizes each run independently, so it compares
distributions rather than regional totals. Count mode can compare totals only
when runs use compatible sample expansion, model coverage, and source units.
Distance labels in existing pages assume miles; skim component units remain
the units in their source matrices or sidecars.

The first configured run is the base for outputs that calculate a difference
or percent difference. Reordering `runs` can therefore change the comparison
reference as well as duplicate-label run-key suffixes.

## Missing And Partial Data

A page can use some runs while excluding others. A standard unavailable card
identifies missing files, unavailable summaries, failed calculations, or
schema mismatches. A partial result means at least one run was usable and at
least one was excluded; the chart still renders the usable runs. Hover labels
and the Runs Loaded legend do not prove that every run contributed to every
visualization.

Set `display.missing_data_display: blank` only when you intentionally want to
hide diagnostic cards. During setup and extension work, keep the default
`card` behavior.

For a page-by-page description, use
[16 - Dashboard User Guide](16-dashboard-user-guide.md).

## Live Dashboard

[`dashboard/app.py`](../dashboard/app.py) assembles the live dashboard. It
creates:

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

Then use the standard configuration command:

```bash
uv run activitysim-viz --config local_config.yaml
```

## HTML Export

HTML export uses the same page registry and converts supported content into one
self-contained document. It includes only the states and selector variants
available at export time.

Configure `pipeline.dashboard_mode: export` and an output path:

```yaml
pipeline:
  steps: [summarize, dashboard]
  dashboard_mode: export

dashboard:
  export:
    output_path: exports/dashboard.html
```

The standard configuration command then writes the export. For details, see
[34 - HTML Export](34-html-export.md).

## Dashboard State

`DashboardState` contains the global state that pages use:

- loaded run labels
- selected weighting mode
- selected value mode, usually percent or count
- optional segmentation type and visibility
- prepared-data provider state

Pages read state through the `DashboardPage` helpers, which avoids duplicating
cache and run-selection logic.

## Extension Path

The [Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md) gives
complete examples for pages, page groups, selectors, widgets, tables, and
figures.

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

- [16 - Dashboard User Guide](16-dashboard-user-guide.md)
- [31 - Dashboard Page Contract](31-dashboard-pages.md)
- [32 - Figures and Widgets](32-figures-and-widgets.md)
- [33 - Dashboard Page Recipes](33-dashboard-page-recipes.md)
- [34 - HTML Export](34-html-export.md)
- [45 - Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md)
