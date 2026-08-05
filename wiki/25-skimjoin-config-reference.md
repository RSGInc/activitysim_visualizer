# 25 - Skimjoin Config Reference

This page describes each field in the standalone skimjoin configuration file.
The main visualizer `skimjoin` step uses this file. For a workflow introduction,
read [22 - Skimjoin](22-skimjoin.md). See this canonical example:
[`example_skimjoin_config.yaml`](../example_skimjoin_config.yaml).

The skimjoin configuration answers four questions:

1. Which skim files and optional `network_los.yaml` must skimjoin use?
2. Which prepared trip and tour columns supply modes, IDs, dimensions, and OD
   lookup columns?
3. Which matrix or sidecar table must skimjoin read for each mode and component?
4. Which policy applies when matrices, OD pairs, or dimension values are missing?

## Common Recipes

### Basic OD Lookup

```yaml
project:
  skim_files:
    - C:\skims\auto.omx

activitysim:
  trip_mode_column: trip_mode
  tour_mode_column: tour_mode
  trip_id_column: trip_id
  tour_id_column: tour_id
  outbound_column: outbound

defaults:
  origin: OTAZ
  destination: DTAZ
  output_prefix: skim_

zone_mapping:
  lookup_name: taz

modes:
  SOV:
    time: SOV_TIME
    distance: SOV_DIST
```

`time: SOV_TIME` has the same result as:

```yaml
time:
  matrix: SOV_TIME
```

### Period Dimension Lookup

```yaml
project:
  skim_files:
    - C:\skims\auto.omx
  network_los_file: C:\skims\network_los.yaml

activitysim:
  trip_mode_column: trip_mode
  tour_mode_column: tour_mode
  trip_id_column: trip_id
  tour_id_column: tour_id
  outbound_column: outbound

defaults:
  origin: OTAZ
  destination: DTAZ

dimensions:
  PERIOD:
    source_columns:
      trip_source_column: depart
      outbound_tour_source_column: start
      inbound_tour_source_column: first_inbound_trip_depart
    values_from_network_los: true

modes:
  SOV:
    time: SOV_TIME__{PERIOD}
```

### Segmented PNR Lookup

```yaml
modes:
  PNR_TRANSIT:
    output_prefix: skim_
    segment_on: outbound
    segments:
      true:
        auto_time:
          matrix: SOV_TIME__{PERIOD}
          origin: OTAZ
          destination: pnr_taz
        transit_time:
          matrix: WTW_TIV__{PERIOD}
          origin: pnr_taz
          destination: DTAZ
      false:
        auto_time:
          matrix: SOV_TIME__{PERIOD}
          origin: pnr_taz
          destination: DTAZ
        transit_time:
          matrix: WTW_TIV__{PERIOD}
          origin: OTAZ
          destination: pnr_taz
```

### Fallback Lookup

```yaml
modes:
  SOV:
    time:
      output: skim_auto_time
      matrix: SOV_TIME__{PERIOD}
      fallbacks:
        - matrix: SOV_TIME__MD
```

Fallbacks execute after the primary lookup. They apply to rows for which the earlier
step did not supply a valid value. Fallback steps use the same final output
column.

### Tour Aggregation

```yaml
tour_aggregation:
  method: aggregate_trips
  aggregations:
    skim_auto_time: sum
    skim_auto_distance: sum
    skim_transit_fare: sum
  directional_outputs:
    skim_auto_time: true
```

Mode rules also create tour lookups directly. Tour lookup output gets an
`_outbound` or `_inbound` suffix.

## Top-Level Sections

| Section | Type | Default | Purpose |
|---|---|---|---|
| `project` | mapping | optional | Skim paths and standalone CLI paths. |
| `skim_files` | list | promoted from `project.skim_files` | Direct skim file list. Usually set under `project`. |
| `activitysim` | mapping | required | Prepared trip/tour source column names. |
| `defaults` | mapping | built-in lookup defaults | Origin, destination, output prefix, missing-data policy, and sentinels. |
| `zone_mapping` | mapping | no mapping name | OMX zone lookup name behavior. |
| `dimensions` | mapping | `{}` | Placeholder definitions for matrix names. |
| `ignore_modes` | list | `[]` | Trip modes allowed to have no lookup rules. |
| `modes` | mapping | required | Mode-specific lookup rules. |
| `tour_aggregation` | mapping | `aggregate_trips` with no configured aggregations | Trip-to-tour aggregation settings. |

The Pydantic schema rejects unknown keys in typed sections.

## `project`

