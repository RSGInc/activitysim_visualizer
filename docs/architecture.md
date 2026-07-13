# Architecture Overview

`activitysim_visualizer` has three main jobs:

1. Read and normalize raw ActivitySim outputs.
2. Build and cache summary tables.
3. Render those summaries in a live Panel dashboard or a standalone HTML export.

The codebase is organized around those jobs rather than around one monolithic app layer.

The config surface is now intentionally split into top-level domains such as
`pipeline`, `dashboard`, `display`, `summarize`, `segment`, and `skimjoin`.
`runtime.config.load_config()` validates that canonical schema before any
workflow code sees it. Removed and unknown keys fail with a focused error.

## Main Subsystems

| Area | Purpose | Key files |
|---|---|---|
| CLI and workflow orchestration | Parse step selections, choose cache-first vs rebuild flow, and hand off to prepare/summarize/dashboard workflows | `run.py`, `runtime/workflows/` |
| Shared runtime contracts | Normalize YAML config and expose shared cross-cutting contracts used by both processor and dashboard | public surface `runtime.config`, implementation in `runtime/config/` |
| Processor prepare step | Read raw ActivitySim outputs, materialize canonical prepared columns, and manage prepared-table cache I/O | `processor/models.py`, `processor/prepare/*` |
| Summary generation | Register builders and compute weighted/unweighted tables | `processor/summarize/builder.py`, `processor/summarize/summary_specs.py`, `processor/summarize/summaries/*.py` |
| Summary cache I/O | Inspect, write, and load cache manifests and CSVs | `processor/summarize/cache.py`, `processor/summarize/cache_storage.py` |
| Dashboard registry and state | Discover pages, validate page contracts, hold live state and cached filtered views | `dashboard/page_registry.py`, `dashboard/page_definitions.py`, `dashboard/state.py`, `dashboard/page_base.py` |
| Rendering | Build the live Panel app or serialize a client-side HTML document | `dashboard/app.py`, `dashboard/components.py`, `dashboard/export/` |

## End-to-End Flow

```text
run.py
  -> runtime.workflows.load_runtime_config()
  -> runtime.workflows.resolve_run_entries()
  -> resolve_effective_plan() from CLI overrides + config.pipeline defaults
  -> zero or more runtime steps:
       A. run_prepare_workflow()
          -> processor.prepare.cache.load_prepared_run_cache()
          -> processor.prepare.reader.read_run()
          -> processor.prepare.enrichment.pipeline.prepare_data()
          -> processor.prepare.cache.write_prepared_run_cache()
       B. run_summary_workflow()
          -> processor.summarize.cache.load_summary_run_cache()
          -> run_prepare_workflow() on summary-cache miss
          -> processor.summarize.builder.build_mode_summaries_with_metadata()
          -> processor.summarize.cache.write_summary_run_cache()
       C. load_summary_runs_from_cache() for dashboard-only cache runs
          -> processor.summarize.cache.load_summary_run_cache()
       D. dashboard.app.build_dashboard()
       E. dashboard.export.html.build_export_html_document()
```

`WorkflowPlan` is the single resolved execution plan passed into these
operations. `run_prepare_workflow()` returns `PreparedRunsArtifact`, and
`run_summary_workflow()` returns `SummaryRunsArtifact`. Cache policy stays in
these runtime workflows; processor functions only transform tables.

## Core Runtime Contracts

### `Config`

`runtime.config.Config` is the normalized application configuration. The public
import surface remains `runtime.config`, while the implementation now lives in
the `runtime/config/` package.

Treat it as the contract for:

- which files are read
- which logical pipeline steps are requested by default
- which dashboard mode is used by default (`none`, `live`, `export`, `host`)
- whether a run should prefer cache reuse or overwrite behavior by default
- how schema aliases are resolved
- which weighting modes exist
- which pages are enabled
- how export selector requests are configured

If a new feature adds a config key or changes config behavior, the README and any relevant docs in this folder should be updated in the same change.

`Config.pipeline` is the canonical home for workflow defaults. Today the
logical step names are:

- `prepare`
- `skimjoin`
- `summarize`
- `segment`
- `dashboard`

The runtime still executes three coarse workflow boundaries (`prepare`,
`summarize`, `dashboard`). `skimjoin` currently resolves inside the prepare
workflow, and `segment` currently resolves inside the summarize workflow.

