# 11 - Configuring Your Data

Select an input type and give each run a label. Use one of these three
configurations.

## Raw ActivitySim Output

Use this configuration for standard ActivitySim output directories:

```yaml
root: artifacts

runs:
  - dir: C:\models\base\output
    label: Base
  - dir: C:\models\build\output
    label: Build
```

The dashboard shows this label.

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

A name without an extension selects a `.parquet` or `.csv` file. Use `file_map`
to set nonstandard file names for one run:

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

If a model uses different column names, list the possible names in order of
preference:

```yaml
columns:
  household_id: [household_id, hh_id]
  tour_purpose: [primary_purpose, tour_type, purpose]
  trip_mode: mode
```

The prepare step copies the selected source to the canonical visualizer
column. See the [complete column list](13-configuration-reference.md#columns)
in chapter 13.

## Already-Prepared Tables

Use `prepared_table_map` for canonical tables from a different process. This
process can prepare, skimjoin, or filter the tables:

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

Each path must end in `.csv` or `.parquet`. A relative path starts from the
configuration file directory. The tables must contain the canonical prepared
columns that the summaries require. The visualizer does not run raw prepare or
integrated skimjoin for this run.

## Dashboard-Ready Summary Tables

Use `summary_table_map` for registered summary tables from a different process:

```yaml
runs:
  - label: External Validation
    summary_table_map:
      population_totals: summaries/population_totals.csv
      traffic_count_comparisons: summaries/traffic_counts.parquet
```

Each key must occur in the [Summary Catalog](24-summary-catalog.md). Each file
must have the registered columns in the specified order. A run can contain
only external summaries. External summaries can also replace selected
summaries from raw or prepared data.

## Weights

Configure the standard modes with:

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

If you do not set weight columns, prepare uses the configured sample-rate
column when it is available. If this column is not available, prepare uses
`1.0`.

If the output tables contain more weights, add a named column mode. Do not
duplicate the run or write Python for this configuration:

```yaml
weighting:
  modes:
    calibrated:
      label: Calibrated
      columns:
        households: calibrated_hh_weight
        persons: calibrated_person_weight
        trips: calibrated_trip_weight

summarize:
  weighting_modes: [weighted, unweighted, calibrated]
```

The visualizer validates the named sources. It copies the weights to applicable
tours, days, vehicles, and skimjoin sidecar tables. See
[43 - Weighting And Hosting Extensions](43-weighting-hosting-extensions.md#worked-example-add-a-weighting-mode)
for the rules.

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
