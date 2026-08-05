# 01 - Architecture

`activitysim_visualizer` has three main jobs:

1. Read and normalize raw ActivitySim outputs.
2. Build and cache summary tables.
3. Render those summaries in a live Panel dashboard or a standalone HTML export.

The codebase is organized around those jobs rather than around one monolithic app layer.

The config surface is now intentionally split into top-level domains such as
`pipeline`, `dashboard`, `display`, `summarize`, `segment`, and `skimjoin`.
`runtime.config.load_config_from_yaml()` validates that canonical schema before
any workflow code sees it. Removed and unknown keys fail with a focused error.

## Main Subsystems

| Area | Purpose | Key files |
|---|---|---|
| CLI and workflow orchestration | Parse step selections, choose cache-first vs rebuild flow, and hand off to prepare/summarize/dashboard workflows | `run.py`, `runtime/workflows/` |
| Shared runtime contracts | Normalize YAML config and expose shared cross-cutting contracts used by both processor and dashboard | public surface `runtime.config`, implementation in `runtime/config/` |
| Processor prepare step | Read raw ActivitySim outputs, materialize canonical prepared columns, and manage prepared-table cache I/O | `processor/models.py`, `processor/prepare/*` |
| Summary generation | Declare builders and compute weighted/unweighted tables | `processor/summarize/contracts.py`, `processor/summarize/catalog.py`, `processor/summarize/summaries/*.py` |
| Summary cache I/O | Inspect, write, and load cache manifests and CSVs | `processor/summarize/cache.py`, `processor/summarize/cache_storage.py` |
| Dashboard page runtime | Discover pages, validate contracts, refresh declared features, and memoize section queries | `dashboard/page_registry.py`, `dashboard/page_definitions.py`, `dashboard/page_lifecycle.py`, `dashboard/page_declarations.py` |
| Rendering | Build context-bound Plotly figures and the live or exported view | `dashboard/rendering/`, `dashboard/app.py`, `dashboard/export/` |

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
- which materialized stages, if any, should be explicitly refreshed
- how schema aliases are resolved
- which weighting modes exist
- which pages are enabled
- how export selector requests are configured

`dashboard.host` is a reserved placeholder for a future hosting integration.
The schema accepts `account`, `app_id`, `title`, and `verify`, but the current
runtime deliberately does not store or act on them.

If a new feature adds a config key or changes config behavior, update the README
and the relevant wiki chapters in the same change.

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

### `@summary` and the summary catalog

Each persisted summary is declared beside its builder with `@summary(...)`. The
declaration defines:

- the stable summary id used by dashboard pages
- the CSV filename stem used in cache directories
- its ordered output schema and prepared-input prerequisites
- whether it is built by default

`processor.summarize.catalog` imports the owning domain modules explicitly,
collects those declarations deterministically, and rejects duplicate ids.
Successful builder results are validated for exact columns, order, and dtypes.
Unexpected builder exceptions follow `summarize.failure_policy`: `record` keeps
typed failure metadata for an interactive dashboard, while `error` is the
fail-fast setting for validation and batch workflows.

### `DashboardPageDefinition` and `DashboardPage`

Dashboard pages are registered with `@dashboard_page(...)` on the page class in
`dashboard/pages/`. The decorator holds identity, navigation grouping, ordering,
and the summary/prepared-data contract through `required_summary_ids`,
`optional_summary_ids`, `prepared_data_mode`, and `required_prepared_tables`.

`dashboard.page_base` is the small public facade. Lifecycle, declarations,
diagnostics, feature composition, data access, and grouped navigation live in
separate implementation modules.

Page authors are expected to:

- implement `build_page()` to declare selectors, features, sections, and layout
- give selectors an option provider and default policy when their domain is dynamic
- compose unrelated user-visible blocks with `self.feature(...)`
- memoize chart-ready transformations with `self.query(...)`
- keep section render methods to lookup/query/render

Large controllers may keep their registered page module as a compatibility
facade and compose page-local implementation mixins from a private `_<page>/`
package. This convention, its constraints, and its distinction from
`PageFeature` are documented in
[Figures And Widgets](32-figures-and-widgets.md#sections-and-features).

The framework now owns:

- widget watchers
- section containers
- section-aware refresh
- selector option refresh and stale-value repair
- query identity derived from page/global/section/selector state
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

For page-local table shaping, `dashboard.data_access.RunTables` applies one
fluent query to every run while preserving run labels. Pages should prefer its
`where`, `with_columns`, `group`, `select`, `sort`, `join`, `requiring`,
`drop_empty`, and `map` operations over open-coded loops through
run/dataframe pairs.

The skim pages share their family-specific model/query service while exposing
small summary and distribution features. This is the reference pattern for
logic reusable within one page family but not broad enough for
`dashboard/helpers/`.

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
|       |-- catalog.py
|       |-- contracts.py
|       |-- csv_export.py
|       |-- schema.py
|       `-- summaries/
|           |-- daily_travel_activity.py
|           |-- daily_travel_escort_counts.py
|           |-- daily_travel_escort_distributions.py
|           |-- demographics.py
|           |-- joint_travel.py
|           |-- long_term_person.py
|           |-- long_term_vehicle.py
|           |-- long_term_geography.py
|           |-- long_term_distance.py
|           |-- tour.py
|           |-- trip.py
|           `-- validation.py
|-- dashboard/
|   |-- app.py
|   |-- rendering/
|   |   |-- context.py
|   |   |-- figures.py
|   |   |-- plotter.py
|   |   |-- layout.py
|   |   `-- tables.py
|   |-- export/
|   |   |-- html.py
|   |   |-- payload.py
|   |   |-- page_serializer.py
|   |   |-- selector_states.py
|   |   |-- serializer.py
|   |   |-- traversal.py
|   |   |-- runtime_assets.py
|   |   |-- types.py
|   |   `-- assets/
|   |-- page_base.py
|   |-- page_declarations.py
|   |-- page_diagnostics.py
|   |-- page_features.py
|   |-- page_lifecycle.py
|   |-- page_navigation.py
|   |-- page_definitions.py
|   |-- page_registry.py
|   |-- state.py
|   `-- pages/
`-- tests/
```

## What to Read First

- Start with [Running Workflows](12-running-workflows.md) to understand cache
  generation, cache loading, and prepared-run usage.
- Read the [Summary Function Cookbook](44-summary-function-cookbook.md) before
  changing anything under `processor/summarize/`.
- Read the [Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md)
  before adding a page, selector, figure, or table.
- Read [HTML Export](34-html-export.md) and the
  [HTML Export Schema](36-html-export-schema.md) before changing the offline
  export contract.
