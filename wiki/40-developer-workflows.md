# 40 - Developer Workflows

This chapter is for contributors changing code or documentation.

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
|   |-- pages/
|   |-- page_base.py
|   |-- page_definitions.py
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
| New summary table | [23 - Summary Functions](23-summary-functions.md#adding-a-summary-function) |
| New figure or table on existing page | [32 - Figures and Widgets](32-figures-and-widgets.md) |
| New dashboard page | [33 - Dashboard Page Recipes](33-dashboard-page-recipes.md) |
| New export node/runtime behavior | [34 - HTML Export](34-html-export.md#changing-export-runtime-behavior) |

## Testing Guidance

Use focused tests for the subsystem you changed:

- prepare changes: minimal raw/prepared input tests and cache identity tests
- skimjoin changes: config normalization, lookup behavior, reports
- summary changes: builder output schema, weighted behavior, missing inputs
- page changes: page registry requirements and page render smoke tests
- export changes: serializer, payload contract, and export HTML smoke tests

Common command:

```bash
uv run --with pytest pytest --basetemp .pytest_tmp
```

Run narrower tests while iterating when possible.

## Generated Wiki Catalogs

Regenerate catalogs after changing:

- `processor/summarize/summary_specs.py`
- summary contracts
- dashboard page definitions
- page data requirements

Command:

```bash
python scripts/generate_wiki_catalogs.py
```

Generated sections are marked with comments. Do not edit inside generated
markers by hand.

## Documentation Maintenance

When behavior changes, update docs in the same change:

| Change | Wiki updates |
|---|---|
| Config behavior | `11-configuring-your-data.md` and `12-running-workflows.md` |
| Prepare behavior | `21-prepared-tables.md` |
| Skimjoin behavior | `22-skimjoin.md` |
| Summary contract or registration | `23-summary-functions.md`, then regenerate catalogs |
| Dashboard page API | `31-dashboard-pages.md`, `32-figures-and-widgets.md`, `33-dashboard-page-recipes.md` |
| Export payload/runtime | `34-html-export.md` |
| User-visible failure mode | `90-troubleshooting.md` |

## Review Checklist

- The change follows the owning subsystem's existing patterns.
- Config and cache behavior are explicit.
- Missing optional inputs fail gracefully.
- Summary/page requirements are declared where the runtime can see them.
- Tests cover the behavior rather than only the implementation detail.
- Generated wiki catalogs are current.

