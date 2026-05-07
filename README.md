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

By default, `python run.py` means `--summarize --dashboard`: it will reuse summary caches when possible, rebuild them when needed, and then start the live dashboard on [http://localhost:5006](http://localhost:5006).

## Config Setup

The repo ships with `config.yaml` as a template. In practice, most people should:

1. Copy `config.yaml` to `local_config.yaml` or another machine-specific file.
2. Update the `runs` section to point at real ActivitySim output folders.
3. Update `skim.file`, `zones`, and `files` if your model layout differs from the defaults.
4. Run with `--config your_file.yaml`.

The minimum useful config is usually:

```yaml
summaries:
  root: artifacts/summary_cache

runs:
  - dir: path\to\run1
    label: Base
  - dir: path\to\run2
    label: Build

skim:
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

Important path rules:

- `summaries.root` is resolved relative to the config file if you give a relative path.
- The prepared cache is created automatically next to `summaries.root` as `prepared_cache/`.
- `runs[*].dir` should point at an ActivitySim output directory.
- `skim.file` may be absolute, or relative to each run directory.
- File entries under `files` can be bare stems like `final_trips` or explicit filenames like `final_trips.csv`.

## Config Reference

These are the sections most people need to touch:

| Section | Purpose |
|---|---|
| `summaries.root` | Where summary caches are stored |
| `summaries.weighting_modes` | Which cache variants to build: `weighted`, `unweighted`, or both |
| `runs` | Run directories, display labels, and optional per-run skim/weight overrides |
| `skim` | Global skim file and default matrix name |
| `zones` | MAZ/TAZ settings for skim joins and zone normalization |
| `files` | ActivitySim output file stems or filenames |
| `columns` | Column aliases when outputs use non-default names |
| `visualizer.dashboard_title` | Title used in the live dashboard and HTML export |
| `visualizer.dashboard_pages` | Ordered list of live pages/groups to show |
| `visualizer.run_colors` | Plot colors by run |
| `visualizer.export_html` | Export-only page selection and selector-state controls |
| `geography` | Optional district/county/zone grouping |
| `modes` | Optional mode ordering and grouped mode display |
| `person_types` | Optional display labels for `ptype` values |
| `student_types` | Optional school/university enrollment definitions for shadow pricing pages |

Weighting rules:

- If a run sets `hh_weight_col`, `person_weight_col`, or `trip_weight_col`, those are used.
- Otherwise, if a `sample_rate` column is available, weights are derived from it.
- Otherwise, weights default to `1`.

Legacy config notes:

- Prefer `summaries.*` over old `outputs.*` keys.
- Prefer `visualizer.dashboard_pages` over old top-level `dashboard_pages`.
- Prefer `visualizer.run_colors` over old top-level `run_colors`.

## Live Pages And Export Pages

`visualizer.dashboard_pages` controls the live dashboard only. `visualizer.export_html` controls what goes into the standalone HTML export.

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
visualizer:
  dashboard_pages:
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
visualizer:
  export_html:
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

- If `visualizer.dashboard_pages` is omitted, the app uses its built-in default page set.
- If `visualizer.export_html.pages` is omitted, export mirrors the live page set.
- Export selector requests accept `default`, `all`, or a list of explicit values.
- `visualizer.export_html.exclude_pages` and `exclude_groups` remove pages from export without changing the live dashboard.

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
| `python run.py --config local_config.yaml --prepare --summarize --dashboard` | Force the full prepare -> summarize -> dashboard chain in one run |
| `python run.py --config local_config.yaml --from-csvs` | Start the dashboard from existing summary caches only |
| `python run.py --config local_config.yaml --from-csvs --export-html output.html` | Build a standalone HTML export from existing summary caches |
| `python run.py --config local_config.yaml --summarize --write-csvs` | Rebuild summaries and write fresh cache files |
| `python run.py --config local_config.yaml --summarize --skip-summary-cache-write` | Build summaries for this run without writing cache updates |

Behavior details:

- `--from-csvs` is cache-only: it will not rebuild missing summaries.
- `--from-csvs path\to\cache1 path\to\cache2` lets you point directly at specific summary cache directories.
- `--dashboard` by itself is not valid unless you also use `--from-csvs`.
- During summarize, the app will reuse prepared cache when possible and rebuild from raw outputs only when needed.

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

Summary caches are written under `summaries.root`:

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

That means presentation-only config changes usually do not force summary rebuilds.

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

Use `null`, `None`, or an empty string in `--run-skim` to fall back to the global `skim.file`.

## Codebase Map

```text
activitysim_visualizer/
|-- run.py
|-- runtime_workflows.py
|-- runtime/
|   `-- config.py
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

## Contributor Docs

Contributor-oriented docs live under [`docs/`](docs/):

- [`docs/architecture.md`](docs/architecture.md)
- [`docs/summary-workflow.md`](docs/summary-workflow.md)
- [`docs/adding-summaries.md`](docs/adding-summaries.md)
- [`docs/adding-dashboard-pages.md`](docs/adding-dashboard-pages.md)
- [`docs/plotting-summary-tables.md`](docs/plotting-summary-tables.md)
- [`docs/export_html_schema.md`](docs/export_html_schema.md)
- [`docs/export_html_contributor_guide.md`](docs/export_html_contributor_guide.md)

If you are new to the codebase, start with `docs/architecture.md`, then `docs/summary-workflow.md`.

## Documentation Maintenance Checklist

When behavior changes, update docs in the same change:

- New config key or config behavior: update this README and any affected workflow guide.
- New summary contract or registration pattern: update `docs/adding-summaries.md`.
- New page, selector, or export behavior: update `docs/adding-dashboard-pages.md`.
- New export payload/runtime behavior: update `docs/export_html_schema.md` and `docs/export_html_contributor_guide.md`.
- Architecture or runtime-flow changes: update `docs/architecture.md` or `docs/summary-workflow.md`.
