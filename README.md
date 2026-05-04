# ActivitySim Visualizer

`activitysim_visualizer` is a Panel-based dashboard for exploring and comparing [ActivitySim](https://activitysim.github.io/) outputs. It supports multiple model runs, weighted and unweighted summaries, and standalone HTML export for offline review.

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

Then choose one of the common workflows:

```bash
# Materialize prepared tables only
python run.py --prepare-only

# Run summarize + dashboard explicitly
python run.py --summarize --dashboard

# Serve the dashboard from prebuilt summary caches only
python run.py --from-csvs

# Export a cache-backed dashboard to standalone HTML
python run.py --from-csvs --export-html output.html
```

`python run.py` remains a shortcut for `--summarize --dashboard`.

The live dashboard runs at [http://localhost:5006](http://localhost:5006) by default.

## Configuration Highlights

Copy `config.yaml` and edit it for your deployment. The most important sections are:

| Section | Purpose |
|---|---|
| `runs` | Run directories, labels, and optional per-run skim/weight overrides |
| `summaries` | Cache root and enabled weighting modes |
| `visualizer.dashboard_title` | Dashboard title shown in the UI and export |
| `visualizer.dashboard_pages` | Ordered live page/group selection list |
| `visualizer.export_html` | Export-only dashboard controls and page selector requests |
| `columns` | Raw-column aliases when ActivitySim outputs differ from expected names |
| `skim` | Global skim file and matrix defaults |
| `geography` | Optional geography breakdown configuration |
| `modes` | Display ordering and grouping for travel modes |

Rules worth knowing up front:

- `visualizer.dashboard_pages` controls live page/group inclusion and order only.
- `visualizer.export_html.pages` controls export page/group inclusion and export selector values.
- If `summaries` or `visualizer` is omitted, the app falls back to built-in defaults.
- Older top-level and `outputs.*` aliases are ignored in favor of `summaries.*` and `visualizer.*`.

Example run configuration:

```yaml
runs:
  - dir: /path/to/run1
    label: Base
    skim_file: null
    hh_weight_col: null
    person_weight_col: null
    trip_weight_col: null

  - dir: /path/to/run2
    label: Build
```

Example grouped dashboard/export configuration:

```yaml
visualizer:
  dashboard_pages:
    - overview
    - tours
    - stops:
      - frequency
      - timing
    - trip_mode
  export_html:
    pages:
      tours:
        children:
          summary:
            person_type: all
          mode:
            purpose: all
      trip_mode:
        tour_purpose: all
        tour_mode: all
```

`dashboard/pages/` now supports a mixed structure:

- standalone top-level pages remain as single files like `dashboard/pages/overview.py`
- grouped pages live under subdirectories like `dashboard/pages/tours/` and `dashboard/pages/stops/`
- each group directory declares one top-level group plus one or more child page modules
- new or refactored pages should use `DashboardPage.build_page()`, `self.selector(...)`, and `self.section(...)` rather than page-local selector/export metadata in `PAGE`

If no explicit weight columns are configured and no `sample_rate` column is present, weights default to `1`.

## Main Workflows

This repo supports four explicit workflow stages:

1. Raw ActivitySim outputs -> prepared cache
2. Prepared cache -> summary cache
3. Summary cache plus page-required prepared tables -> live dashboard
4. Summary cache plus export-required prepared tables -> standalone HTML export

Prepared caches are written under the configured prepared root with one directory per run:

```text
<prepared_root>/
  <run_key>/
    manifest.json
    households.parquet|csv
    persons.parquet|csv
    tours.parquet|csv
    trips.parquet|csv
    joint_tour_participants.parquet|csv
    land_use.parquet|csv
```

Summary caches are written under `summaries.root` with one directory per run:

```text
<summary_root>/
  <run_key>/
    manifest.json
    weighted/
    unweighted/
```

Prepared manifests record the prepare-config digest plus the run fingerprint used to build each prepared run, along with per-table state/diagnostic metadata for prepared tables that were empty, unavailable, or failed. Summary manifests record summary ids, weighting modes, a summary-config digest, the run fingerprint, the prepared-manifest identity they were built from, and per-summary state/diagnostic metadata for summaries that were empty, unavailable, or failed.

Within `processor/prepare/`, raw inputs are loaded in `reader.py`, cache and manifest handling lives in `cache.py`, and prepared-table enrichment is split into focused modules under `processor/prepare/enrichment/`. The public enrichment entrypoint is `processor.prepare.enrichment.pipeline.prepare_data`.

Within `processor/summarize/`, the registry in `summary_specs.py` stays intentionally small while builder contracts supply typed empty fallback schemas and optional prerequisite metadata. `processor/summarize/cache.py` uses those contracts to keep summarize best-effort per summary instead of failing the whole run when one summary cannot be built safely.

## Codebase Map

```text
activitysim_visualizer/
|-- run.py
|-- runtime_workflows.py
|-- runtime/
|   |-- config.py
|-- processor/
|   |-- models.py
|   |-- prepare/
|   |   |-- availability.py
|   |   |-- cache.py
|   |   |-- enrichment/
|   |   |   |-- pipeline.py
|   |   |   |-- columns.py
|   |   |   |-- canonicalize.py
|   |   |   |-- weights.py
|   |   |   |-- zones.py
|   |   |   |-- households_persons.py
|   |   |   |-- tours.py
|   |   |   |-- trips.py
|   |   |   `-- finalize.py
|   |   |-- reader.py
|   `-- summarize/
|       |-- cache.py
|       |-- schema.py
|       |-- summary_specs.py
|       |-- writer.py
|       `-- summaries/
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

## Contributor Docs

The contributor-oriented docs live under [`docs/`](docs/):

- [`docs/architecture.md`](docs/architecture.md): subsystem overview and extension contracts
- [`docs/summary-workflow.md`](docs/summary-workflow.md): cache generation, cache loading, and export/live runtime flow
- [`docs/adding-summaries.md`](docs/adding-summaries.md): how to add and register new summary tables
- [`docs/adding-dashboard-pages.md`](docs/adding-dashboard-pages.md): how to add pages, selectors, and shared dashboard components
- [`docs/plotting-summary-tables.md`](docs/plotting-summary-tables.md): how to turn summary tables into bar, line, and distribution charts
- [`docs/export_html_schema.md`](docs/export_html_schema.md): the offline export payload/runtime contract
- [`docs/export_html_contributor_guide.md`](docs/export_html_contributor_guide.md): how to extend export support for pages and selectors
- [`docs/adr/ADR-custom-export-runtime.md`](docs/adr/ADR-custom-export-runtime.md): why the project keeps the custom offline export runtime

If you are new to the codebase, start with `architecture.md`, then read the specific extension guide for the area you plan to change.

## Documentation Maintenance Checklist

When behavior changes, update the docs in the same change:

- New config key or config behavior: update this README and any affected workflow guide.
- New summary contract or registration pattern: update `docs/adding-summaries.md`.
- New page, selector, or export behavior: update `docs/adding-dashboard-pages.md`.
- New export payload/runtime behavior: update `docs/export_html_schema.md` and `docs/export_html_contributor_guide.md`.
- Architecture or runtime-flow changes: update `docs/architecture.md` or `docs/summary-workflow.md`.

Treat this README plus the `docs/` guides as the canonical contributor onboarding set.
