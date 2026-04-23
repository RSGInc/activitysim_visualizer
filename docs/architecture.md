# Architecture Overview

`activitysim_visualizer` has three main jobs:

1. Read and normalize raw ActivitySim outputs.
2. Build and cache summary tables.
3. Render those summaries in a live Panel dashboard or a standalone HTML export.

The codebase is organized around those jobs rather than around one monolithic app layer.

## Main Subsystems

| Area | Purpose | Key files |
|---|---|---|
| CLI and workflow orchestration | Parse flags, choose cache-first vs raw-run flow, hand off to the right runtime path | `run.py`, `runtime_workflows.py` |
| Runtime config and prepared data | Normalize YAML config and expose the prepared `RunData` contract used everywhere else | `runtime/config.py`, `runtime/models.py`, `runtime/run_data.py` |
| Summary generation and cache I/O | Register summary builders, compute weighted/unweighted tables, write/load cache manifests and CSVs | `summarize/cache.py`, `summarize/schema.py`, `summarize/*.py` |
| Dashboard registry and state | Discover pages, validate page contracts, hold live state and cached filtered views | `dashboard/page_registry.py`, `dashboard/page_definitions.py`, `dashboard/state.py`, `dashboard/page_base.py` |
| Rendering | Build the live Panel app or serialize a client-side HTML document | `dashboard/app.py`, `dashboard/components.py`, `dashboard/export/` |

## End-to-End Flow

```text
run.py
  -> runtime_workflows.load_runtime_config()
  -> runtime_workflows.resolve_run_entries()
  -> one of:
       A. run_summary_workflow()
          -> runtime.run_data.read_run()
          -> runtime.run_data.prepare_data()
          -> summarize.cache.build_mode_summaries()
          -> summarize.cache.write_summary_run_cache()
       B. load_summary_runs_from_cache()
          -> summarize.cache.load_summary_run_cache()
  -> one of:
       C. dashboard.app.build_dashboard()
       D. dashboard.export.html.build_export_html_document()
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

`runtime.models.RunData` is the prepared-data contract consumed by summary builders. Summary code should rely on canonical prepared columns rather than guessing raw ActivitySim column names directly. `runtime/run_data.py` is the layer that materializes those canonical fields.

### `SummarySpec` and `SUMMARY_SPECS`

`summarize.cache.SUMMARY_SPECS` is the summary registry. It defines:

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
|   `-- run_data.py
|-- summarize/
|   |-- cache.py
|   |-- schema.py
|   |-- demographics.py
|   |-- mandatory.py
|   |-- tours.py
|   |-- tour_mode.py
|   |-- tour_tod.py
|   |-- stops.py
|   |-- trips.py
|   |-- totals.py
|   `-- destination.py
|-- dashboard/
|   |-- app.py
|   |-- components.py
|   |-- export/
|   |   |-- html.py
|   |   |-- payload.py
|   |   |-- serializer.py
|   |   |-- runtime_assets.py
|   |   |-- types.py
|   |   `-- assets/
|   |-- page_base.py
|   |-- page_definitions.py
|   |-- page_registry.py
|   |-- state.py
|   `-- pages/
`-- tests/
```

## What to Read First

- Start with [summary-workflow.md](summary-workflow.md) if you need to understand cache generation, cache loading, and raw-run usage.
- Read [adding-summaries.md](adding-summaries.md) before changing anything under `summarize/`.
- Read [adding-dashboard-pages.md](adding-dashboard-pages.md) before adding a dashboard page or page-local export selector.
- Read [export_html_schema.md](export_html_schema.md) and [export_html_contributor_guide.md](export_html_contributor_guide.md) before changing the offline export contract.