| Field | Type | Default | Notes |
|---|---|---|---|
| `skim_files` | list of path strings | `[]` | OMX, CSV, HDF5, or H5 skim inputs. In integrated visualizer use, main config overrides may replace this list. |
| `network_los_file` | path string | none | ActivitySim `network_los.yaml`, used when `dimensions.PERIOD.values_from_network_los` is true. |
| `trips_table` | path string | none | Standalone skimjoin CLI input. Not required for integrated visualizer use. |
| `tours_table` | path string | none | Standalone skimjoin CLI input. Optional. |
| `output_dir` | path string | none | Standalone skimjoin CLI output directory. |

```yaml
project:
  skim_files:
    - C:\skims\*.omx
    - C:\skims\maz_stop_walk.csv
  network_los_file: C:\skims\network_los.yaml
```

## `activitysim`

`activitysim` names columns in prepared trip and tour tables.

| Field | Type | Default | Notes |
|---|---|---|---|
| `trips_table` | path string | none | Standalone CLI trips table. May also be promoted from `project.trips_table`. |
| `tours_table` | path string | none | Standalone CLI tours table. May also be promoted from `project.tours_table`. |
| `trip_mode_column` | string | `trip_mode` | Mode column in prepared trips. |
| `tour_mode_column` | string | `tour_mode` | Mode column in prepared tours. |
| `trip_id_column` | string | `trip_id` | Trip id column. |
| `tour_id_column` | string | `tour_id` | Tour id column. |
| `outbound_column` | string | `outbound` | Trip outbound/inbound flag. |

Column names cannot be blank.

## `defaults`

Each mode, segment, and component uses these defaults. A value nearer to the
rule overrides a default.

| Field | Type | Default | Allowed values | Notes |
|---|---|---|---|---|
| `origin` | string | `origin` | source column | Origin column for OD lookups. |
| `destination` | string | `destination` | source column | Destination column for OD lookups. |
| `output_prefix` | string | `skim_` | any string | Prefix used when a component does not set `output`. |
| `missing_matrix_policy` | string | `error` | `error`, `warn`, `set_null` | Policy for absent matrices or matrix names that skimjoin cannot resolve. |
| `missing_od_policy` | string | `error` | `error`, `warn`, `set_null` | Policy for missing/out-of-bounds OD values. |
| `sentinel_values` | list of numbers | `[]` | numeric list | Skimjoin treats lookup results equal to these values as missing. |

```yaml
defaults:
  origin: OTAZ
  destination: DTAZ
  output_prefix: skim_auto_
  missing_matrix_policy: warn
  missing_od_policy: set_null
  sentinel_values: [9999, 999999]
```

## Context Inheritance

You can set these keys in the top-level `defaults`, a mode, a mode `defaults`
block, a segment, or a component:

`origin`, `destination`, `output_prefix`, `missing_matrix_policy`,
`missing_od_policy`, `sentinel_values`, `when`, and `dimensions`.

Settings nearer to a rule override or merge with parent settings:

| Key | Merge behavior |
|---|---|
| `origin`, `destination`, `output_prefix`, policies | Override parent value. |
| `sentinel_values` | Override parent list. |
| `when` | Merge by source column; child values replace same-column parent values. |
| `dimensions` | Merge by dimension name; child dimension replaces same-name parent dimension. |

```yaml
modes:
  SOV:
    output_prefix: skim_auto_
    defaults:
      missing_od_policy: warn
    time:
      matrix: SOV_TIME
      missing_od_policy: set_null
```

## `zone_mapping`

`zone_mapping` controls the selection of an OMX lookup name.

| Field | Type | Default | Allowed values | Notes |
|---|---|---|---|---|
| `lookup_name` | string or null | `null` | OMX mapping name | Default mapping name used for OMX OD matrices. |
| `file_lookup_names` | mapping | `{}` | file pattern to lookup name | Overrides `lookup_name` for matching file paths or file names. Patterns use shell-style matching. |
| `missing_zone_policy` | string | `error` | `error`, `warn`, `set_null` | Policy for missing zone mappings. |

```yaml
zone_mapping:
  lookup_name: taz
  file_lookup_names:
    fares.omx: zone_number
    "*maz*.omx": maz
  missing_zone_policy: error
```

## `dimensions`

Dimensions supply placeholder values for matrix names such as
`SOV_TIME__{PERIOD}`.

Each dimension entry has these fields:

| Field | Type | Default | Notes |
|---|---|---|---|
| `source_columns.trip_source_column` | string | required | Source column used for trip lookup rules. |
| `source_columns.outbound_tour_source_column` | string | required | Source column used for outbound tour lookup rules. |
| `source_columns.inbound_tour_source_column` | string | required | Source column used for inbound tour lookup rules. |
| `values_from_network_los` | boolean | `false` | Only supported for `PERIOD`. Requires `project.network_los_file`. |
| `values` | mapping | `{}` | Raw source value to matrix-name token. The loader normalizes keys and values to strings. |

