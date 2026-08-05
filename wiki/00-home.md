# ActivitySim Visualizer Wiki

This wiki contains the main documentation for ActivitySim Visualizer. Use it
for these tasks:

- run the visualizer with ActivitySim output
- extend the processor, summaries, skimjoin, or dashboard

The main data flow is:

```text
ActivitySim outputs
  -> Output Processor
  -> prepared tables and summary caches
  -> Output Visualizer
  -> live dashboard or standalone HTML export
```

For the subsystem boundaries and the complete repository map, see
[01 - Architecture](01-architecture.md).

## I Am Using The Visualizer

For standard use, read these three chapters:

1. [Get a dashboard running](10-getting-started.md).
2. [Choose raw, prepared, or summary inputs](11-configuring-your-data.md).
3. [Configure a live, export, or processor workflow](12-running-workflows.md).

Use [Troubleshooting](90-troubleshooting.md) when data is missing. Use the
[Configuration Reference](13-configuration-reference.md) to find a field or a
default value. You do not have to read the complete reference.

## I Am Extending The Visualizer

| Task | Read |
|---|---|
| Find every main config field and option | [13 - Configuration Reference](13-configuration-reference.md) |
| Understand the Output Processor | [20 - Output Processor](20-output-processor.md) |
| Add a prepared column | [41 - Data Extension Cookbook](41-data-extension-cookbook.md#worked-example-add-a-column-to-an-existing-prepared-table) |
| Add or debug skimjoin outputs | [22 - Skimjoin](22-skimjoin.md) |
| Find every skimjoin config field and lookup option | [25 - Skimjoin Config Reference](25-skimjoin-config-reference.md) |
| Add a summary function | [44 - Summary Function Cookbook](44-summary-function-cookbook.md) |
| Find every registered summary table | [24 - Summary Catalog](24-summary-catalog.md) |
| Understand the Output Visualizer | [30 - Output Visualizer](30-output-visualizer.md) |
| Add a dashboard page or page group | [45 - Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md) |
| Add a figure, table, selector, or widget | [45 - Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md) |
| Add an outside summary, prepared column, or prepared table | [41 - Data Extension Cookbook](41-data-extension-cookbook.md) |
| Add a config item, column alias, or label mapping | [42 - Config, Columns, and Labels](42-config-column-label-cookbook.md) |
| Add a weighting mode or hosting adapter | [43 - Weighting and Hosting Extensions](43-weighting-hosting-extensions.md) |
| Debug an empty page, bad cache, or export mismatch | [90 - Troubleshooting](90-troubleshooting.md) |

## Chapters

### User Guides

- [01 - Architecture](01-architecture.md)
- [10 - Getting Started](10-getting-started.md)
- [11 - Configuring Your Data](11-configuring-your-data.md)
- [12 - Running Workflows](12-running-workflows.md)
- [13 - Configuration Reference](13-configuration-reference.md)

### Output Processor

- [20 - Output Processor](20-output-processor.md)
- [21 - Prepared Tables](21-prepared-tables.md)
- [22 - Skimjoin](22-skimjoin.md)
- [23 - Summary Functions](23-summary-functions.md)
- [24 - Summary Catalog](24-summary-catalog.md)
- [25 - Skimjoin Config Reference](25-skimjoin-config-reference.md)

### Output Visualizer

- [30 - Output Visualizer](30-output-visualizer.md)
- [31 - Dashboard Pages](31-dashboard-pages.md)
- [32 - Figures and Widgets](32-figures-and-widgets.md)
- [33 - Dashboard Page Recipes](33-dashboard-page-recipes.md)
- [34 - HTML Export](34-html-export.md)

### Developer Reference

- [40 - Developer Workflows](40-developer-workflows.md)
- [41 - Data Extension Cookbook](41-data-extension-cookbook.md)
- [42 - Config, Columns, and Labels](42-config-column-label-cookbook.md)
- [43 - Weighting and Hosting Extensions](43-weighting-hosting-extensions.md)
- [44 - Summary Function Cookbook](44-summary-function-cookbook.md)
- [45 - Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md)
- [46 - Testing](46-testing.md)
- [90 - Troubleshooting](90-troubleshooting.md)
- [99 - Glossary](99-glossary.md)

## Generated Pages

The project generates some wiki sections from code. This process keeps the
reference material consistent with the code:

- [24 - Summary Catalog](24-summary-catalog.md)
- the generated page catalog in [31 - Dashboard Pages](31-dashboard-pages.md)

Regenerate these sections after you change a summary declaration, a summary
contract, a dashboard page definition, or a page data requirement:

```bash
uv run python scripts/generate_wiki_catalogs.py
```
