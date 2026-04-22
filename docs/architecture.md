# Architecture Overview

`activitysim_visualizer` has three main jobs:

1. Read and normalize raw ActivitySim outputs.
2. Build and cache summary tables.
3. Render those summaries in a live Panel dashboard or a standalone HTML export.

The codebase is organized around those jobs rather than around one monolithic app layer.

## Main Subsystems

| Area | Purpose | Key files |
|---|---|---|
| CLI and workflow orchestration | Parse step selections, choose cache-first vs rebuild flow, and hand off to prepare/summarize/dashboard workflows | `run.py`, `runtime_workflows.py` |
| Shared runtime contracts | Normalize YAML config and expose shared cross-cutting contracts used by both processor and dashboard | `runtime/config.py`, `runtime/models.py` |
| Processor prepare step | Read raw ActivitySim outputs, materialize canonical prepared columns, and manage prepared-table cache I/O | `processor/models.py`, `processor/prepare/*` |
| Summary generation and cache I/O | Register summary builders, compute weighted/unweighted tables, write/load cache manifests and CSVs | `processor/summarize/cache.py`, `processor/summarize/schema.py`, `processor/summarize/summaries/*.py` |
| Dashboard registry and state | Discover pages, validate page contracts, hold live state and cached filtered views | `dashboard/page_registry.py`, `dashboard/page_definitions.py`, `dashboard/state.py`, `dashboard/page_base.py` |
| Rendering | Build the live Panel app or serialize a client-side HTML document | `dashboard/app.py`, `dashboard/components.py`, `dashboard/export_html.py` |

## End-to-End Flow

```text
run.py
  -> runtime_workflows.load_runtime_config()
  -> runtime_workflows.resolve_run_entries()
  -> zero or more explicit steps:
       A. run_prepare_workflow()
          -> processor.prepare.load_prepared_run_cache()
          -> processor.prepare.read_run()
          -> processor.prepare.prepare_data()
          -> processor.prepare.write_prepared_run_cache()
       B. run_summary_workflow()
          -> processor.summarize.cache.load_summary_run_cache()
          -> run_prepare_workflow() on summary-cache miss
          -> processor.summarize.cache.build_mode_summaries()
          -> processor.summarize.cache.write_summary_run_cache()
       C. load_summary_runs_from_cache() for dashboard-only cache runs
          -> processor.summarize.cache.load_summary_run_cache()
       D. dashboard.app.build_dashboard()
       E. dashboard.export_html.build_export_html_document()
```

## Core Runtime Contracts

### `Config`

`runtime.config.Config` is the normalized application configuration.

Treat it as the contract for:

- which files are read
- how schema aliases are resolved
- which weighting modes exist
- which pages are enabled
- how export selector requests are configured

If a new feature adds a config key or changes config behavior, the README and any relevant docs in this folder should be updated in the same change.

### `RunData`

`processor.models.RunData` is the prepared-data contract consumed by summary builders. Summary code should rely on canonical prepared columns rather than guessing raw ActivitySim column names directly. `processor/prepare/` is the layer that materializes those canonical fields and now also owns prepared-table cache helpers.

### `SummarySpec` and `SUMMARY_SPECS`

`processor.summarize.summary_specs.SUMMARY_SPECS` is the summary registry. It defines:

- the stable summary id used by dashboard pages
- the CSV filename stem used in cache directories
- the builder function that produces the summary table

Adding a summary is not complete until it is registered there.

### `DashboardPageDefinition` and `PageSelectorDefinition`

Dashboard pages are registered through module-level `PAGE = DashboardPageDefinition(...)` objects in `dashboard/pages/`. Export-capable page-local controls are declared in `PAGE.selectors` using `PageSelectorDefinition`.

These definitions are consumed by both the live dashboard and the HTML export path, so they are the supported page extension API.

## Repository Map

```text
activitysim_visualizer/
|-- run.py
|-- runtime_workflows.py
|-- config.yaml
|-- runtime/
|   |-- config.py
|   |-- models.py
|   `-- run_data.py      # temporary compatibility shim during migration
|-- processor/
|   |-- models.py
|   |-- prepare/
|   |   |-- __init__.py
|   |   |-- reader.py
|   |   |-- enrichment.py
|   |   |-- cache.py
|   |   `-- writer.py
|   `-- summarize/
|       |-- __init__.py
|       |-- cache.py
|       |-- schema.py
|       |-- summary_specs.py
|       |-- writer.py
|       `-- summaries/
|           |-- daily_travel.py
|           |-- demographics.py
|           |-- joint_travel.py
|           |-- legacy.py
|           |-- long_term.py
|           |-- tour.py
|           |-- trip.py
|           `-- validation.py
|-- dashboard/
|   |-- app.py
|   |-- components.py
|   |-- export_html.py
|   |-- page_base.py
|   |-- page_definitions.py
|   |-- page_registry.py
|   |-- state.py
|   `-- pages/
`-- tests/
```

## What to Read First

- Start with [summary-workflow.md](summary-workflow.md) if you need to understand cache generation, cache loading, and prepared-run usage.
- Read [adding-summaries.md](adding-summaries.md) before changing anything under `processor/summarize/`.
- Read [adding-dashboard-pages.md](adding-dashboard-pages.md) before adding a dashboard page or page-local export selector.
