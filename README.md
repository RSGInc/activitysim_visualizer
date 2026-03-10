# ActivitySim Visualizer

An interactive, browser-based dashboard for exploring and comparing [ActivitySim](https://activitysim.github.io/) model outputs. It supports side-by-side comparison of multiple model runs, weighted and unweighted summaries, and optional export to a self-contained HTML file.

---

## Setup

### Install with uv (recommended)

Insure [uv](https://docs.astral.sh/uv/) is installed on your machine and then type

```bash
uv sync --locked
```
If you get a failed to install error caused by "failed to hardlink file", try adding "--link-mode=copy":

```bash
uv sync --locked --link-mode=copy
```

Then activate the newly created environment:

```bash
.\.venv\Scripts\activate
```

You should see (activitysim-visualizer) show at the start of your command prompt line
---

## Configuration

Copy `config.yaml` and edit it for your model deployment. Key sections:

| Section | Required | Description |
|---|---|---|
| `name` / `dashboard_title` | Yes | Display names for the run and dashboard header |
| `files` | Yes | Stems (or full filenames) of ActivitySim output files |
| `columns` | Yes | Column name overrides if your outputs use non-standard names |
| `zones` | Yes | Set `use_maz: false` for TAZ-only models; configure MAZ/TAZ columns otherwise |
| `runs` | Yes | List of run directories with labels and optional per-run skim/weight overrides |
| `skim` | No | Global OMX skim file path and matrix name for distance/time summaries |
| `person_types` | No | Display labels for `ptype` values |
| `geography` | No | Enable district/county-level breakdowns using a land-use column |
| `modes` | No | Control display order and grouping of travel modes in charts |
| `run_colors` | No | Hex colors for each run (cycles if more runs than colors) |

### Specifying runs

Runs are listed in the `runs` section of `config.yaml`:

```yaml
runs:
  - dir:   /path/to/run1
    label: Base
    skim_file: null          # uses global skim default
    hh_weight_col: null      # uses auto-detected sample_rate weighting
    person_weight_col: null
    trip_weight_col: null

  - dir:   /path/to/run2
    label: Build
```

If no weight columns are specified and no `sample_rate` column is found, all weights default to 1.

---

## Running the Dashboard

### Basic usage (runs from config.yaml)

```bash
python run.py --config config.yaml
```

Then open [http://localhost:5006](http://localhost:5006) in your browser.

### Specify runs on the command line

```bash
python run.py --run /path/to/run1 "Base" --run /path/to/run2 "Build"
```

### With per-run skim overrides

```bash
python run.py \
  --run /path/to/run1 "Base" \
  --run /path/to/run2 "Build" \
  --run-skim /path/to/run1/skims.omx /path/to/run2/skims.omx
```

### Write calibration CSVs

```bash
# Launch dashboard and write CSVs
python run.py --write-csvs

# Write CSVs only (no dashboard)
python run.py --write-csvs --no-dashboard
```

### Export to static HTML

```bash
python run.py --export-html output.html
```

### Additional options

| Flag | Default | Description |
|---|---|---|
| `--config`, `-c` | `config.yaml` | Path to configuration file |
| `--port` | `5006` | Port to serve the dashboard on |
| `--no-show` | on | Disable automatic opening of the dashboard in a browser |
| `--from-csvs [DIR ...]` | — | Load pre-computed summary CSVs instead of raw run outputs |

---

## What the Tool Does

The ActivitySim Visualizer reads raw ActivitySim output files (households, persons, tours, trips, joint tour participants, and land use) and produces an interactive multi-tab dashboard for model validation and scenario comparison.

### Dashboard Pages

| Tab | Content |
|---|---|
| **Overview** | Household and person demographics: HH size, auto ownership, workers per HH, person type distribution |
| **Long-Term** | Long-term choice outcomes: workplace and school location distances, free parking at work |
| **Tour Summary** | Tour rates by person type and purpose; daily activity patterns |
| **Joint Tours** | Joint tour frequency and party composition |
| **Destination** | Tour destination choice: distance distributions by purpose |
| **Tour TOD** | Tour time-of-day: departure and arrival period distributions |
| **Tour Mode** | Tour mode share by purpose, with optional mode grouping |
| **Stop Frequency** | Stop frequency by tour purpose and direction |
| **Stop Location** | Stop location choice: distance-to-primary-destination distributions |
| **Stop Timing** | Stop departure and arrival time distributions |
| **Trip Mode** | Trip-level mode share by purpose |

All charts support toggling between **weighted** (using `finalweight`) and **unweighted** (raw count) views, and between **percent** and **count** display modes.

### Weighting

Weights are computed automatically from the `sample_rate` column in the households file (`finalweight = 1 / sample_rate`). Explicit weight columns (`hh_weight_col`, `person_weight_col`, `trip_weight_col`) can be specified per run in the config. If neither is available, all weights are set to 1.

---

## Repository Structure

```
activitysim_visualizer/
├── run.py              # CLI entry point and argument parsing
├── config.yaml         # Example configuration file
├── pyproject.toml      # Package metadata and dependencies
├── summarize/          # Data reading and summarization logic
│   ├── reader.py       # Config loading, file reading, weight computation
│   ├── demographics.py # HH/person demographic summaries
│   ├── mandatory.py    # Workplace/school location summaries
│   ├── tours.py        # Tour-level summaries
│   ├── tour_mode.py    # Tour mode share summaries
│   ├── tour_tod.py     # Tour time-of-day summaries
│   ├── stops.py        # Stop frequency and location summaries
│   ├── trips.py        # Trip-level summaries
│   ├── totals.py       # Aggregate count summaries
│   └── writer.py       # CSV export utilities
└── dashboard/          # Panel-based UI
    ├── app.py          # Dashboard assembly and layout
    ├── components.py   # Shared chart components and helpers
    └── pages/          # One module per dashboard tab
        ├── overview.py
        ├── long_term.py
        ├── tour_summary.py
        ├── joint_tours.py
        ├── destination.py
        ├── tour_tod.py
        ├── tour_mode.py
        ├── stop_freq.py
        ├── stop_location.py
        ├── stop_timing.py
        └── trip_mode.py
```

---

## Developer Guide: Adding New Summaries and Pages

### 1. Add a new summary function

Summary functions live in the `summarize/` package. Each function receives a `RunData` and `Config` object and returns a Polars `DataFrame`. Add your function to the most relevant existing module, or create a new module for a distinct topic area.

**Example — adding a function to `summarize/trips.py`:**

```python
import polars as pl
from .reader import RunData, Config

def trip_distance_by_mode(rd: RunData, config: Config) -> pl.DataFrame:
    """Trip distance distribution by mode. Columns: trip_mode, distance_bin, freq."""
    return (
        rd.trips
        .filter(pl.col("trip_mode").is_not_null())
        .with_columns(
            (pl.col("distance") / 5).cast(pl.Int32).mul(5).alias("distance_bin")
        )
        .group_by(["trip_mode", "distance_bin"])
        .agg(pl.col("finalweight").sum().alias("freq"))
        .sort(["trip_mode", "distance_bin"])
    )
```

Key conventions:
- Always use `pl.col("finalweight").sum()` (not row counts) so that weighted and unweighted modes work correctly via the `finalweight` column on `RunData`.
- Return a plain `pl.DataFrame` — no Panel or Plotly objects.
- Guard against missing columns with an early-return empty `DataFrame` matching the expected schema (see existing functions for the pattern).

---

### 2. Add a new dashboard page

Each tab in the dashboard is a module in `dashboard/pages/`. A page module must expose a single `build` function with this signature:

```python
def build(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    ...
```

**Step-by-step:**

**a. Create `dashboard/pages/my_page.py`**

```python
"""My new page."""
from __future__ import annotations
import panel as pn
import polars as pl
from dashboard.components import bar_chart
from summarize.reader import RunData, Config
from summarize import trips as trip_sums


def build(runs: list[tuple[str, RunData]], config: Config) -> pn.viewable.Viewable:
    if not runs:
        return pn.pane.Markdown("No runs loaded.")

    # Compute summaries for each run
    data = [(label, trip_sums.trip_distance_by_mode(rd, config)) for label, rd in runs]

    # Build a chart using a shared helper from dashboard/components.py
    chart = bar_chart(data, x_col="distance_bin", y_col="freq", title="Trip Distance by Mode")

    return pn.Column(chart)
```

Available chart helpers in `dashboard/components.py`:
- `bar_chart(data_list, x_col, y_col, title, ...)` — grouped bar chart comparing runs
- `line_chart(data_list, x_col, y_col, title, ...)` — multi-run line chart
- `kpi_box(label, values, colors)` — styled metric card

**b. Register the page in `dashboard/app.py`**

Add the import near the top of the file alongside the other page imports:

```python
from dashboard.pages import (
    overview, long_term, tour_summary, joint_tours, destination,
    tour_tod, tour_mode, stop_freq, stop_location, stop_timing, trip_mode,
    my_page,  # <-- add this
)
```

Then add a tab entry inside the `make_tabs` function in `build_dashboard`:

```python
return pn.Tabs(
    ("Overview",         overview.build(cur_runs, config)),
    # ... existing tabs ...
    ("Trip Mode",        trip_mode.build(cur_runs, config)),
    ("My New Page",      my_page.build(cur_runs, config)),  # <-- add this
    dynamic=dynamic,
)
```

The tab label (first element of the tuple) is the text shown on the tab in the browser.

---

### Tips

- **Reactive widgets**: If your page needs dropdowns or filters, use `pn.widgets` and `@pn.depends` (or `pn.bind`) to wire them to chart functions, following the pattern in `dashboard/pages/tour_summary.py`.
- **Weighted vs. unweighted**: The dashboard automatically passes either the weighted or unweighted `RunData` to `build()` depending on the toggle — you do not need to handle this yourself.
- **Percent vs. count**: Call `from dashboard.components import set_percent_mode` and check `_DISPLAY_PERCENT_MODE` if your chart needs to respond to the Percent/Count toggle, or pass `pct_col` to `bar_chart` for automatic normalization.
- **Column safety**: Always check that expected columns exist before using them, returning an empty DataFrame with the right schema if they are absent.