### `RunData`

`processor.models.RunData` is the prepared-data contract consumed by summary builders and prepared-data dashboard pages. Summary code should rely on canonical prepared columns rather than guessing raw ActivitySim column names directly. `processor/prepare/` is the layer that materializes those canonical fields and owns prepared-table cache helpers.

### `SummarySpec` and `SUMMARY_SPECS`

`processor.summarize.summary_specs.SUMMARY_SPECS` is the summary registry. It defines:

- the stable summary id used by dashboard pages
- the CSV filename stem used in cache directories
- the builder function that produces the summary table

Adding a summary is not complete until it is registered there.

### `DashboardPageDefinition` and `DashboardPage`

Dashboard pages are registered with `@dashboard_page(...)` on the page class in
`dashboard/pages/`. The decorator holds identity, navigation grouping, ordering,
and the summary/prepared-data contract through `required_summary_ids`,
`optional_summary_ids`, `prepared_data_mode`, and `required_prepared_tables`.

The public page authoring API lives on `dashboard.page_base.DashboardPage`.

Page authors are expected to:

- implement `build_page()` to create widgets and stable layout once
- optionally implement `sync_controls()` to reconcile selector options and values
- use `self.select(...)` for dropdowns and `self.selector(...)` for custom widgets
- register refreshable/exportable regions with `self.section(...)`
- return section content from section render functions

The framework now owns:

- widget watchers
- section containers
- section-aware refresh
- stale tracking
- export selector metadata
- export region metadata

That means live refresh behavior and export behavior both derive from the same selector/section registration graph rather than from separate page metadata declarations.

The shared helper layer under `dashboard/helpers/` is now part of that page
authoring model:

- `category_helpers.py` centralizes selector domains, labels, and category completion
- `geography_helpers.py` centralizes geography normalization, option discovery, and filters
- `person_type_helpers.py` centralizes person-type selectors and total-row handling
- `time_distance_helpers.py` centralizes repeated time-bin and distance-bin behavior
- `comparison_helpers.py` centralizes percent-error formatting and base-run comparisons

For page-local table shaping, `dashboard.data_access.RunTableView` applies one
fluent query to every run while preserving run labels. Pages should prefer its
`where`, `with_columns`, `group`, `select`, `sort`, `join`, `requiring`,
`drop_empty`, and `map` operations over open-coded loops through
run/dataframe pairs.

The skim pages intentionally keep their own family-specific shared module at
`dashboard/pages/skim_summaries/_shared.py`. That file is the reference pattern
for shared logic that is reusable within one page family but not broad enough
for `dashboard/helpers/`.

## Repository Map

```text
activitysim_visualizer/
|-- run.py
|-- runtime/
|   |-- workflows/
|-- config.yaml
|-- runtime/
|   `-- config/
|-- processor/
|   |-- models.py
|   |-- prepare/
|   |   |-- __init__.py
|   |   |-- availability.py
|   |   |-- cache.py
|   |   |-- enrichment/
|   |   |   |-- __init__.py
|   |   |   |-- canonicalize.py
|   |   |   |-- columns.py
|   |   |   |-- domains.py
|   |   |   |-- finalize.py
|   |   |   |-- households_persons.py
|   |   |   |-- pipeline.py
|   |   |   |-- tours.py
|   |   |   |-- trips.py
|   |   |   |-- types.py
|   |   |   |-- weights.py
|   |   |   `-- zones.py
|   |   |-- reader.py
|   |   `-- writer.py
|   `-- summarize/
|       |-- builder.py
|       |-- cache.py
|       |-- cache_storage.py
|       |-- cache_types.py
|       |-- summary_specs.py
|       `-- summaries/
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

- Start with [summary-workflow.md](summary-workflow.md) if you need to understand cache generation, cache loading, and prepared-run usage.
- Read [adding-summaries.md](adding-summaries.md) before changing anything under `processor/summarize/`.
- Read [adding-dashboard-pages.md](adding-dashboard-pages.md) before adding a dashboard page or page-local export selector.
- Read [export_html_schema.md](export_html_schema.md) and [export_html_contributor_guide.md](export_html_contributor_guide.md) before changing the offline export contract.
