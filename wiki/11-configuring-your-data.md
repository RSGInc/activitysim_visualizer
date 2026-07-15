# 11 - Configuring Your Data

Most users only need to choose an input type and name their runs. Use one of the
three patterns below.

## Raw ActivitySim Output

Use this when you have normal ActivitySim output folders:

```yaml
root: artifacts

runs:
  - dir: C:\models\base\output
    label: Base
  - dir: C:\models\build\output
    label: Build
```

The label is what appears in the dashboard.

### File Names

The default files are:

```yaml
files:
  households: final_households
  persons: final_persons
  tours: final_tours
  trips: final_trips
  joint_tour_participants: final_joint_tour_participants
  land_use: final_land_use
```

A bare name accepts either `.parquet` or `.csv`. Override one unusual run with
`file_map`:

```yaml
runs:
  - dir: C:\models\base\output
    label: Base
  - dir: C:\models\build\output
    label: Build
    file_map:
      trips: linked_trips
      persons: final_people.csv
```

### Column Names

If a model uses different column names, list the candidates in preferred order:

```yaml
columns:
  household_id: [household_id, hh_id]
  tour_purpose: [primary_purpose, tour_type, purpose]
  trip_mode: mode
```

Prepare converts the selected source to the visualizer's canonical column. See
chapter 13 for the [complete column list](13-configuration-reference.md#columns).

## Already-Prepared Tables

Use `prepared_table_map` for canonical tables that were prepared, skimjoined,
or filtered elsewhere:

```yaml
runs:
  - label: Filtered Run
    prepared_table_map:
      households: prepared/households.parquet
      persons: prepared/persons.parquet
      tours: prepared/tours.parquet
      trips: prepared/trips.parquet
      land_use: prepared/land_use.parquet
```

Paths must end in `.csv` or `.parquet` and are relative to the config file.
These tables must already use the canonical prepared columns expected by
summaries. Raw prepare and integrated skimjoin are skipped for this run.

## Dashboard-Ready Summary Tables

Use `summary_table_map` when another process has already produced registered
summary tables:

```yaml
runs:
  - label: External Validation
    summary_table_map:
      population_totals: summaries/population_totals.csv
      traffic_count_comparisons: summaries/traffic_counts.parquet
```

Keys must appear in the [Summary Catalog](24-summary-catalog.md). Files must
match the registered columns exactly. A run may contain only outside summaries,
or they may override selected summaries generated from raw/prepared data.

## Weights

The normal modes are configured with:

```yaml
summarize:
  weighting_modes: [weighted, unweighted]
```

If a run has explicit weight columns:

```yaml
runs:
  - dir: C:\models\base\output
    label: Base
    hh_weight_col: household_weight
    person_weight_col: person_weight
    trip_weight_col: trip_weight
```

Otherwise prepare uses a configured sample-rate column when available, then
falls back to `1.0`.

## Zones

TAZ-only model:

```yaml
zones:
  use_maz: false
  maz_col: zone_id
  taz_col: TAZ
```

MAZ/TAZ model:

```yaml
zones:
  use_maz: true
  maz_col: [MAZ, zone_id]
  taz_col: [TAZ, taz]
```

## Optional Features

- For skim enrichment, read [Skimjoin](22-skimjoin.md).
- For custom geography aggregation, read the
  [`summarize.geography` reference](13-configuration-reference.md#summarize).
- For segmentation, read the
  [`segment` reference](13-configuration-reference.md#segment).
- For every accepted key and default, use the
  [Configuration Reference](13-configuration-reference.md).

## Next

- [Run workflows and manage caches](12-running-workflows.md)
- [Troubleshoot missing data](90-troubleshooting.md)
