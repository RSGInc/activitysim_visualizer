# ActivitySim Visualizer Marimo Alt

An interactive, browser-based dashboard for exploring and comparing [ActivitySim](https://activitysim.github.io/) model outputs. This project is a marimo-based alternative to the Panel dashboard and is designed around the same comparison workflow: multiple runs, weighted and unweighted summaries, percent or count views, and page-level controls for filtering charts.

---

## Setup

### Install with `uv` (recommended)

Ensure [uv](https://docs.astral.sh/uv/) is installed, then from the project directory run:

```powershell
cd c:\Users\wesley.darling\projects\activitysim_visualizer\marimo_visualizer
uv sync --locked
```

If you hit a Windows hardlink issue during install, retry with:

```powershell
uv sync --locked --link-mode=copy
```

This creates the local virtual environment in `.venv`.

---

## Configuration

Edit [config.yaml](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/config.yaml) for your model deployment. Key sections:

| Section | Required | Description |
|---|---|---|
| `name` / `dashboard_title` | Yes | Display names for the run set and dashboard header |
| `files` | Yes | Stems or full filenames of ActivitySim output files |
| `columns` | Yes | Column-name overrides if your outputs differ from the default schema |
| `zones` | Yes | Controls MAZ/TAZ behavior and join columns for skim lookups |
| `runs` | Yes | List of run directories with labels and optional per-run skim/weight overrides |
| `skim` | No | Global OMX skim path and matrix name for distance-based summaries |
| `person_types` | No | Display labels for `ptype` values |
| `geography` | No | Enable geography summaries using a land-use column and mapping |
| `modes` | No | Display order and grouping of tour/trip modes |
| `run_colors` | No | Colors used consistently across plots and KPI cards |

### Specifying runs

Runs are listed in the `runs` section of `config.yaml`:

```yaml
runs:
  - dir: C:\path\to\run1
    label: Base
    skim_file: null
    hh_weight_col: null
    person_weight_col: null
    trip_weight_col: null

  - dir: C:\path\to\run2
    label: Build
```

If no explicit weight columns are provided and no `sample_rate` column is found, weights default to `1.0`.

### Minimal example

```yaml
name: "Example"
dashboard_title: "ActivitySim Comparison Visualizer"

runs:
  - dir: C:\path\to\run1
    label: Base
  - dir: C:\path\to\run2
    label: Build

skim:
  file: C:\path\to\skims.omx
  matrix: DIST

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

columns:
  ptype: ptype
  hhsize: hhsize
  auto_ownership: auto_ownership
  num_workers: num_workers
  num_adults: num_adults
```

### Skims

Skims are optional but strongly recommended for distance-based pages.

```yaml
skim:
  file: C:\path\to\skims.omx
  matrix: DIST
```

Notes:
- `skim.file` can be absolute or relative to the run directory.
- `runs[*].skim_file` overrides the global skim on a per-run basis.
- If no skim is available, the app still runs, but distance-based summaries may be empty or zeroed.

Pages most affected by missing skims:
- `Long-Term`
- `Destination`
- `Stop Location`
- `Overview` PMT/VMT metrics

### Geography settings

```yaml
geography:
  enabled: true
  landuse_col: COUNTY
  mapping:
    1: County A
    2: County B
```

If `geography.enabled: false`, the app still runs and geography-specific summaries are skipped or fall back to non-geographic behavior.

### Mode settings

```yaml
modes:
  order:
    - DRIVEALONE
    - SHARED2
    - WALK
    - BIKE
  groups:
    Auto: [DRIVEALONE, SHARED2]
    Non-Motorized: [WALK, BIKE]
```

This affects:
- Tour Mode ordering
- Trip Mode ordering
- grouped mode profiles
- auto-mode detection used in aggregate vehicle metrics

---

## Running the Dashboard

### Basic usage

Interactive editor mode:

```powershell
cd c:\Users\wesley.darling\projects\activitysim_visualizer\marimo_visualizer
uv run marimo edit app.py
```

Run mode:

```powershell
cd c:\Users\wesley.darling\projects\activitysim_visualizer\marimo_visualizer
uv run marimo run app.py
```

### Panel-style launcher

The marimo alt now includes [run.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/run.py), which is analogous to the Panel visualizer launcher.

Use runs defined in `config.yaml`:

```powershell
cd c:\Users\wesley.darling\projects\activitysim_visualizer\marimo_visualizer
uv run python run.py --config config.yaml
```

Override runs on the command line:

```powershell
uv run python run.py `
  --run C:\path\to\run1 Base `
  --run C:\path\to\run2 Build
```

Per-run skim overrides:

```powershell
uv run python run.py `
  --run C:\path\to\run1 Base `
  --run C:\path\to\run2 Build `
  --run-skim C:\path\to\run1\skims.omx C:\path\to\run2\skims.omx
```

Write summary CSVs and still launch the dashboard:

```powershell
uv run python run.py --write-csvs
```

Write summary CSVs only:

```powershell
uv run python run.py --write-csvs --no-dashboard
```

Export the app to static HTML:

```powershell
uv run python run.py --export-html output.html
```

Useful CLI options:

| Flag | Default | Description |
|---|---|---|
| `--config`, `-c` | `config.yaml` | Base configuration file |
| `--run DIR LABEL` | off | Add or override runs from the command line |
| `--run-skim` | off | Per-run skim overrides matching the order of `--run` |
| `--write-csvs` | off | Write summary CSVs to each run directory |
| `--no-dashboard` | off | Skip the dashboard; requires `--write-csvs` |
| `--export-html PATH` | off | Export the marimo app as HTML and exit |
| `--include-code` | off | Include notebook code in exported HTML |
| `--host` | `127.0.0.1` | Host for `marimo run` |
| `--port` | `5006` | Port for `marimo run` |
| `--headless` | off | Do not open a browser automatically |
| `--watch` | off | Watch the app file for changes and reload |

### Config path used by the app

The app currently uses the default config path defined in [app.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/app.py):

```python
default_config_path = Path(__file__).resolve().parent / "config.yaml"
```

That means the app reads:

`marimo_visualizer/config.yaml`

To load your own data:
1. Edit `config.yaml`
2. Update `runs[*].dir` to real ActivitySim output folders
3. Update skim, geography, columns, and modes if needed
4. Restart marimo after changing config

---

## What the Tool Does

The marimo visualizer reads raw ActivitySim output files and prepares weighted and unweighted run variants for side-by-side comparison. It loads households, persons, tours, trips, joint tour participants, and land use, computes derived columns, joins skim-based distances when available, and renders a multi-page dashboard.

### Dashboard Pages

| Page | Content |
|---|---|
| **Overview** | Population, households, tours, trips, PMT/VMT, person type and HH size distributions |
| **Long-Term** | Auto ownership, TLFDs, telecommuting, geography flows, mandatory tour lengths |
| **Tour Summary** | Daily activity pattern, mandatory tour frequency, individual non-mandatory tours |
| **Joint Tours** | Joint tour frequency, composition, party size, and HH-size split |
| **Destination** | Non-mandatory tour distance distributions and average distances by purpose |
| **Tour TOD** | Tour departure, arrival, and duration profiles |
| **Tour Mode** | Tour mode profiles by purpose |
| **Stop Frequency** | Outbound, inbound, and total stop frequency plus stop-purpose mix |
| **Stop Location** | Stop out-of-direction distance distribution |
| **Stop Timing** | Stop and trip departure time distributions |
| **Trip Mode** | Trip mode share by tour purpose and tour mode |

All pages respect:
- `Weighted` vs `Unweighted`
- `Percent` vs `Count`
- page-local dropdown filters where applicable

### Weighting

Weights are computed during preparation:
- If explicit weight columns are configured, those are used.
- Otherwise `sample_rate` is used where available via `finalweight = 1 / sample_rate`.
- If neither is available, weights default to `1.0`.

The app keeps both:
- weighted prepared runs
- unweighted prepared runs with `finalweight = 1.0`

The global `Weighting` control in [app.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/app.py) chooses which prepared run set is passed into the page renderer.

---

## Repository Structure

```text
marimo_visualizer/
|-- app.py                 # marimo app shell and top-level reactive cells
|-- config.yaml            # Example configuration file
|-- pyproject.toml         # Project metadata and dependencies
|-- run.py                 # CLI launcher for dashboard, CSV writing, and HTML export
|-- uv.lock                # Locked dependency set
|-- README.md              # User and developer documentation
`-- viz/
    |-- __init__.py        # Public exports for app and helpers
    |-- charts.py          # Shared Plotly chart builders and KPI card HTML
    |-- config.py          # YAML config loading and normalization
    |-- filters.py         # Shared option builders for dropdown controls
    |-- io.py              # Raw file and skim loading
    |-- models.py          # Typed config/run dataclasses
    |-- pages.py           # Page renderers and page-control builders
    |-- prepare.py         # Weighting, joins, derived columns, prepared runs
    |-- tables.py          # Shared marimo table helpers and percent-diff tables
    |-- writer.py          # Summary CSV export helpers
    `-- summaries/
        |-- demographics.py
        |-- mandatory.py
        |-- stops.py
        |-- totals.py
        |-- tour_mode.py
        |-- tour_tod.py
        |-- tours.py
        `-- trips.py
```

---

## Developer Guide: Adding New Summaries and Pages

The marimo app is intentionally split into:
- pure data/summary logic in `viz/summaries/`
- pure chart/table helpers in `viz/charts.py` and `viz/tables.py`
- UI composition and page routing in `viz/pages.py`
- top-level marimo reactivity in `app.py`

That separation matters. Summary modules should stay marimo-free. Page renderers should stay thin and compose summaries plus shared chart helpers.

### 1. Add a new summary function

Summary functions live in `viz/summaries/`. Each function receives a `RunData` and, where needed, a `Config`, and returns a Polars `DataFrame`.

Example: add a function to `viz/summaries/trips.py`

```python
import polars as pl

from ..models import Config, RunData


def trip_distance_by_mode(rd: RunData, config: Config) -> pl.DataFrame:
    """Trip distance distribution by mode."""
    del config

    if not {"trip_mode", "od_dist", "finalweight"}.issubset(rd.trips.columns):
        return pl.DataFrame({"trip_mode": [], "distance_bin": [], "freq": []})

    return (
        rd.trips
        .filter(pl.col("trip_mode").is_not_null() & pl.col("od_dist").is_not_null())
        .with_columns(
            (pl.col("od_dist") / 5).floor().cast(pl.Int32).mul(5).alias("distance_bin")
        )
        .group_by(["trip_mode", "distance_bin"])
        .agg(pl.col("finalweight").sum().alias("freq"))
        .sort(["trip_mode", "distance_bin"])
    )
```

Key conventions:
- Always aggregate with `pl.col("finalweight").sum()` unless you have a very specific reason not to.
- Return a plain `pl.DataFrame`; do not create marimo or Plotly objects in summaries.
- Guard missing columns early and return an empty frame with the expected schema.
- Keep page-specific formatting out of the summary layer.

### 2. Add a new dashboard page

Pages currently live in [viz/pages.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/viz/pages.py). Each page consists of:
- an optional page-control builder
- a renderer function
- registration in the page-control and page-renderer maps
- an entry in `PAGE_NAMES` in [app.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/app.py)

#### a. Create the renderer

Example skeleton:

```python
def render_trip_distance(
    runs: Runs,
    config: Config,
    as_percent: bool,
    run_colors: Sequence[str],
    mo: Any,
    controls: dict[str, Any] | None = None,
    control_values: dict[str, Any] | None = None,
):
    data = [(label, trips.trip_distance_by_mode(rd, config)) for label, rd in runs]

    fig = bar_chart(
        data,
        x_col="distance_bin",
        y_col="freq",
        title="Trip Distance by Mode",
        xaxis_title="Distance Bin",
        yaxis_title="Trips",
        as_percent=as_percent,
        run_colors=run_colors,
    )

    return mo.vstack(
        [
            mo.md("## Trip Distance"),
            _plot(mo, fig),
        ],
        gap=1.0,
    )
```

Available shared helpers:
- `bar_chart(...)` in [viz/charts.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/viz/charts.py)
- `density_chart(...)` in [viz/charts.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/viz/charts.py)
- `line_chart(...)` in [viz/charts.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/viz/charts.py)
- `make_table(...)` and `make_run_tables(...)` in [viz/tables.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/viz/tables.py)

#### b. Add page-local controls if needed

In marimo, page-local controls are created outside the renderer using `build_page_controls(...)`. This is important for reactivity.

Example control builder:

```python
def _controls_trip_distance(runs: Runs, config: Config, mo: Any) -> dict[str, Any]:
    del config
    return {
        "purpose": _dropdown_widget(
            mo,
            "Purpose",
            purpose_options_from_trips(runs, include_total=True),
        )
    }
```

Inside the renderer, read the selected value through `control_values`:

```python
purpose_sel = _control_widget(controls, "purpose")
selected_purpose = _control_value(control_values, "purpose", "Total")
```

Then include the widget in the layout:

```python
_maybe_control_row(mo, [purpose_sel])
```

#### c. Register the page

In [viz/pages.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/viz/pages.py):

1. Add the control builder to `PAGE_CONTROL_BUILDERS` if needed
2. Add the renderer to `PAGE_RENDERERS`

In [app.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/app.py):

3. Add the page label to `PAGE_NAMES`

Example:

```python
PAGE_CONTROL_BUILDERS["Trip Distance"] = _controls_trip_distance
PAGE_RENDERERS["Trip Distance"] = render_trip_distance
```

And in `app.py`:

```python
PAGE_NAMES = [
    "Overview",
    ...
    "Trip Distance",
]
```

### 3. Understand the reactive model

The marimo app is not structured like the Panel app.

Current flow:
1. `app.py` creates global controls for weighting, values, and active page.
2. `app.py` loads and prepares weighted and unweighted run bundles.
3. `app.py` calls `build_page_controls(...)` for the active page.
4. `app.py` reads the reactive values from the page-control container.
5. `app.py` calls `render_page(...)` with `runs`, `config`, `as_percent`, `run_colors`, `controls`, and `control_values`.
6. `viz/pages.py` renders the page using pure summary/chart/table helpers.

Important rule:
- Do not create a marimo widget and read its `.value` in the same render function. Build widgets in the dedicated control cell path and pass their values into the renderer.

The app currently uses `mo.ui.dictionary(...)` for page controls because it gives proper reactive execution for a dynamic set of widgets.

### 4. Preserve weighted/unweighted and percent/count behavior

When adding a page:
- assume `runs` already contains either the weighted or unweighted prepared runs
- pass `as_percent` directly into shared chart helpers
- do not recompute weighting inside the page renderer

Examples:
- `bar_chart(..., as_percent=as_percent, run_colors=run_colors)`
- `density_chart(..., as_percent=as_percent, run_colors=run_colors, normalize=True)`

Note:
- Some density-style pages intentionally preserve Panel behavior where `normalize=True` still normalizes even if the global values toggle is set to `Count`.

### 5. Column safety and ambiguous behaviors

Follow the existing summary-layer pattern:
- check for required columns first
- return empty but schema-compatible frames on missing inputs
- preserve categorical-to-string normalization before joins when needed

This matters because real ActivitySim outputs vary:
- some runs have categorical columns
- some runs have no skims
- some runs have geography disabled
- some files are CSV, others Parquet

### 6. When to add a new module

Add to an existing summary module when the logic clearly belongs there.

Create a new module when:
- the summary family is large enough to stand on its own
- the new page needs several related summary functions
- mixing it into an existing file would make the module harder to navigate

If you create a new module under `viz/summaries/`, export it through [viz/summaries/__init__.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/viz/summaries/__init__.py).

---

## Troubleshooting

### The app opens but only shows a load error

Usually one of these is true:
- `config.yaml` points at the wrong run directory
- one or more required output files are missing
- the skim path is wrong
- a configured column name does not exist in the outputs

### Distance-based pages look empty

Usually:
- no skim is configured
- the skim file path is wrong
- the skim matrix name is wrong
- zone IDs do not match the configured MAZ/TAZ setup

### Geography controls or tables are missing

Check:
- `geography.enabled: true`
- `geography.landuse_col` exists in `final_land_use`

### A page dropdown does not update a plot

Page-local controls are wired through the marimo app shell. If you change page-control code, fully restart the marimo process before retesting.

### Marimo warns about `C:\Users\<user>\.config\marimo`

There is currently a non-blocking local marimo config warning on this machine. It does not prevent the app from running.

---

## Relevant Files

- [app.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/app.py)
- [config.yaml](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/config.yaml)
- [viz/config.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/viz/config.py)
- [viz/io.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/viz/io.py)
- [viz/prepare.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/viz/prepare.py)
- [viz/pages.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/viz/pages.py)
- [viz/charts.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/viz/charts.py)
- [viz/tables.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/marimo_visualizer/viz/tables.py)

