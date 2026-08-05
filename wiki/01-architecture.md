# 01 - Architecture

`activitysim_visualizer` has three main jobs:

1. Read and normalize raw ActivitySim outputs.
2. Build and cache summary tables.
3. Render those summaries in a live Panel dashboard or a standalone HTML export.

The codebase has a separate subsystem for each job.

The configuration has top-level sections such as `pipeline`, `dashboard`,
`display`, `summarize`, `segment`, and `skimjoin`.
`runtime.config.load_config_from_yaml()` validates the canonical schema before
the workflow uses it. Removed keys and unknown keys cause a specific error.

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
          -> inspect/load the final prepared cache
          -> when skimjoin is enabled, inspect/load the base prepared cache separately
          -> processor.prepare.reader.read_run()
          -> processor.prepare.enrichment.pipeline.prepare_data()
          -> processor.skimjoin.pipeline.apply_skimjoin() when selected
          -> processor.prepare.cache.write_prepared_run_cache()
       B. run_summary_workflow()
          -> inspect reusable/stale tables in the summary bundle
          -> run_prepare_workflow() on summary-cache miss
          -> processor.summarize.builder.build_mode_summaries_with_metadata()
          -> merge reusable and rebuilt tables
          -> processor.summarize.cache.write_summary_run_bundle()
       C. load_summary_runs_from_cache() for dashboard-only cache runs
          -> processor.summarize.cache.load_summary_run_bundle()
       D. run_dashboard_workflow()
          -> dashboard.app.build_dashboard() and Panel serve for live mode
          -> dashboard.export.write_export_html_document() for export mode
