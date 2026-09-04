# SimOR Quick Start

This guide explains how to use the included Metro, LCOG, and SKATS
configurations to create three area dashboards and one combined comparison
dashboard. It covers only the paths and file names normally needed on a new
computer. For other changes, use the [main documentation](wiki/00-home.md).

## 1. Install the visualizer

Open a terminal in the repository root and install the locked dependencies:

```bash
uv sync --locked
```

If Windows reports a hardlink problem, use:

```bash
uv sync --locked --link-mode=copy
```

## 2. Update the three area configs

The area configs are:

- [Metro](simor_configs/metro_configs/metro_config.yaml)
- [LCOG](simor_configs/lcog_configs/lcog_config.yaml)
- [SKATS](simor_configs/skats_configs/skats_config.yaml)

Make the following changes in each config that you plan to run. The SimOR
runner runs all three areas, so all three configs must be valid when using that
runner.

### Output locations

`root` is where the area config writes prepared tables, summary tables, and
other working files. A relative path starts from the directory containing the
config. The included value writes to `simor_project_outputs/` in this
repository, so it can usually be left unchanged.

`dashboard.export.output_path` is the exported HTML file. A relative export
path starts from `root`. The included configs place all exports in
`simor_project_outputs/exports/`.

If you change an area's `root`, set `dashboard.export.output_path` relative to
the new root (or use an absolute path). Also update that area's paths under
`runs[*].prepared_table_map` in the
[comparison config](simor_configs/comparison_configs/estimation_mode_outputs_comparison.yaml).
The comparison reads the prepared tables created by the area dashboards.

### Input directories and file names

Set every `runs[*].dir` to the directory that contains that run's ActivitySim
output files. Each included area config expects four runs:

1. Raw Statewide Survey
2. Regional: Filtered & Attributed
3. Estimation Mode Inputs
4. Estimation Mode Outputs

The `files` section defines the default table names for the config.
`runs[*].file_map` overrides those names for one run. Update a `file_map` entry
only when the files on your computer use a different name. A name without an
extension accepts either CSV or Parquet; an explicit `.csv` or `.parquet`
extension requires that format.

Set `fallback_files.land_use` to a land-use CSV or Parquet file that can be
shared by runs that do not contain their own land-use table. If every run has
the correct land-use file, this fallback can be removed.

For more detail about input files, see
[Configuring Your Data](wiki/11-configuring-your-data.md).

### Distance and time-period files

Set these paths in the `prepare` section:

- `prepare.distance_skim.file`: the motorized distance OMX used when skimjoin
  is skipped. Confirm that `prepare.distance_skim.matrix` names the correct
  distance matrix.
- `prepare.non_motorized_distance_skim.file`: the walk/non-motorized distance
  CSV or OMX. For an OMX file, also set its `matrix`.
- `prepare.time_periods.network_los_file`: the ActivitySim `network_los.yaml`
  used to convert period numbers to time-period labels.

Also set `skimjoin.defaults.network_los_file` to that valid
`network_los.yaml` path. The config loader validates the configured skimjoin
settings before applying the runner's `--no-skimjoin` workflow selection, even
though that run does not read the skim files.

These files provide distance, VMT, and time-period values for the exported
dashboard when you run with `--no-skimjoin`.

### Geographic aggregations

Choose one setup before running:

- To include the configured district, county, city, or other aggregations,
  leave `summarize.geography.enabled: true` and update every
  `summarize.geography.aggregations.*.file` path to the area's land-use file.
- If you do not need those aggregations, set
  `summarize.geography.enabled: false`. No aggregation file paths are then
  required.

## 3. Check the comparison config

The
[comparison config](simor_configs/comparison_configs/estimation_mode_outputs_comparison.yaml)
uses the prepared `Estimation Mode Outputs` from the three area configs.
Its included `prepared_table_map` paths work with the included area `root`
values. Update the maps only if you changed those roots, output format, or the
`Estimation Mode Outputs` run label.

Also set `prepare.time_periods.network_los_file` in the comparison config to a
valid `network_los.yaml` path. The comparison inputs are already prepared, but
the config loader still validates this configured file.

## 4. Export the dashboards without skimjoin

From the repository root, run:

```bash
uv run python scripts/run_simor_scenarios.py --no-skimjoin
```

This command does not require changing or commenting out `pipeline.steps`. It
prepares, summarizes, and exports Metro, LCOG, and SKATS with up to two area
jobs running at once. After all three succeed, it exports the comparison
dashboard.

With the included output settings, the finished files are:

```text
simor_project_outputs/exports/metro_dashboard.html
simor_project_outputs/exports/lcog_dashboard.html
simor_project_outputs/exports/skats_dashboard.html
simor_project_outputs/exports/estimation_mode_outputs_comparison.html
```

The runner prints `PASS` or `FAIL` as each dashboard finishes. Detailed runtime
and console logs are written to a timestamped directory under
`simor_project_outputs/logs/scenario_runner/`.

## Run with skimjoin

Skimjoin adds the skim-derived fields and skim summary pages. Before using it,
set these values in each area config:

- `skimjoin.defaults.skim_files`: the area's OMX and supporting CSV files;
- `skimjoin.defaults.network_los_file`: the area's `network_los.yaml`; and
- `runs[*].skimjoin.config_path`: only when that run needs rules different from
  the area's default rules. The included regional survey runs already select
  the alternate-ID rules files.

Then run the same runner without `--no-skimjoin`:

```bash
uv run python scripts/run_simor_scenarios.py
```

The area-specific skimjoin rule files are next to each area config. Editing
their lookup rules is outside this quick start; see
[Skimjoin](wiki/22-skimjoin.md) and the
[Skimjoin Config Reference](wiki/23-skimjoin-config-reference.md).

## Add another SimOR area

Adding an area is a short manual registration; the runner does not discover
area configs automatically.

1. Copy the closest existing area config directory and update its main config,
   logo, output paths, and, if needed, skimjoin rule files.
2. Add the new area name and main config path to `AREA_CONFIGS` in
   [`scripts/run_simor_scenarios.py`](scripts/run_simor_scenarios.py).
3. To include the area in the combined dashboard, copy an existing run block in
   the comparison config, point its `prepared_table_map` to the new area's
   `Estimation Mode Outputs` prepared tables, and add a matching
   `display.run_colors` entry.
4. Run the command above. The runner will build the new area before starting
   the comparison.

For changes to tables, columns, summaries, or dashboard pages, use the
[configuration reference](wiki/13-configuration-reference.md) rather than
expanding this quick-start setup.
