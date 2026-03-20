# Panel Visualizer Architecture

## Concise summary

The current visualizer is a thin Panel UI over a Polars-based summary pipeline. `run.py` loads `config.yaml`, reads each ActivitySim run into a `RunData` object with `summarize.reader.read_run()`, enriches it with `prepare_data()`, and passes a list of `(label, RunData)` tuples into `dashboard.app.build_dashboard()`.

The dashboard shell lives in [`dashboard/app.py`](/c:/Users/wesley.darling/projects/activitysim_visualizer/dashboard/app.py). It owns template setup, sidebar controls, run colors, and top-level tab construction. Each tab is a small page module under [`dashboard/pages/`](/c:/Users/wesley.darling/projects/activitysim_visualizer/dashboard/pages) that computes page-specific summary `pl.DataFrame`s once, then exposes Panel widget callbacks that filter or reshape those summaries into charts and tables.

The data layer is shared and reusable. Most behavioral complexity is in [`summarize/reader.py`](/c:/Users/wesley.darling/projects/activitysim_visualizer/summarize/reader.py) and the `summarize/*.py` summary functions, not in the page modules themselves.

## Runtime pipeline

1. Load config from [`config.yaml`](/c:/Users/wesley.darling/projects/activitysim_visualizer/config.yaml).
2. Resolve run directories, labels, optional skim overrides, and optional explicit weight columns.
3. Read raw ActivitySim tables:
   - households
   - persons
   - tours
   - trips
   - joint tour participants
   - land use
   - optional OMX skim matrix
4. Compute `finalweight` for households, persons, tours, and trips.
5. Enrich tables with derived columns used by summaries:
   - HHVEH, HHSIZE, WORKERS, ADULTS
   - HGEO, WGEO
   - home/work/school distances
   - AUTOSUFF
   - stop counts
   - NUMBER_HH
   - OTAZ, DTAZ, SKIMDIST, od_dist, out_dir_dist
   - start/end/duration aliases
6. Build the Panel template and page tabs.
7. Render one chart trace or table pane per run.

## Module roles

| Module | Responsibility |
| --- | --- |
| [`run.py`](/c:/Users/wesley.darling/projects/activitysim_visualizer/run.py) | CLI entry point, run loading, optional CSV export, Panel serve/export |
| [`summarize/reader.py`](/c:/Users/wesley.darling/projects/activitysim_visualizer/summarize/reader.py) | Config model, raw file reading, skim loading, weight computation, data enrichment |
| [`summarize/*.py`](/c:/Users/wesley.darling/projects/activitysim_visualizer/summarize) | Domain summaries by topic |
| [`dashboard/app.py`](/c:/Users/wesley.darling/projects/activitysim_visualizer/dashboard/app.py) | Global sidebar controls, tab assembly, static export behavior |
| [`dashboard/components.py`](/c:/Users/wesley.darling/projects/activitysim_visualizer/dashboard/components.py) | Shared Plotly chart builders, Tabulator helper, run color handling, percent mode flag |
| [`dashboard/pages/*.py`](/c:/Users/wesley.darling/projects/activitysim_visualizer/dashboard/pages) | One page per tab with local controls and output layout |

## Plotting and table stack

- Data manipulation: `polars`
- Small numeric helpers: `numpy`
- Charts: `plotly.graph_objects`
- Chart embedding: `pn.pane.Plotly`
- Tables: `pn.widgets.Tabulator`
- App shell: `pn.template.FastListTemplate`

There is no hvPlot, Altair, Bokeh authoring API, or class-based Panel state. The app stays close to raw Plotly + functional callbacks.

## Reactive and state model

- Global app state is minimal:
  - `weight_mode`: `Weighted` vs `Unweighted`
  - `value_mode`: `Percent` vs `Count`
- `build_dashboard()` caches four tab sets keyed by `(weighted?, percent?)` so toggling does not rebuild pages every time.
- `Unweighted` mode is implemented by cloning each `RunData` and replacing `finalweight` with `1.0` on households, persons, tours, and trips.
- `Percent` mode is implemented through a mutable module-level flag in [`dashboard/components.py`](/c:/Users/wesley.darling/projects/activitysim_visualizer/dashboard/components.py): `_DISPLAY_PERCENT_MODE`.
- Page-level reactivity is local and simple:
  - `pn.widgets.Select`
  - `@pn.depends(...)`
  - `pn.bind(...)` for the top-level tab switcher
- There is no central shared store across pages. Pages do not talk to each other.

## Important architectural implications for migration

- The safest migration path is to preserve `summarize/reader.py` and `summarize/*.py` as the source of truth first, then replace only the UI/runtime layer.
- The Panel app already separates data prep from rendering reasonably well.
- The main behavior that should not be ported directly is the mutable global percent flag. In Shiny, percent/count should be an explicit reactive input passed into pure chart functions.
- The current app is comparison-first. Any Quarto + Shiny design should keep "multiple runs as parallel traces" as a first-class assumption rather than treating run selection as an afterthought.
