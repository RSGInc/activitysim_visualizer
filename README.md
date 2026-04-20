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
# Build or refresh summary caches from raw ActivitySim outputs
python run.py --write-csvs --no-dashboard

# Serve the dashboard from prebuilt summary caches
python run.py --from-csvs

# Export a cache-backed dashboard to standalone HTML
python run.py --from-csvs --export-html output.html
```

The live dashboard runs at [http://localhost:5006](http://localhost:5006) by default.

## Configuration Highlights

Copy `config.yaml` and edit it for your deployment. The most important sections are:

| Section | Purpose |
|---|---|
| `runs` | Run directories, labels, and optional per-run skim/weight overrides |
| `summaries` | Cache root and enabled weighting modes |
| `visualizer.dashboard_title` | Dashboard title shown in the UI and export |
| `visualizer.dashboard_pages` | Ordered list of live page ids |
| `visualizer.export_html` | Export-only dashboard controls and page selector requests |
| `columns` | Raw-column aliases when ActivitySim outputs differ from expected names |
| `skim` | Global skim file and matrix defaults |
| `geography` | Optional geography breakdown configuration |
| `modes` | Display ordering and grouping for travel modes |

Rules worth knowing up front:

- `visualizer.dashboard_pages` controls live page inclusion and order only.
- `visualizer.export_html.pages` controls export page inclusion and export selector values.
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

If no explicit weight columns are configured and no `sample_rate` column is present, weights default to `1`.

## Main Workflows

This repo supports three distinct workflows:

1. Raw outputs -> summary cache
2. Summary cache -> live dashboard
3. Summary cache plus optional raw runs -> standalone HTML export

Summary caches are written under `summaries.root` with one directory per run:

```text
<summary_root>/
  <run_key>/
    manifest.json
    weighted/
    unweighted/
```

The cache manifest records summary ids, weighting modes, a summary-config digest, and a run fingerprint so the runtime can tell whether an existing cache is still safe to reuse.

## Codebase Map

```text
activitysim_visualizer/
|-- run.py
|-- runtime_workflows.py
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
|   |-- export_html.py
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

If you are new to the codebase, start with `architecture.md`, then read the specific extension guide for the area you plan to change.

## Documentation Maintenance Checklist

When behavior changes, update the docs in the same change:

- New config key or config behavior: update this README and any affected workflow guide.
- New summary contract or registration pattern: update `docs/adding-summaries.md`.
- New page, selector, or export behavior: update `docs/adding-dashboard-pages.md`.
- Architecture or runtime-flow changes: update `docs/architecture.md` or `docs/summary-workflow.md`.

Treat this README plus the `docs/` guides as the canonical contributor onboarding set.
