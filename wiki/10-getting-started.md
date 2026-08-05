# 10 - Getting Started

This is the shortest path from a clone to a local dashboard.

## 1. Install

From the repository root:

```bash
uv sync --locked
```

If Windows reports a hardlink problem:

```bash
uv sync --locked --link-mode=copy
```

## 2. Create A Small Config

Create `local_config.yaml`. This file defines both the inputs and what the run
should produce:

```yaml
root: artifacts

pipeline:
  steps: [prepare, summarize, dashboard]
  dashboard_mode: live
  refresh: []

runs:
  - dir: C:\models\base\output
    label: Base
  - dir: C:\models\build\output
    label: Build

zones:
  use_maz: false
  maz_col: zone_id
  taz_col: TAZ

dashboard:
  title: Regional Model Comparison
  export:
    output_path: exports/dashboard.html
```

Change the two `dir` values to real ActivitySim output folders. The default
input names are `final_households`, `final_persons`, `final_tours`,
`final_trips`, `final_joint_tour_participants`, and `final_land_use`; each may be
CSV or Parquet.

If your files have different names, read
[File Names](11-configuring-your-data.md#raw-activitysim-output).

`root` is the visualizer's artifact location. Summary caches are written below
it, and relative export paths resolve below it. Keep the export path configured
even for a live workflow; switching from a live dashboard to an HTML file then
requires changing only `pipeline.dashboard_mode` from `live` to `export`.

## 3. Run The Config

```bash
uv run activitysim-viz --config local_config.yaml
```

The first run prepares data, builds summaries, and starts the dashboard at
[http://localhost:5006](http://localhost:5006). Later runs reuse valid caches.

Stop the server with `Ctrl+C`.

Use this same command for live dashboards, HTML exports, and processor-only
workflows. Change the `pipeline` and `dashboard` sections in the config instead
of maintaining different launch commands.

## If The First Run Fails

Check these first:

1. each `runs[*].dir` exists;
2. the expected tables are present as `.csv` or `.parquet`;
3. `zones.use_maz`, `maz_col`, and `taz_col` match the model; and
4. the log names the missing file or column.

Then use [Troubleshooting](90-troubleshooting.md).

## Next

- [Choose an input type](11-configuring-your-data.md)
- [Configure live, export, and processor workflows](12-running-workflows.md)
- [Use the dashboard](30-output-visualizer.md)
