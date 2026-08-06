# 40 - Developer Workflows

Use this chapter to find the right workflow when changing code or documentation.

## Codebase Map

```text
activitysim_visualizer/
|-- run.py
|-- runtime/
|   |-- config/
|   `-- workflows/
|-- processor/
|   |-- prepare/
|   |-- skimjoin/
|   |-- summarize/
|   `-- models.py
|-- dashboard/
|   |-- app.py
|   |-- export/
|   |-- helpers/
|   |-- rendering/
|   |-- pages/
|   |-- page_base.py
|   |-- page_declarations.py
|   |-- page_definitions.py
|   |-- page_features.py
|   |-- page_lifecycle.py
|   |-- page_registry.py
|   `-- state.py
|-- scripts/
|-- tests/
`-- wiki/
```

## Common Change Paths

| Change | Start with |
|---|---|
| New raw-output normalization | [21 - Prepared Tables](21-prepared-tables.md) |
| New prepared column | [21 - Prepared Tables](21-prepared-tables.md#adding-a-prepared-column) |
| New skim-derived output | [22 - Skimjoin](22-skimjoin.md#adding-a-skim-output) |
| New generated summary function/table | [44 - Summary Function Cookbook](44-summary-function-cookbook.md) |
| New figure or table on existing page | [32 - Figures and Widgets](32-figures-and-widgets.md) |
| New dashboard page | [33 - Dashboard Page Recipes](33-dashboard-page-recipes.md) |
| New export node/runtime behavior | [34 - HTML Export](34-html-export.md#changing-export-runtime-behavior) |
| Plotting API or count/share behavior | [35 - Plotting Reference](35-plotting-reference.md) |
| New externally produced summary table/file | [41 - Data Extension Cookbook](41-data-extension-cookbook.md#worked-example-add-an-outside-summary-table) |
| New prepared column or table | [41 - Data Extension Cookbook](41-data-extension-cookbook.md) |
| New config key or source-column alias | [42 - Config, Columns, and Labels](42-config-column-label-cookbook.md) |
| New dashboard label mapping | [42 - Config, Columns, and Labels](42-config-column-label-cookbook.md#worked-example-add-a-label-mapping-and-use-it-on-a-page) |
| New weighting mode or host | [43 - Weighting and Hosting Extensions](43-weighting-hosting-extensions.md) |
| New page, page group, widget, table, or figure | [45 - Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md) |

## Testing Guidance

Run focused tests for the subsystem you changed:

- prepare changes: minimal raw/prepared input tests and cache identity tests
- skimjoin changes: config normalization, lookup behavior, reports
- summary changes: builder output schema, weighted behavior, missing inputs
- page changes: page registry requirements and page render smoke tests
- export changes: serializer, payload contract, and export HTML smoke tests

Common command:

```bash
uv run --with pytest pytest --basetemp .pytest_tmp
```

During development, use the smallest relevant test group. The
[Testing](46-testing.md) chapter describes the fast and full markers and gives
the required release test commands.

## Generated Wiki Catalogs

Regenerate the catalogs after you change:

- `@summary(...)` declarations and contracts
- `processor/summarize/catalog.py`
- dashboard page definitions
- page data requirements

Command:

```bash
uv run python scripts/generate_wiki_catalogs.py
```

Comments identify generated sections. Do not edit the text between those
markers by hand.

## Documentation Maintenance

When behavior changes, update the documentation in the same change:

| Change | Wiki updates |
|---|---|
| Config behavior | `11-configuring-your-data.md` and `13-configuration-reference.md` |
| Prepare behavior | `21-prepared-tables.md` |
| Skimjoin behavior | `22-skimjoin.md` |
| Summary contract or registration | `23-summary-functions.md`, then regenerate catalogs |
| Dashboard page API | `31-dashboard-pages.md`, `32-figures-and-widgets.md`, `33-dashboard-page-recipes.md` |
| Export payload/runtime | `34-html-export.md` |
| Export payload schema | `36-html-export-schema.md` |
| User-visible failure mode | `90-troubleshooting.md` |
| Cross-cutting extension recipe | `41-data-extension-cookbook.md` through `45-dashboard-extension-cookbook.md` |

## Review Checklist

- The change follows the owning subsystem's existing patterns.
- Config and cache behavior are explicit.
- Missing optional input gives a controlled result.
- Declare summary and page requirements where the runtime can use them.
- Tests cover the behavior rather than only the implementation detail.
- Generated wiki catalogs are current.
- The fast suite passes, and the `full_export` boundary passes when the change
  affects pages, plotting, summaries, or export.
