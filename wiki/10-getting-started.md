# 10 - Getting Started

This chapter gets a new machine from clone to dashboard. It assumes you already
have ActivitySim output files or prepared tables to visualize.

## Install

Install dependencies with `uv`:

```bash
uv sync --locked
```

If Windows reports a hardlink problem, retry with copy mode:

```bash
uv sync --locked --link-mode=copy
```

Activate the virtual environment if you want to run commands directly:

```powershell
.\.venv\Scripts\activate
```

## Create A Local Config

Start from the example config:

```powershell
Copy-Item config.yaml local_config.yaml
```

Edit `local_config.yaml`:

1. Set `root` to a local artifact folder.
2. Add one or more entries under `runs`.
3. Confirm `files` matches your ActivitySim output names.
4. Set `zones.use_maz` and the MAZ/TAZ columns correctly.
5. Set `pipeline.steps` and `pipeline.dashboard_mode`.

The smallest useful raw-output run looks like this:

```yaml
root: artifacts

pipeline:
  steps: [prepare, summarize, dashboard]
  dashboard_mode: live

runs:
  - dir: C:\path\to\activitysim\output
    label: Base

files:
  households: final_households
  persons: final_persons
  tours: final_tours
  trips: final_trips
  joint_tour_participants: final_joint_tour_participants
  land_use: final_land_use

zones:
  use_maz: false
  maz_col: zone_id
  taz_col: TAZ
```

## First Run

Run the configured pipeline:

```bash
python run.py --config local_config.yaml
```

With `dashboard_mode: live`, the app serves a local dashboard on the configured
port, defaulting to `http://localhost:5006`.

With `dashboard_mode: export`, the app writes an HTML file and exits.

## Common First Commands

| Goal | Command |
|---|---|
| Build prepared caches only | `python run.py --config local_config.yaml --prepare-only` |
| Build or reuse summaries | `python run.py --config local_config.yaml --summarize` |
| Build summaries and open dashboard | `python run.py --config local_config.yaml --summarize --dashboard` |
| Open dashboard from existing summary caches | `python run.py --config local_config.yaml --from-csvs` |
| Export a standalone dashboard | `python run.py --config local_config.yaml --export-html exports/dashboard.html` |
| Rebuild both cache layers | `python run.py --config local_config.yaml --refresh-caches` |

## What Gets Created

The first successful processor run creates:

- prepared caches: canonical per-run tables used by summaries and prepared-data pages
- summary caches: dashboard-ready CSV tables under each run and weighting mode
- logs and diagnostics
- optional export HTML when export mode is selected

## Next Steps

- For raw/prepared input options, read [11 - Configuring Your Data](11-configuring-your-data.md).
- For cache and CLI behavior, read [12 - Running Workflows](12-running-workflows.md).
- For dashboard pages and exports, read [30 - Output Visualizer](30-output-visualizer.md).