If `values` is empty, skimjoin converts the raw source value to a string. It
then puts the string in the matrix name. If `values` is present, each observed
value must have a mapping.

```yaml
dimensions:
  PERIOD:
    source_columns:
      trip_source_column: depart
      outbound_tour_source_column: start
      inbound_tour_source_column: first_inbound_trip_depart
    values_from_network_los: true

  VOT:
    source_columns:
      trip_source_column: vot_bin
      outbound_tour_source_column: vot_bin
      inbound_tour_source_column: vot_bin
    values:
      L: L
      M: M
      H: H
```

## `ignore_modes`

`ignore_modes` lists trip modes that do not require a matching `modes` rule.
Use this list for modes that do not require skim enrichment.

```yaml
ignore_modes:
  - BIKE
  - WALK
  - OTHER
```

## `modes`

`modes` contains the main skimjoin rules. Each key is a prepared trip or tour
mode. A mode block can contain context keys and component lookup rules.

Reserved keys inside a mode block:

| Key | Purpose |
|---|---|
| `output_prefix` | Overrides inherited output prefix. |
| `origin` | Overrides inherited origin column. |
| `destination` | Overrides inherited destination column. |
| `dimensions` | Overrides or adds dimension definitions for this mode. |
| `when` | Adds row filters for this mode. |
| `segment_on` | Splits the mode into segment-specific rule blocks. |
| `segments` | Segment value to component block mapping. |
| `defaults` | Nested context defaults for this mode. |
| `missing_matrix_policy` | Mode-level missing matrix policy. |
| `missing_od_policy` | Mode-level missing OD policy. |
| `sentinel_values` | Mode-level sentinel list. |
| `skip` | If `true`, skip the mode block. |
| `apply_to` | Reserved for component rules. |
| `combine` | Reserved for component rules. |
| `fallbacks` | Reserved for component rules. |
| `tour_origin` | Reserved for future/compatibility context. |
| `tour_destination` | Reserved for future/compatibility context. |

Skimjoin uses each non-reserved key in a mode or segment block as a component
name.

```yaml
modes:
  HOV2:
    output_prefix: skim_auto_
    time: SR2_TIME
    distance: SR2_DIST
```

This example creates `skim_auto_time` and `skim_auto_distance`.

## Component Rules

A component rule can be a matrix-name string or a mapping.

| Field | Type | Default | Allowed values | Notes |
|---|---|---|---|---|
| `matrix` | string | required | matrix/table value name | Matrix name or matrix-name template using `{DIMENSION}` placeholders. |
| `output` | string | `output_prefix` + component name | output column | Final output column. Tour lookup outputs also receive `_outbound` or `_inbound`. |
| `lookup` | string | `od` | `od`, `key` | Lookup type. |
| `key_column` | string | none | source column | Required when `lookup: key`. |
| `origin` | string | inherited | source column | Origin column for OD lookup, or key value when `lookup: key` and `key_column` is absent. |
| `destination` | string | inherited | source column | Destination column for OD lookup. Ignored for `lookup: key`. |
| `when` | mapping | inherited/merged | equality or `in` filters | Additional row filters. |
| `dimensions` | mapping | inherited/merged | dimension definitions | Component-specific placeholder definitions. |
| `missing_matrix_policy` | string | inherited | `error`, `warn`, `set_null` | Component missing-matrix policy. |
| `missing_od_policy` | string | inherited | `error`, `warn`, `set_null` | Component missing-OD policy. |
| `sentinel_values` | list of numbers | inherited | numeric list | Component sentinel values. |
| `combine` | string | `replace` | `replace`, `sum` | How to combine overlapping outputs for a row. |
| `apply_to` | string | `both` | `trips`, `tours`, `both` | Whether the component creates trip rules, tour rules, or both. |
| `fallbacks` | list | `[]` | list of component mappings or strings | Lookup chain attempted after the primary step. |

```yaml
modes:
  WALK_TRANSIT:
    output_prefix: skim_
    access_walk_time:
      output: skim_walk_time
      combine: sum
      matrix: WTW_ACC__{PERIOD}
    egress_walk_time:
      output: skim_walk_time
      combine: sum
      matrix: WTW_EGR__{PERIOD}
```

If multiple rules write the same output for the same rows, set `combine: sum`
on all applicable rules. Without this setting, validation reports an output
collision.

