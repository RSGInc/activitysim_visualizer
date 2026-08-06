# 11 - Configuring Your Data

Choose one of the three input types below, and give each run a label. For exact
table, key, relationship, and type rules, see
[14 - Input Data Contract](14-input-data-contract.md).

## Run Input Decision Matrix

The fields on one run can be combined only when their boundaries make sense:

| Run input | Prepare source | Skimjoin | Segmentation | Generated summaries | Mapped-summary behavior |
|---|---|---|---|---|---|
| `dir` | Raw CSV/Parquet files | Available when the step and paths are configured | Available | Available | Optional mapped IDs replace generated IDs. |
| `prepared_table_map` | Supplied canonical tables; raw prepare is skipped | Skipped for this run | Available | Available | Optional mapped IDs replace generated IDs. |
| `summary_table_map` only | None | Not available | Not available | Not available | Mapped IDs are the run's summaries. |
| `dir` plus `summary_table_map` | Raw files | Available | Available | Available for unmapped IDs | The same mapped table replaces its ID for full and segmented units. |
| `prepared_table_map` plus `summary_table_map` | Supplied canonical tables | Skipped | Available | Available for unmapped IDs | The same mapped table replaces its ID for full and segmented units. |
| `--from-csvs <cache-dir>` | Existing manifested cache bundle | Already complete | Already complete | Not run | Loads the bundle; it is not a loose-file mapping. |

`file_map`, `skim_file`, and the three run weight fields apply to raw `dir`
input. `file_map` cannot be combined with `prepared_table_map`. A
`summary_table_map` entry is mode-independent: built-in weighted and unweighted
modes copy it, while declarative named modes reject it because they cannot
recalculate an aggregated file.

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

The dashboard uses the label to identify the run.

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

The prepare step copies the first available source into the canonical
visualizer column. See the
[complete column list](13-configuration-reference.md#columns) in chapter 13.

## Already-Prepared Tables

Use `prepared_table_map` for canonical tables created by another process. That
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

Each path must end in `.csv` or `.parquet`. Relative paths start from the
configuration file directory. The tables must contain the canonical prepared
columns required by the summaries. For this type of run, the visualizer skips
raw preparation and integrated skimjoin.

The visualizer also skips canonicalization, derived columns, standard weight
creation, and geography mapping. The supplied files must already satisfy those
parts of the prepared contract.

## Dashboard-Ready Summary Tables

Use `summary_table_map` for registered summary tables created by another
process:

```yaml
runs:
  - label: External Validation
    summary_table_map:
      population_totals: summaries/population_totals.csv
      traffic_count_comparisons: summaries/traffic_counts.parquet
```

Each key must appear in the [Summary Catalog](26-summary-catalog.md), and each
file must have the registered columns in the specified order. A run can contain
only external summaries, or external summaries can replace selected summaries
from raw or prepared data.

Mapped summary tables cannot be segmented or reweighted from their rows. When
combined with buildable input, one mapped table is overlaid unchanged on every
full or segmented analysis unit.

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

If you do not set weight columns, the prepare step uses the configured
sample-rate column when available and otherwise uses `1.0`.

If the output tables contain other weights, add a named column mode instead of
duplicating the run or writing Python:

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

The visualizer validates the named sources and copies the weights to relevant
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
- To build the same summaries for configured subsets, read
  [Segmentation](24-segmentation.md).
- To add district, county, or other zone mappings, read
  [Geography](27-geography.md).
- For every accepted key and default, use the
  [Configuration Reference](13-configuration-reference.md).

## Next

- [Run workflows and manage caches](12-running-workflows.md)
- [Troubleshoot missing data](90-troubleshooting.md)
