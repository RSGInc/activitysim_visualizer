# ActivitySim Visualizer Wiki

This wiki is the main documentation home for the ActivitySim Visualizer. It is
written for two audiences:

- users who need to run the visualizer on ActivitySim outputs
- developers who need to extend the processor, summaries, skimjoin, or dashboard

The short mental model:

```text
ActivitySim outputs
  -> Output Processor
  -> prepared tables and summary caches
  -> Output Visualizer
  -> live dashboard or standalone HTML export
```

## Start Here

| If you want to... | Read |
|---|---|
| Run the visualizer for the first time | [10 - Getting Started](10-getting-started.md) |
| Point the tool at your own raw outputs | [11 - Configuring Your Data](11-configuring-your-data.md) |
| Find every main config field and option | [13 - Configuration Reference](13-configuration-reference.md) |
| Use already prepared tables | [11 - Configuring Your Data](11-configuring-your-data.md#using-pre-prepared-tables) |
| Understand prepare, summarize, dashboard, and caches | [12 - Running Workflows](12-running-workflows.md) |
| Understand the Output Processor | [20 - Output Processor](20-output-processor.md) |
| Add a prepared column | [21 - Prepared Tables](21-prepared-tables.md#adding-a-prepared-column) |
| Add or debug skimjoin outputs | [22 - Skimjoin](22-skimjoin.md) |
| Find every skimjoin config field and lookup option | [25 - Skimjoin Config Reference](25-skimjoin-config-reference.md) |
| Add a summary function | [23 - Summary Functions](23-summary-functions.md#adding-a-summary-function) |
| Find every registered summary table | [24 - Summary Catalog](24-summary-catalog.md) |
| Understand the Output Visualizer | [30 - Output Visualizer](30-output-visualizer.md) |
| Add a dashboard page | [33 - Dashboard Page Recipes](33-dashboard-page-recipes.md) |
| Add a figure or widget | [32 - Figures and Widgets](32-figures-and-widgets.md) |
| Debug an empty page, bad cache, or export mismatch | [90 - Troubleshooting](90-troubleshooting.md) |

## Chapters

### User Guides

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
- [90 - Troubleshooting](90-troubleshooting.md)
- [99 - Glossary](99-glossary.md)

## Generated Pages

Some wiki sections are generated from code to keep reference material from
drifting:

- [24 - Summary Catalog](24-summary-catalog.md)
- the generated page catalog in [31 - Dashboard Pages](31-dashboard-pages.md)

Regenerate them after changing summary specs, summary contracts, dashboard page
definitions, or page data requirements:

```bash
python scripts/generate_wiki_catalogs.py
```

