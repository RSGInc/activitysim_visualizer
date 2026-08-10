# ActivitySim Visualizer Wiki

This wiki is the main documentation for ActivitySim Visualizer. It covers two
common tasks:

- running the visualizer with ActivitySim output
- extending the processor, summaries, skimjoin, or dashboard

The main data flow is:

```text
ActivitySim outputs
  -> Output Processor
  -> prepared tables and summary caches
  -> Output Visualizer
  -> live dashboard or standalone HTML export
```

For subsystem boundaries and a complete repository map, see
[01 - Architecture](01-architecture.md).

## I Am Using The Visualizer

For a standard setup, read these three chapters in order:

1. [Get a dashboard running](10-getting-started.md).
2. [Choose raw, prepared, or summary inputs](11-configuring-your-data.md).
3. [Configure a live, export, or processor workflow](12-running-workflows.md).

After the dashboard starts, use the
[Dashboard User Guide](16-dashboard-user-guide.md) to choose an analysis and
interpret its controls and results.

To publish a standalone dashboard at no cost, see
[17 - Publish An Export With Posit Connect Cloud](17-posit-connect-cloud.md).

Use [14 - Input Data Contract](14-input-data-contract.md) when you need exact
table, key, relationship, or bypass-prepare rules. Use
[15 - Cache And Manifest Reference](15-cache-manifest-reference.md) when you
need to interpret stored identities and diagnostics.

If data is missing, see [Troubleshooting](90-troubleshooting.md). Use the
[Configuration Reference](13-configuration-reference.md) to look up a field or
default value; you do not need to read it from beginning to end.

## I Am Extending The Visualizer

| Task | Read |
|---|---|
| Find every main config field and option | [13 - Configuration Reference](13-configuration-reference.md) |
| Understand the Output Processor | [20 - Output Processor](20-output-processor.md) |
| Add a prepared column | [41 - Data Extension Cookbook](41-data-extension-cookbook.md#worked-example-add-a-column-to-an-existing-prepared-table) |
| Add or debug skimjoin outputs | [22 - Skimjoin](22-skimjoin.md) |
| Find every skimjoin config field and lookup option | [23 - Skimjoin Config Reference](23-skimjoin-config-reference.md) |
| Build summaries for configured subsets | [24 - Segmentation](24-segmentation.md) |
| Add custom zone-based geographies | [27 - Geography](27-geography.md) |
| Add a summary function | [44 - Summary Function Cookbook](44-summary-function-cookbook.md) |
| Find every registered summary table | [26 - Summary Catalog](26-summary-catalog.md) |
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
- [14 - Input Data Contract](14-input-data-contract.md)
- [15 - Cache And Manifest Reference](15-cache-manifest-reference.md)
- [16 - Dashboard User Guide](16-dashboard-user-guide.md)
- [17 - Publish An Export With Posit Connect Cloud](17-posit-connect-cloud.md)

### Output Processor

- [20 - Output Processor](20-output-processor.md)
- [21 - Prepared Tables](21-prepared-tables.md)
- [22 - Skimjoin](22-skimjoin.md)
- [23 - Skimjoin Config Reference](23-skimjoin-config-reference.md)
- [24 - Segmentation](24-segmentation.md)
- [25 - Summary Functions](25-summary-functions.md)
- [26 - Summary Catalog](26-summary-catalog.md)
- [27 - Geography](27-geography.md)

### Output Visualizer

- [30 - Output Visualizer](30-output-visualizer.md)
- [31 - Dashboard Page Contract](31-dashboard-pages.md)
- [32 - Figures and Widgets](32-figures-and-widgets.md)
- [33 - Dashboard Page Recipes](33-dashboard-page-recipes.md)
- [34 - HTML Export](34-html-export.md)
- [35 - Plotting Reference](35-plotting-reference.md)
- [36 - HTML Export Schema](36-html-export-schema.md)

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

The project generates some wiki sections directly from the code so that the
reference material stays accurate:

- [26 - Summary Catalog](26-summary-catalog.md)
- the generated page catalog in
  [31 - Dashboard Page Contract](31-dashboard-pages.md)

Regenerate these sections after you change a summary declaration, a summary
contract, a dashboard page definition, or a page data requirement:

```bash
uv run python scripts/generate_wiki_catalogs.py
```
