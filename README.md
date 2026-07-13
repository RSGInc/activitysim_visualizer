# ActivitySim Visualizer

`activitysim_visualizer` is a Panel-based dashboard for exploring and comparing [ActivitySim](https://activitysim.github.io/) outputs. It can:

- compare multiple model runs side by side
- build and reuse prepared and summary caches
- serve a live local dashboard
- export a standalone HTML version for offline sharing

## Quick Start

Install dependencies with `uv`:

```bash
uv sync --locked
```

If `uv sync` fails because of a hardlink issue, retry with:

```bash
uv sync --locked --link-mode=copy
```

Activate the environment:

```bash
.\.venv\Scripts\activate
```

Create a project-specific config:

```bash
Copy-Item config.yaml local_config.yaml
```

Edit `local_config.yaml`, then run the app with that config:

```bash
python run.py --config local_config.yaml
```

By default, `python run.py` follows `pipeline.steps` from the loaded config when no explicit step flags are supplied. The shipped example config defaults to `summarize` + `dashboard`, so a normal run will reuse summary caches when possible, rebuild them when needed, and then start the live dashboard on [http://localhost:5006](http://localhost:5006).

## Dashboard Pages

Dashboard pages now use one shared authoring model:

- page modules export `PAGE = DashboardPageDefinition(...)`
- page classes subclass `DashboardPage`
- page-local controls are registered with `selector(...)`
- refreshable regions are registered with `section(...)`
- live refresh and export metadata both derive from those registrations

The main shared page-helper modules live under `dashboard/helpers/`:

- `category_helpers.py`
- `geography_helpers.py`
- `person_type_helpers.py`
- `time_distance_helpers.py`
- `comparison_helpers.py`

If you are adding or refactoring a page, start with [wiki/33-dashboard-page-recipes.md](wiki/33-dashboard-page-recipes.md). For the broader runtime picture, see [wiki/12-running-workflows.md](wiki/12-running-workflows.md).

## Config Setup

The repo ships with `config.yaml` as a template. In practice, most people should:

1. Copy `config.yaml` to `local_config.yaml` or another machine-specific file.
2. Update the `runs` section to point at real ActivitySim output folders.
3. Update `skimjoin.distance_skim`, `zones`, and `files` if your model layout differs from the defaults.
4. Run with `--config your_file.yaml`.

The canonical config layout is organized around a few top-level sections:

```yaml
root: artifacts/
log_level: INFO

pipeline:
  steps: [summarize, dashboard]
  dashboard_mode: live
  overwrite: false

prepare: ...
summarize: ...
segment: ...
dashboard: ...
display: ...
skimjoin: ...
```

Older keys such as `processor.*`, `summaries.*`, `visualizer.*`, top-level
`dashboard_labels`, and top-level `run_colors` are still supported for
compatibility, but they now emit deprecation warnings and normalize into the
canonical schema above.

The minimum useful config is usually:

```yaml
root: artifacts/summary_cache

pipeline:
  steps:
    - summarize
    - dashboard
  dashboard_mode: live

runs:
  - dir: path\to\run1
    label: Base
  - dir: path\to\run2
    label: Build

skimjoin:
  distance_skim:
    file: path\to\skims.omx
    matrix: SOV_DIST__MD

zones:
  use_maz: false
  maz_col: zone_id
  taz_col: TAZ

files:
  households: final_households
  persons: final_persons
  tours: final_tours
  trips: final_trips
  joint_tour_participants: final_joint_tour_participants
  land_use: final_land_use
```

If runs use different raw filenames, keep `files:` as the default mapping and
override only the differences inside `runs[*].file_map`:

```yaml
files:
  households: final_households
  persons: final_persons
  tours: final_tours
  trips: final_trips

runs:
  - dir: path\to\run1
    label: Base
    file_map:
      households: final_hh
      trips: trip_linked

  - dir: path\to\run2
    label: Build
    file_map:
      households: household
      persons: person
      tours: tour
      trips: trip
```

If a run should skip raw prepare and use externally managed canonical prepared
tables instead, point it at those files with `runs[*].prepared_table_map`:

```yaml
runs:
  - dir: path\to\raw_run
    label: Raw Run

  - label: Custom Prepared Run
    prepared_table_map:
      households: path\to\custom\households.parquet
      persons: path\to\custom\persons.csv
      tours: path\to\custom\tours.parquet
      trips: path\to\custom\trips.csv
      joint_tour_participants: path\to\custom\joint_tour_participants.parquet
      land_use: path\to\custom\land_use.csv
```

`prepared_table_map` is intended for canonical prepared tables that were already
skimjoined and then optionally filtered or otherwise post-processed outside this
repo. When a run uses `prepared_table_map`, the workflow loads those prepared
tables directly and does not rerun raw prepare or integrated skimjoin for that run.

If a run already has dashboard-ready summary tables, point directly at those
files with `runs[*].summary_table_map`:

```yaml
runs:
  - label: Summary Only Demo
    summary_table_map:
      totals: path\to\summaries\totals.csv
      traffic_count_comparisons: path\to\summaries\traffic_count_comparisons.parquet
```

`summary_table_map` uses registered summary IDs as keys, accepts explicit
`.csv` or `.parquet` paths, and resolves relative paths from the config file
directory. Mapped summaries are expected to already use the dashboard's canonical
columns. During summarize they override the listed generated summaries; missing
summaries can still be generated from raw/prepared inputs when those inputs exist.
Some registered summary IDs are external/demo-only and are not generated by
default for raw/prepared runs, which avoids writing `__empty__` cache CSVs just
to make those IDs available to `summary_table_map`.

Integrated skim enrichment can now be selected per run without forcing one
shared skimjoin config for every skim structure. Keep the explicit skimjoin
YAML logic in separate files, then choose the file and optional project-input
overrides per run:

```yaml
skimjoin:
  defaults:
    config_path: configs/skimjoin_default.yaml

runs:
  - dir: path\to\run_a
    label: Run A
    skimjoin:
      config_path: configs/skimjoin_odot_series15.yaml
      skim_files:
        - path\to\run_a\skims\*.omx
        - path\to\run_a\skims\maz_stop_walk.csv
      network_los_file: path\to\run_a\network_los.yaml

  - dir: path\to\run_b
    label: Run B
    skimjoin:
      config_path: configs/skimjoin_combined_walk.yaml
      skim_files:
        - path\to\run_b\skims\*.omx
```

Skimjoin override rules:

- `runs[*].skimjoin.config_path` overrides global `skimjoin.config_path`.
- `runs[*].skimjoin.skim_files` overrides the selected skimjoin config's `project.skim_files`.
- `runs[*].skimjoin.network_los_file` overrides the selected skimjoin config's `project.network_los_file`.
- If a run omits `runs[*].skimjoin`, it uses the global skimjoin settings exactly as before.

Recommended rule of thumb:

- If runs differ only by skim file locations, share one skimjoin config and override `runs[*].skimjoin.skim_files`.
- If runs differ only by period definitions, share one skimjoin config and override `runs[*].skimjoin.network_los_file`.
- If runs differ by lookup logic, fallback behavior, combined vs split components, or directional semantics, use different skimjoin config files.

VOT bin preparation stays in `prepare.vot_bins` and remains run-aware by run label.

Skimjoin dimensions are now standardized under `dimensions`, while
`activitysim` only carries the structural trip/tour fields. The recommended
integrated-runtime pattern is:

```yaml
activitysim:
  trip_mode_column: trip_mode
  trip_id_column: trip_id
  tour_mode_column: tour_mode
  tour_id_column: tour_id
  outbound_column: outbound

dimensions:
  PERIOD:
    source_columns:
      trip_source_column: depart_hour
      outbound_tour_source_column: start_hour
      inbound_tour_source_column: first_inbound_trip_depart
    values_from_network_los: true
    values:
      8: AM
      17: PM
  VOT:
    source_columns:
      trip_source_column: vot_bin
      outbound_tour_source_column: vot_bin
      inbound_tour_source_column: vot_bin
    values:
      L: L
      M: M
      H: H
```

Period behavior is directional by design:

- trips use `dimensions.PERIOD.source_columns.trip_source_column`
- outbound tours use `dimensions.PERIOD.source_columns.outbound_tour_source_column`
- inbound tours use `dimensions.PERIOD.source_columns.inbound_tour_source_column`

In the standard prepare workflow, `first_inbound_trip_depart` is derived from
the first inbound trip on each tour before integrated skimjoin runs.

Prepared endpoint columns are also standardized before skimjoin runs:

- prepared trips and tours always include `OTAZ` and `DTAZ`
- when `zones.use_maz: true`, prepare also materializes `o_maz` and `d_maz`
- inbound tour lookups reuse those same column names, while skimjoin swaps
  their logical direction in the inbound tour context

The normal prepare step can also write prepared caches as CSV when needed:

```yaml
prepare:
  output:
    file_format: csv
  validation:
    relationship_checks: warn
```

Important path rules:

- `root` is resolved relative to the config file if you give a relative path.
- The prepared cache is created automatically next to `root` as `prepared_cache/`.
- `runs[*].dir` should point at an ActivitySim output directory.
- `skimjoin.distance_skim.file` may be absolute, or relative to each run directory.
- File entries under `files` can be bare stems like `final_trips` or explicit filenames like `final_trips.csv`.
- `runs[*].file_map` uses the same filename rules as `files`, but applies only to that run.
- `runs[*].prepared_table_map` must use explicit `.parquet` or `.csv` paths and resolves relative paths from the config file directory.
- `runs[*].summary_table_map` must use registered summary IDs with explicit `.parquet` or `.csv` paths and resolves relative paths from the config file directory.
- `prepare.output.file_format` controls how standard prepared caches are written; supported values are `parquet` and `csv`, with `parquet` as the default.
- `prepare.validation.relationship_checks` controls prepared-table foreign-key validation. Use `warn` to log inconsistencies and continue, `error` to fail the run, or `off` to skip the checks.
- `dashboard.export.output_path`, when relative, is resolved from `root`.

## Config Reference

These are the sections most people need to touch:

| Section | Purpose |
|---|---|
| `root` | Where summary caches are stored |
| `pipeline` | Default workflow steps, dashboard mode, and overwrite behavior |
| `runs` | Run directories, display labels, and optional per-run skim, raw file-map, custom prepared-table map, custom summary-table map, and weight overrides |
| `skimjoin.distance_skim` | Default distance skim file and matrix name used by summaries |
| `zones` | MAZ/TAZ settings for skim joins and zone normalization |
| `files` | Default ActivitySim output file stems or filenames used unless a run overrides them |
| `columns` | Column aliases when outputs use non-default names |
| `prepare.output.file_format` | On-disk format for prepared caches written by the normal prepare workflow |
| `prepare.validation.relationship_checks` | Whether cross-table prepared-key validation is disabled, warns, or errors |
| `prepare.student_types` | Optional school/university enrollment definitions for shadow pricing pages |
| `dashboard.title` | Title used in the live dashboard and HTML export |
| `dashboard.live.pages` | Ordered list of live pages/groups to show |
| `dashboard.export` | Export-only output path, page selection, and selector-state controls |
| `display.run_colors` | Plot colors by run |
| `display.labels` | Presentation-only labels and ordering for dashboard/export |
| `summarize.weighting_modes` | Which cache variants to build: `weighted`, `unweighted`, or both |
| `summarize.geography` | Optional configured district/county/zone mappings |
| `summarize.pnr_tour_modes` | Which tour modes count as park-and-ride in summary builders |
| `summarize.group_*_tour_purposes` | Summary-time purpose regrouping switches |
| `summarize.category_normalization` | Summary-affecting category normalization/regrouping |
| `modes` | Optional mode ordering and grouped mode display |
| `person_types` | Optional display labels for `ptype` values |

Weighting rules:

- If a run sets `hh_weight_col`, `person_weight_col`, or `trip_weight_col`, those are used.
- Otherwise, if a `sample_rate` column is available, weights are derived from it.
- Otherwise, weights default to `1`.

Geography summary notes:

- Summaries may emit `all_geographies` total rows independently of the geography config.
- Native prepared geographies such as `home_taz`, `home_county`, and `home_mpo` may appear whenever those columns are available in prepared data, even when `summarize.geography.enabled: false`.
- `summarize.geography` controls additional mapped geography aggregations, such as `home_geo__school_district`, `work_geo__county`, or `land_use_geo__district`.

Legacy config notes:

- Prefer the canonical top-level schema: `root`, `pipeline`, `dashboard`, `display`, `summarize`, `segment`, and `skimjoin`.
- Older keys such as `processor.root`, `summaries.weighting_modes`, `visualizer.dashboard_pages`, top-level `run_colors`, top-level `summary_categories`, and top-level `student_types` are still supported for compatibility, but now log deprecation warnings.

Geography note:

- `geography.enabled: false` now disables both the older geography mapping behavior and the newer `geography.aggregations` derived columns. If you want aggregation-based geography summaries, `geography.enabled` must be `true`.

Category config note:

- Use `summarize.category_normalization` when a mapping changes summary values, grouping membership, or canonical category values.
- Use `display.labels` when a change is cosmetic and should only affect dashboard/export labels or ordering.

## Live Pages And Export Pages

`dashboard.live.pages` controls the live dashboard only. `dashboard.export` controls what goes into the standalone HTML export.

Current top-level page ids are:

- `overview`
- `long_term_choices`
- `daily_travel`
- `joint_travel`
- `tour_summaries`
- `trip_summaries`
- `validation`
- `raw_trip_demo`

Grouped page ids support either the whole group or specific child pages. For example:

```yaml
dashboard:
  live:
    pages:
      - overview
      - long_term_choices:
        - individual_choices
        - mandatory_location_choice
        - shadow_pricing
      - daily_travel: default
      - tour_summaries: all
      - trip_summaries:
        - trip_mode
        - trip_stop_time
```

Notes:

- `default` means "the group's default enabled children".
- `all` means every child page in the group.
- A plain group id like `tour_summaries` behaves like the group's default selection.
- `raw_trip_demo` is disabled by default and requests prepared trip tables, so keep it out unless you explicitly want that behavior.

For HTML export, you can further narrow the exported page set and selector states:

```yaml
dashboard:
  export:
    dashboard:
      weighting: [unweighted]
      values: [percent]
    exclude_groups: [validation]
    pages:
      long_term_choices:
        shadow_pricing:
          geography_level: [all]
          student_type: [all]
          parts:
            workplace_table:
              enabled: false
            school_table:
              enabled: false
```

Rules worth remembering:

- If `dashboard.live.pages` is omitted, the app uses its built-in default page set.
- If `dashboard.export.pages` is omitted, export mirrors the live page set.
- Export selector requests accept `default`, `all`, or a list of explicit values.
- `dashboard.export.exclude_pages` and `exclude_groups` remove pages from export without changing the live dashboard.

## Run Modes

The CLI exposes three workflow steps:

1. `prepare`
2. `summarize`
3. `dashboard`

Common commands:

| Command | What it does |
|---|---|
| `python run.py --config local_config.yaml` | Reuse or build summaries, then start the live dashboard |
| `python run.py --config local_config.yaml --prepare-only` | Build prepared caches and exit |
| `python run.py --config local_config.yaml --summarize` | Reuse or build summary caches and exit |
| `python run.py --config local_config.yaml --summarize --dashboard` | Explicit form of the default live workflow |
| `python run.py --config local_config.yaml --dashboard` | Start the dashboard from existing summary caches for the configured runs |
| `python run.py --config local_config.yaml --prepare --summarize --dashboard` | Force the full prepare -> summarize -> dashboard chain in one run |
| `python run.py --config local_config.yaml --from-csvs` | Start the dashboard from existing summary caches only |
| `python run.py --config local_config.yaml --from-csvs --export-html output.html` | Build a standalone HTML export from existing summary caches |
| `python run.py --config local_config.yaml --summarize --write-csvs` | Rebuild summaries and write fresh cache files |
| `python run.py --config local_config.yaml --summarize --skip-summary-cache-write` | Build summaries for this run without writing cache updates |
| `python run.py --config local_config.yaml --summarize --refresh-summary-cache` | Delete and rebuild summary caches for the selected runs |
| `python run.py --config local_config.yaml --summarize --refresh-prepared-cache` | Rebuild summaries from freshly prepared tables instead of prepared-cache hits |
| `python run.py --config local_config.yaml --prepare --summarize --refresh-caches` | Delete and rebuild both prepared and summary caches for the selected runs |

Behavior details:

- `--from-csvs` is cache-only: it reads visualizer summary-cache directories with manifests, not loose summary CSVs.
- `--from-csvs path\to\cache1 path\to\cache2` lets you point directly at specific summary cache directories.
- Use `runs[*].summary_table_map` when you have loose dashboard-ready summary files instead of visualizer cache directories.
- `--dashboard` by itself is valid when summary caches already exist for the configured runs.
- During summarize, the app will reuse prepared cache when possible and rebuild from raw outputs only when needed.
- `--refresh-prepared-cache` deletes the selected runs' prepared-cache directories first, then disables prepared-cache reuse for that invocation.
- `--refresh-summary-cache` deletes the selected runs' summary-cache directories first, then disables summary-cache reuse for that invocation.
- `--refresh-caches` is shorthand for both refresh flags together.

## Cache Layout

Prepared caches are written automatically next to the summary cache root:

```text
<summary_root_parent>/
  prepared_cache/
    <run_key>/
      manifest.json
      households.parquet|csv
      persons.parquet|csv
      tours.parquet|csv
      trips.parquet|csv
      joint_tour_participants.parquet|csv
      land_use.parquet|csv
```

Summary caches are written under `root`:

```text
<summary_root>/
  <run_key>/
    manifest.json
    weighted/
    unweighted/
```

Both cache layers validate manifests before reuse. Cache invalidation is driven by:

- the run inputs
- the prepare and summary config digests
- the prepared-manifest identity used to build summary caches
- per-summary summary digests inside the summary-cache manifest

That means presentation-only config changes usually do not force summary rebuilds, and adding a newly requested summary can backfill just that table instead of rebuilding the entire summary bundle.

## CLI Overrides

You can override runs on the command line instead of putting them in the config:

```bash
python run.py --config local_config.yaml ^
  --run C:\path\to\run1 "Base" ^
  --run C:\path\to\run2 "Build"
```

Optional per-run skim overrides can be supplied in the same order:

```bash
python run.py --config local_config.yaml ^
  --run C:\path\to\run1 "Base" ^
  --run C:\path\to\run2 "Build" ^
  --run-skim C:\path\to\base_skims.omx C:\path\to\build_skims.omx
```

Use `null`, `None`, or an empty string in `--run-skim` to fall back to the configured `skimjoin.distance_skim.file`.

## Codebase Map

```text
activitysim_visualizer/
|-- run.py
|-- runtime/
|   |-- workflows/
|-- runtime/
|   `-- config/
|-- processor/
|   |-- prepare/
|   |-- summarize/
|   `-- models.py
|-- dashboard/
|   |-- app.py
|   |-- export/
|   |-- page_base.py
|   |-- page_definitions.py
|   |-- page_registry.py
|   |-- state.py
|   `-- pages/
`-- tests/
```

## Wiki

User and contributor documentation lives under [`wiki/`](wiki/):

- [`wiki/00-home.md`](wiki/00-home.md)
- [`wiki/10-getting-started.md`](wiki/10-getting-started.md)
- [`wiki/11-configuring-your-data.md`](wiki/11-configuring-your-data.md)
- [`wiki/12-running-workflows.md`](wiki/12-running-workflows.md)
- [`wiki/20-output-processor.md`](wiki/20-output-processor.md)
- [`wiki/30-output-visualizer.md`](wiki/30-output-visualizer.md)
- [`wiki/40-developer-workflows.md`](wiki/40-developer-workflows.md)
- [`wiki/90-troubleshooting.md`](wiki/90-troubleshooting.md)

If you are running or configuring the tool, start with `wiki/10-getting-started.md`.
If you are changing the codebase, start with `wiki/40-developer-workflows.md`.

## Documentation Maintenance Checklist

When behavior changes, update docs in the same change:

- New config key or config behavior: update this README and affected wiki chapters.
- New summary contract or registration pattern: update `wiki/23-summary-functions.md` and regenerate catalogs.
- New page, selector, or export behavior: update `wiki/31-dashboard-pages.md`, `wiki/32-figures-and-widgets.md`, or `wiki/33-dashboard-page-recipes.md`.
- New export payload/runtime behavior: update `wiki/34-html-export.md`.
- Architecture or runtime-flow changes: update `wiki/12-running-workflows.md`, `wiki/20-output-processor.md`, or `wiki/30-output-visualizer.md`.
