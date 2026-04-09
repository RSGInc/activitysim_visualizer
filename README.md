# ActivitySim Visualizer

An interactive, browser-based dashboard for exploring and comparing [ActivitySim](https://activitysim.github.io/) model outputs. It supports side-by-side comparison of multiple model runs, weighted and unweighted summaries, and optional export to a self-contained HTML file.

---

## Setup

### Install with uv (recommended)

Ensure [uv](https://docs.astral.sh/uv/) is installed on your machine and then type

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
| `dashboard_pages` | No | Ordered list of page IDs to include in live and export modes |
| `files` | Yes | Stems (or full filenames) of ActivitySim output files |
| `columns` | Yes | Column name overrides if your outputs use non-standard names |
| `zones` | Yes | Set `use_maz: false` for TAZ-only models; configure MAZ/TAZ columns otherwise |
| `runs` | Yes | List of run directories with labels and optional per-run skim/weight overrides |
| `skim` | No | Global OMX skim file path and matrix name for distance/time summaries |
| `outputs` | No | Summary cache root directory and enabled weighting modes |
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

### Selecting dashboard pages

Use top-level `dashboard_pages` to control which pages appear and in what order:

```yaml
dashboard_pages:
  - overview
  - long_term
  - tour_summary
  - destination
  - trip_mode
```

Rules:
- The list controls page order in both the live dashboard and `--export-html`.
- Each entry must be a stable page ID, not the visible tab title.
- Unknown or duplicate page IDs fail during config load.
- Omit raw-data demo pages from this list unless you intentionally want the dashboard to request raw runs.

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
# Refresh the configured summary cache, then launch the dashboard
python run.py --write-csvs

# Write cache files only (no dashboard)
python run.py --write-csvs --no-dashboard
```

Summary caches are written under `outputs.summary_root` using this layout:

```text
<summary_root>/
  <run_key>/
    manifest.json
    weighted/
    unweighted/
```

### Export to static HTML

```bash
python run.py --export-html output.html
```

### Recommended workflow patterns

```bash
# Build or refresh summary caches from raw ActivitySim outputs
python run.py --write-csvs --no-dashboard

# Serve the dashboard from prebuilt summary caches only
python run.py --from-csvs

# Export a cache-backed dashboard without rereading raw outputs
python run.py --from-csvs --export-html output.html
```

Notes:
- The summary workflow reads raw ActivitySim outputs and writes summary caches.
- The dashboard and export workflows consume precomputed `summary_runs` and do not generate missing summaries.
- Raw run data is only passed into the dashboard when an enabled page explicitly requires it.
- Runtime logs are written to both the console and `<summary_root>/../logs/activitysim_visualizer.log`.

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
├── run.py              # CLI entry point that delegates to runtime workflows
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

Each tab in the dashboard is a module in `dashboard/pages/`. The supported extension point is now the page module itself: one module owns the page helpers, the persistent `DashboardPage` controller, and the exported `PAGE` definition used by both live mode and HTML export.

**Step-by-step:**

**a. Create `dashboard/pages/my_page.py`**

```python
"""My new page."""
from __future__ import annotations

import panel as pn

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from summarize.reader import Config


class MyPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("My New Page", state, config)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## My New Page"),
            self._body,
            sizing_mode="stretch_width",
        )

    def _refresh(self) -> None:
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        trip_mode_profile = self.require_summary("trip_mode_profile")
        if trip_mode_profile is None:
            self._body.objects = [
                self.data_not_available_card(
                    detail="This page only renders from precomputed summary tables.",
                    missing_items=["trip_mode_profile"],
                )
            ]
            return

        self._body.objects = [
            bar_chart(
                trip_mode_profile,
                x_col="trip_mode",
                y_col="freq",
                title="Trip Mode Profile",
            )
        ]


PAGE = DashboardPageDefinition(
    page_id="my_page",
    title="My New Page",
    order=120,
    controller_cls=MyPage,
    required_summary_ids=("trip_mode_profile",),
)
```

Available chart helpers in `dashboard/components.py`:
- `bar_chart(data_list, x_col, y_col, title, ...)` — grouped bar chart comparing runs
- `line_chart(data_list, x_col, y_col, title, ...)` — multi-run line chart
- `kpi_box(label, values, colors)` — styled metric card

**b. Add the page to config**

Include the page ID in top-level `dashboard_pages` wherever you want it to appear:

```yaml
dashboard_pages:
  - overview
  - my_page
  - trip_mode
```

That is the only page-registration step needed.

**c. Add selector metadata if the page has page-local export controls**

If a page-level widget should work offline in `--export-html`, declare it in the page module's `PAGE.selectors`:

```python
from dashboard.page_definitions import PageSelectorDefinition

PAGE = DashboardPageDefinition(
    page_id="tour_summary",
    title="Tour Summary",
    order=30,
    controller_cls=TourSummaryPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="person_type",
            widget_attr="ptype_sel",
            label="Person Type",
        ),
    ),
)
```

If the selector should be configurable from YAML, document its key under `outputs.export_html.pages.<page_id>.<selector_id>`.

**d. Add tests**

- Add or extend live-dashboard tests if the page has important state or caching behavior.
- Add or extend [tests/test_export_html.py](/c:/Users/wesley.darling/projects/activitysim_visualizer/tests/test_export_html.py) if the page participates in export, especially when selectors are involved.

### Compatibility note

The page-module API is now the only supported dashboard extension API. Each page module should define its persistent `DashboardPage` controller and export a `PAGE = DashboardPageDefinition(...)`; there is no separate module-level `build(runs, config)` path to maintain.

---

### Tips

- **Reactive widgets**: For persistent pages, create `pn.widgets` on the controller instance and call `_watch_widget(...)` so the page refreshes without losing widget state.
- **Summary-backed pages**: Prefer `require_summary(...)` and `require_summaries(...)` so pages degrade cleanly instead of rebuilding data inside the dashboard.
- **Raw-data pages**: Only use `require_raw_runs(...)` on pages whose `PAGE.raw_data_mode` is `"optional"` or `"required"`.
- **Required summaries**: Declare every summary dependency in `PAGE.required_summary_ids` so registry validation, live mode, and export mode all share the same contract.
- **Unavailable states**: Use `self.data_not_available_card(...)` when required summaries or raw runs are missing so the UI and logs stay aligned.
- **Percent vs. count**: Call `from dashboard.components import set_percent_mode` and check `_DISPLAY_PERCENT_MODE` if your chart needs to respond to the Percent/Count toggle, or pass `pct_col` to `bar_chart` for automatic normalization.
- **Export-safe layouts**: Stick to the Panel view types already supported by the HTML export path, such as `pn.Column`, `pn.Row`, `pn.Card`, `pn.Tabs`, `pn.pane.Markdown`, `pn.pane.HTML`, `pn.widgets.Select`, `pn.widgets.RadioButtonGroup`, `pn.widgets.Tabulator`, and `pn.pane.Plotly`.
- **Column safety**: Always check that expected columns exist before using them, returning an empty DataFrame with the right schema if they are absent.
