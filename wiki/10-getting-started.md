# 10 - Getting Started

Follow these steps to start a local dashboard from a repository clone.

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

Create `local_config.yaml` to define the input and output:

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

Set the two `dir` values to ActivitySim output directories. The default
input names are `final_households`, `final_persons`, `final_day`,
`final_tours`, `final_trips`, `final_vehicles`,
`final_joint_tour_participants`, and `final_land_use`. Day, vehicle, joint
participant, and land-use tables are optional. Each input file can be CSV or
Parquet.

If your files have different names, read
[File Names](11-configuring-your-data.md#raw-activitysim-output).

`root` is the artifact directory, where the visualizer writes summary caches
and resolves relative export paths. Keep the export path in the configuration
for a live workflow. To create HTML later, you only need to change
`pipeline.dashboard_mode` from `live` to `export`.

## 3. Run The Config

```bash
uv run activitysim-viz --config local_config.yaml
```

On the first run, the visualizer prepares the data, builds the summaries, and
starts the dashboard at [http://localhost:5006](http://localhost:5006). Later
runs reuse valid caches.

To stop the server, press `Ctrl+C`.

The command is the same for live dashboards, HTML exports, and processor-only
workflows. Select the workflow in the `pipeline` and `dashboard` sections.

## If the first execution fails

Check the following:

1. Make sure each `runs[*].dir` exists.
2. Make sure each required table is a `.csv` or `.parquet` file.
3. Make sure `zones.use_maz`, `maz_col`, and `taz_col` agree with the model.
4. Find the missing file or column in the log.

For more help, see [Troubleshooting](90-troubleshooting.md).

## Next

- [Choose an input type](11-configuring-your-data.md)
- [Configure live, export, and processor workflows](12-running-workflows.md)
- [Use the dashboard](30-output-visualizer.md)