## `when` Filters

`when` applies a rule only to rows that agree with source column conditions. A
condition can be scalar equality or an `in` list.

```yaml
modes:
  DRIVE:
    time:
      matrix: SOV_TIME
      when:
        income_segment:
          in: [1, 2]
        outbound: true
```

`when` filters merge through context inheritance. A mode-level filter applies
to all its components. A child filter can replace the same column key.

## `segment_on` And `segments`

Use `segment_on` when one mode requires different lookup rules for different
source values. Each key under `segments` is a value from the `segment_on`
column. Skimjoin adds the applicable `when` filter for each segment.

```yaml
modes:
  PNR_TRANSIT:
    segment_on: outbound
    segments:
      true:
        auto_time:
          matrix: SOV_TIME
          origin: OTAZ
          destination: pnr_taz
      false:
        auto_time:
          matrix: SOV_TIME
          origin: pnr_taz
          destination: DTAZ
```

Validation makes sure that each observed value for a covered mode has a segment
block.

## `fallbacks`

Fallback entries use the same string or mapping format as primary component
rules. Skimjoin tries them in list order after a prior step fails. A fallback
uses the parent component output unless it sets an output. All steps in a
fallback chain must use the same final output.

```yaml
modes:
  SOV:
    time:
      matrix: SOV_TIME__{PERIOD}
      fallbacks:
        - matrix: SOV_TIME__MD
        - matrix: SOV_TIME
          missing_matrix_policy: set_null
```

Skimjoin writes fallback reports to `fallback_lookup_report`.

## Lookup Types

| `lookup` | Required fields | Behavior |
|---|---|---|
| `od` | `matrix`, `origin`, `destination` | Reads an OMX OD matrix or CSV OD table by origin and destination. |
| `key` | `matrix`, `key_column` | Reads a keyed sidecar table by one source column. |

For CSV skim files, the inventory code finds key and value columns from the file
structure. It can also find origin and destination columns. For OMX files, OD
lookups use the configured `zone_mapping` lookup name.

```yaml
modes:
  WALK:
    terminal_walk:
      lookup: key
      key_column: MAZ
      matrix: walk_dist_local_bus
      output: skim_walk_dist
```

## Trip And Tour Rules

By default, each component creates trip and tour lookup rules:

| Target | Source mode column | Dimension source | Output name |
|---|---|---|---|
| Trips | `activitysim.trip_mode_column` | `trip_source_column` | `output` |
| Outbound tours | `activitysim.tour_mode_column` | `outbound_tour_source_column` | `output_outbound` |
| Inbound tours | `activitysim.tour_mode_column` | `inbound_tour_source_column` | `output_inbound` |

Set `apply_to: trips` or `apply_to: tours` to execute a component on only one target
table.

## `tour_aggregation`

`tour_aggregation` controls trip-to-tour totals for skim columns.

| Field | Type | Default | Allowed values | Notes |
|---|---|---|---|---|
| `method` | string | `aggregate_trips` | `aggregate_trips` | Only supported aggregation method. |
| `aggregations` | mapping | `{}` | `sum`, `mean`, `min`, `max`, `first`, `last` | Output column to aggregation method. |
| `directional_outputs` | mapping | `{}` | output column to boolean | Requests directional outbound/inbound tour outputs for selected components. |

```yaml
tour_aggregation:
  method: aggregate_trips
  aggregations:
    skim_auto_time: sum
    skim_auto_distance: sum
    skim_transit_fare: sum
  directional_outputs:
    skim_auto_time: true
```

## Missing Data And Reports

During integrated prepare, skimjoin writes these report artifacts:

| Report | Purpose |
|---|---|
| `skim_lookup_summary` | Successful lookup counts and output summaries. |
| `missing_lookup_report` | Missing matrix, missing OD, missing dimension, and skipped lookup details. |
| `fallback_lookup_report` | Fallback attempts and outcomes. |
| `skipped_rule_report` | Rules skipped by missing source columns or other selection conditions. |
| `tour_aggregation_summary` | Tour lookup and aggregation details. |
| `failure_report` | Runtime failure detail when skimjoin cannot complete. |

Policies:

| Policy | Behavior |
|---|---|
| `error` | Treat the missing condition as a validation/runtime failure where enforced. |
| `warn` | Record warning/missing report rows and continue. |
| `set_null` | Write null for the missing value and continue. |

## Related Chapters

- [13 - Configuration Reference](13-configuration-reference.md#skimjoin)
- [22 - Skimjoin](22-skimjoin.md), including the standalone CLI
- [90 - Troubleshooting](90-troubleshooting.md)
