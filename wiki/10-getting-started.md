# 10 - Getting Started

Use this procedure to start a local dashboard from a repository clone.

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

Create `local_config.yaml`. This file defines the input and the required
output:

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
input names are `final_households`, `final_persons`, `final_tours`,
`final_trips`, `final_joint_tour_participants`, and `final_land_use`. Each input
file can be CSV or Parquet.

If your files have different names, read
[File Names](11-configuring-your-data.md#raw-activitysim-output).

`root` is the artifact directory. The visualizer writes summary caches in this
directory. It also resolves relative export paths from this directory. Keep
the export path in the configuration for a live workflow. You can then create
HTML by changing only `pipeline.dashboard_mode` from `live` to `export`.

## 3. Run The Config

```bash
uv run activitysim-viz --config local_config.yaml
```

The first execution prepares data and builds summaries. It then starts the dashboard
at [http://localhost:5006](http://localhost:5006). Later executions use valid caches.

To stop the server, press `Ctrl+C`.

Use this command for live dashboards, HTML exports, and processor-only
workflows. Change the `pipeline` and `dashboard` sections to select the
workflow.

## If the first execution fails

Do these checks:

1. Make sure that each `runs[*].dir` exists.
2. Make sure that each required table is a `.csv` or `.parquet` file.
3. Make sure that `zones.use_maz`, `maz_col`, and `taz_col` agree with the model.
4. Find the missing file or column in the log.

Then use [Troubleshooting](90-troubleshooting.md).

## Next

- [Choose an input type](11-configuring-your-data.md)
- [Configure live, export, and processor workflows](12-running-workflows.md)
- [Use the dashboard](30-output-visualizer.md)