```

The runtime passes one resolved `WorkflowPlan` to these operations.
`run_prepare_workflow()` returns `PreparedRunsArtifact`.
`run_summary_workflow()` returns `SummaryRunsArtifact`. The runtime workflows
control the cache policy. Processor functions only transform tables.

## Core Runtime Contracts

### `Config`

`runtime.config.Config` is the normalized application configuration. Import
the public API from `runtime.config`. The implementation is in the
`runtime/config/` package.

Treat it as the contract for:

- files that the application reads
- logical pipeline steps that the application requests by default
- default dashboard mode (`none`, `live`, `export`, `host`)
- stored stages that require a refresh
- rules to resolve schema aliases
- which weighting modes exist
- enabled pages
- export selector request configuration

`dashboard.host` is reserved for a future hosting integration. The schema
accepts `account`, `app_id`, `title`, and `verify`. The runtime does not store
or use these values.

If a feature adds a configuration key or changes configuration behavior,
update the README and the applicable wiki chapters in the same change.

`Config.pipeline` is the canonical home for workflow defaults. Today the
logical step names are:

- `prepare`
- `skimjoin`
- `segment`
- `summarize`
- `dashboard`

The runtime executes three main workflow boundaries: `prepare`, `summarize`,
and `dashboard`. The runtime resolves `skimjoin` in the prepare workflow. It
resolves `segment` in the summarize workflow.

### `RunData`

`processor.models.RunData` is the prepared-data contract. Summary builders and
prepared-data dashboard pages use this contract. Summary code must use
canonical prepared columns. It must not estimate the names of raw ActivitySim
columns. The `processor/prepare/` subsystem creates the canonical fields and
contains the prepared-table cache helpers.

### `@summary` and the summary catalog

Declare each persistent summary next to its builder with `@summary(...)`. The
declaration defines:

- the stable summary id used by dashboard pages
- the CSV file-name stem used in cache directories
- its ordered output schema and prepared-input prerequisites
- default build status

`processor.summarize.catalog` imports the applicable domain modules. It
collects the declarations in a repeatable order and rejects duplicate IDs. The
system validates the columns, column order, and data types of each successful
builder result. The `summarize.failure_policy` setting controls unexpected
builder exceptions. The `record` value keeps typed failure metadata for an
interactive dashboard. The `error` value stops validation and batch workflows
immediately.

### `DashboardPageDefinition` and `DashboardPage`

Register a dashboard page with `@dashboard_page(...)` on its page class in
`dashboard/pages/`. The decorator defines identity, navigation group, order,
and the summary or prepared-data contract through `required_summary_ids`,
`optional_summary_ids`, `prepared_data_mode`, and `required_prepared_tables`.

`dashboard.page_base` is the small public facade. Lifecycle, declarations,
diagnostics, feature composition, data access, and grouped navigation live in
separate implementation modules.

Page authors must:

- implement `build_page()` to declare selectors, features, sections, and layout
- give selectors an option provider and default policy when their domain is dynamic
- compose unrelated user-visible blocks with `self.feature(...)`
- memoize chart-ready transformations with `self.query(...)`
- keep section render methods to lookup/query/render

Large controllers can keep the registered page module as a compatibility
facade. They can use page-local implementation mixins from a private `_<page>/`
package. For the rules and the difference from `PageFeature`, see
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

The same selector and section registration graph controls live refresh and
export behavior. Separate page metadata does not control these behaviors.

The page authoring model includes the shared helpers in `dashboard/helpers/`:

- `category_helpers.py` centralizes selector domains, labels, and category completion
- `geography_helpers.py` centralizes geography normalization, option discovery, and filters
- `person_type_helpers.py` centralizes person-type selectors and total-row handling
- `time_distance_helpers.py` centralizes repeated time-bin and distance-bin behavior
- `comparison_helpers.py` centralizes percent-error formatting and base-run comparisons

For page-local table changes, `dashboard.data_access.RunTables` applies one
query to every run and keeps the run labels. Pages must use its
`where`, `with_columns`, `group`, `select`, `sort`, `join`, `requiring`,
`drop_empty`, and `map` operations when possible. Do not write equivalent loops
through run and data frame pairs.

The skim pages use a model and query service for their page family. Each page
provides small summary and distribution features. Use this pattern for logic
that one page family shares. Put more general logic in `dashboard/helpers/`.

## Public Python APIs

Import these facades when you extend or embed the visualizer. A file that a
facade does not export is an implementation detail. A cookbook can identify an
exception as an extension point.

| Import surface | Public contract |
|---|---|
| `runtime.config` | `Config`, `load_config_from_yaml()`, `config_for_run()`, `resolve_run_skimjoin_settings()`, normalized export/pipeline/prepare/segmentation setting types, and weighting registry types. `Config.from_yaml()` is the equivalent class entry point. |
| `runtime.workflows` | Config/run resolution; prepared and summary cache roots/loaders; `run_prepare_workflow()`, `run_summary_workflow()`, and `run_dashboard_workflow()`; consumer pruning; `WorkflowPlan`, `PreparedRunsArtifact`, `SummaryRunsArtifact`, and `SummaryCacheInspection`. Workflow functions are keyword-oriented and return artifacts rather than hidden module state. |
| `processor` | `RunData`, the canonical prepared-run data contract. |
| `processor.summarize` | `summary`, the declaration decorator for registered summary builders. |
| `dashboard` | `DashboardPage`, `dashboard_page`, `DashboardState`, `PageData`, `RunTables`, and prepared/summary provider types used by page and embedding code. |
| `dashboard.page_base` | `GroupedDashboardPage`, `PageFeature`, selector/section declaration types, and `PAGE_SELECTOR_STYLESHEET`, in addition to `DashboardPage`. |
| `dashboard.rendering` | `RenderContext`, `FigureBuilder`, `Plotter`, table/formatting helpers, selector/control rows, legends, and the standard unavailable card. |
| `dashboard.export` | `build_export_html_document()` for an in-memory document and `write_export_html_document()` for the streamed file/diagnostics workflow. |

The normalized config value objects exported alongside `Config` are
`CategorySpec`, `PipelineSettings`, `ExportDashboardSettings`,
`ExportHTMLSettings`, `ExportSelectorRequest`,
`PrepareNonMotorizedDistanceSkimSettings`, `SegmentationDefinition`,
`PreparedColumnSegmentationSource`, `CsvLookupSegmentationSource`, and
`StudentTypeConfig`. They are read-only runtime contracts. YAML normalization
supplies user input. Do not assemble a `Config` manually.

The workflow facade also exports `effective_processor_config()`,
`run_entries_with_keys()`, `prepared_cache_root()`, `summary_cache_root()`,
`prune_summary_runs()`, and `prune_summary_artifact()`. Embedding code can use
them to get the same identity and removal behavior as `run.py`. The
dashboard facade exports `DashboardPreparedRunProvider` and
`DashboardSummarySeries`; the page-base facade exports the typed
`RegisteredPageSelector`, `RegisteredPageSection`, and `SectionContent`
declaration records.

Chapter 32 describes the page-facing `PageData` and `RunTables` API. Chapter 35
describes chart keywords. Chapter 23 describes the `@summary` contract. The
subsystem sections above describe workflow arguments and artifacts. Public code must pass
an explicit `WorkflowPlan` when the required behavior differs from the loaded
configuration. The plan records logical steps, runtime boundaries, dashboard
mode, and refresh targets.

## Repository Map

```text
activitysim_visualizer/
|-- run.py
|-- config.yaml
|-- runtime/
|   |-- config/                 # canonical schema, normalizers, models, signatures
|   |-- workflows/              # prepare/summarize/dashboard orchestration and artifacts
|   |-- logging.py
|   `-- weighting.py
|-- processor/
|   |-- analysis_units.py
|   |-- cache_identity.py
|   |-- cache_infra.py
|   |-- models.py
|   |-- segmentation.py
|   |-- prepare/
|   |   |-- availability.py
|   |   |-- cache.py
|   |   |-- enrichment/
|   |   |   |-- canonicalize.py
|   |   |   |-- columns.py
|   |   |   |-- domains.py
|   |   |   |-- finalize.py
|   |   |   |-- households_persons.py
|   |   |   |-- non_motorized_distance.py
|   |   |   |-- pipeline.py
|   |   |   |-- student_enrollment.py
|   |   |   |-- time_periods.py
|   |   |   |-- tours.py
|   |   |   |-- trips.py
|   |   |   |-- weights.py
|   |   |   `-- zones.py
|   |   |-- reader.py
|   |   |-- validation.py
|   |   `-- writer.py
|   |-- skimjoin/               # config, inventory, annotation, stores, QA reports, CLI
|   `-- summarize/
|       |-- builder.py
|       |-- cache.py
|       |-- cache_storage.py
|       |-- cache_types.py
|       |-- catalog.py
|       |-- contracts.py
|       |-- csv_export.py
|       |-- external.py
|       |-- schema.py
|       |-- validation_derived.py
|       `-- summaries/
|           `-- <domain summary modules>
|-- dashboard/
|   |-- app.py
|   |-- calculation_notes.py / calculation_notes.yaml
|   |-- data_access.py
|   |-- helpers/
|   |-- rendering/
|   |   |-- context.py
|   |   |-- figures.py
|   |   |-- labels.py
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
|   |   |-- js_runtime/
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
|-- scripts/
|   |-- generate_wiki_catalogs.py
|   `-- generate_validation_demo_fixtures.py
|-- wiki/
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
