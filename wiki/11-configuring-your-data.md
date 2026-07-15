# 11 - Configuring Your Data

The config file tells the visualizer where model outputs live, how to normalize
them, and which workflow to run. The canonical example is
[`config.yaml`](../config.yaml).

For full field-by-field options, defaults, allowed values, path behavior, and
cache impact, see [13 - Configuration Reference](13-configuration-reference.md).

## Top-Level Sections

| Section | Purpose |
|---|---|
| `root` | Base artifact directory for caches and exports. |
| `pipeline` | Default steps, dashboard mode, and overwrite behavior. |
| `runs` | Model runs, labels, and per-run overrides. |
| `files` | Default raw ActivitySim output filenames. |
| `fallback_files` | Shared explicit files used when optional run-local files are missing. |
| `zones` | MAZ/TAZ behavior and land-use zone columns. |
| `columns` | Column aliases for outputs that do not use expected names. |
| `prepare` | Prepared output format, validation, distance skim, VOT bins. |
| `skimjoin` | Optional skim enrichment defaults. |
| `segment` | Optional segment definitions and dashboard visibility. |
| `summarize` | Weighting modes and summary options. |
| `dashboard` | Title, page selection, live/export behavior. |
| `display` | Labels, category order, and run colors. |

## Raw ActivitySim Runs

Use `runs[*].dir` for folders containing raw ActivitySim output files:

```yaml
runs:
  - dir: C:\models\base\output
    label: Base
  - dir: C:\models\build\output
    label: Build
```

Labels become dashboard run names. Keep them stable: cache keys and comparison
tables are easier to understand when labels do not change casually.

## File Names

`files` maps logical table names to raw output file stems. The reader tries
`.parquet` first, then `.csv`, unless you specify an extension.

```yaml
files:
  households: final_households
  persons: final_persons
  tours: final_tours
  trips: final_trips
  joint_tour_participants: final_joint_tour_participants
  land_use: final_land_use
```

If one run uses different names, override only that run:

```yaml
runs:
  - dir: C:\models\base\output
    label: Base
  - dir: C:\models\build\output
    label: Build
    file_map:
      households: household
      persons: person
      tours: tour
      trips: trip_linked
```

## Using Pre-Prepared Tables

Use `prepared_table_map` when a run should skip raw prepare and load canonical
prepared tables directly:

```yaml
runs:
  - label: Filtered Prepared Run
    prepared_table_map:
      households: C:\prepared\households.parquet
      persons: C:\prepared\persons.parquet
      tours: C:\prepared\tours.parquet
      trips: C:\prepared\trips.parquet
      joint_tour_participants: C:\prepared\joint_tour_participants.parquet
      land_use: C:\prepared\land_use.parquet
```

Use this for tables that already follow the prepared table contract. If you need
skimjoin-derived columns in this path, include them in the supplied prepared
tables; the raw prepare path is skipped for that run.

## Weights

The processor creates `finalweight` during prepare. Most summaries aggregate
`finalweight`, and the summary workflow can build both weighted and unweighted
outputs.

Common options:

```yaml
summarize:
  weighting_modes: [weighted, unweighted]
```

If no explicit run weight column and no sample rate are available, weights fall
back to `1.0`. If model outputs use custom weight columns, set the appropriate
run-level fields supported by the config schema.

## Zones And Geography

For TAZ-only models:

```yaml
zones:
  use_maz: false
  maz_col: zone_id
  taz_col: TAZ
```

For MAZ/TAZ models:

```yaml
zones:
  use_maz: true
  maz_col: [MAZ, zone_id]
  taz_col: TAZ
```

Custom geography aggregations live under `summarize.geography`:

```yaml
summarize:
  geography:
    enabled: true
    aggregations:
      district:
        source_zone_system: maz
        file: C:\lookups\land_use.csv
        zone_id_col: MAZ
        geography_col: DISTRICT
```

## Per-Run Skimjoin Overrides

Use global defaults when all runs share lookup logic:

```yaml
skimjoin:
  defaults:
    config_path: configs\skimjoin_default.yaml
    skim_files:
      - C:\skims\*.omx
    network_los_file: C:\skims\network_los.yaml
```

Override individual runs when skim files, period definitions, or lookup logic
differ:

```yaml
runs:
  - dir: C:\models\base\output
    label: Base
    skimjoin:
      config_path: configs\skimjoin_base.yaml
      skim_files:
        - C:\base_skims\*.omx
      network_los_file: C:\base_skims\network_los.yaml
```

## Config Recipes

### Dashboard From Existing Summary Caches

```yaml
pipeline:
  steps: [dashboard]
  dashboard_mode: live
```

Run:

```bash
python run.py --config local_config.yaml --from-csvs
```

### Export-Only Workflow

```yaml
pipeline:
  steps: [summarize, dashboard]
  dashboard_mode: export

dashboard:
  export:
    output_path: exports\dashboard.html
```

### Prepared Tables With No Raw Run Directory

```yaml
pipeline:
  steps: [summarize, dashboard]

runs:
  - label: Scenario A
    prepared_table_map:
      households: C:\scenario_a\households.parquet
      persons: C:\scenario_a\persons.parquet
      tours: C:\scenario_a\tours.parquet
      trips: C:\scenario_a\trips.parquet
      land_use: C:\scenario_a\land_use.parquet
```

## Related Chapters

- [12 - Running Workflows](12-running-workflows.md)
- [13 - Configuration Reference](13-configuration-reference.md)
- [21 - Prepared Tables](21-prepared-tables.md)
- [22 - Skimjoin](22-skimjoin.md)

