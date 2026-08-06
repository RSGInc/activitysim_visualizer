# 23 - Skimjoin Config Reference

This page is a field-by-field reference for the standalone skimjoin
configuration used by the main visualizer. For a workflow introduction, read
[22 - Skimjoin](22-skimjoin.md). For a complete self-contained example that
also supports the standalone CLI, see
[`example_skimjoin_config.yaml`](../example_skimjoin_config.yaml).

The skimjoin configuration answers four questions:

1. Which skim files and optional `network_los.yaml` must skimjoin use?
2. Which prepared trip and tour columns supply modes, IDs, dimensions, and OD
   lookup columns?
3. Which matrix or sidecar table must skimjoin read for each mode and component?
4. Which policy applies when matrices, OD pairs, or dimension values are missing?

## Choose Where Paths Live

The standalone skimjoin file always defines lookup behavior. Its `project`
section is optional for integrated visualizer use because the main config can
supply the data paths.

| Use case | Put paths here |
|---|---|
| Integrated workflow with shared paths | `skimjoin.defaults` in the main visualizer config. |
| Integrated workflow with paths that differ by run | `runs[*].skimjoin` in the main visualizer config. |
| Self-contained skimjoin file or standalone CLI | `project` in the skimjoin config. |

For integrated use, the effective config must have at least one skim file. A
`network_los_file` is required only when
`dimensions.PERIOD.values_from_network_los` is `true`. The integrated workflow
supplies prepared trip and tour tables, so it does not need
`project.trips_table`, `project.tours_table`, or `project.output_dir`.

Main visualizer config with shared paths:

```yaml
pipeline:
  steps: [prepare, skimjoin, summarize, dashboard]

skimjoin:
  defaults:
    config_path: configs\skimjoin_rules.yaml
    skim_files:
      - skims\*.omx
    network_los_file: skims\network_los.yaml
```

The referenced rules file can then omit `project`:

```yaml
activitysim:
  trip_mode_column: trip_mode
  tour_mode_column: tour_mode
  trip_id_column: trip_id
  tour_id_column: tour_id
  outbound_column: outbound

defaults:
  origin: OTAZ
  destination: DTAZ

modes:
  SOV:
    time: SOV_TIME
    distance: SOV_DIST
```

Main-config paths resolve from the main config directory. Paths in `project`
resolve from the skimjoin file's directory.

Main-config skim and network paths replace the corresponding `project` values.
Avoid the standalone top-level `skim_files` field when you need this override
behavior. If that top-level field is present, config promotion keeps it instead
of the injected `project.skim_files` value.

Run overrides have one additional rule: a run with no override block uses the
complete global resolution, but a run-specific override reloads the selected
skimjoin file. Any skim or network path omitted from that run block then comes
from the selected skimjoin file. Repeat a required global path in the run block
when the file does not contain it.

## Common Recipes

### Basic OD Lookup

```yaml
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

`time: SOV_TIME` is equivalent to:

```yaml
time:
  matrix: SOV_TIME
```

When multiple skim files contain the same matrix name, qualify the reference
with its source filename. For example, set the files in the main config:

```yaml
skimjoin:
  defaults:
    skim_files:
      - C:\skims\bike_commute.omx
      - C:\skims\bike_noncommute.omx
```

In the skimjoin rules file:

```yaml
modes:
  BIKE:
    distance:
      matrix: "bike_commute.omx::distance"
```

Unqualified references continue to work when the matrix name is unique across
the configured skim files. An ambiguous unqualified reference fails validation
and lists the available qualified names. Filename-qualified references may also
contain dimension placeholders.

### Period Dimension Lookup

The main config can supply both paths:

```yaml
skimjoin:
  defaults:
    skim_files:
      - C:\skims\auto.omx
    network_los_file: C:\skims\network_los.yaml
```

The rules file defines how to use `network_los.yaml`:

```yaml
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

Fallbacks run after the primary lookup and apply only to rows that do not yet
have a valid value. Every fallback step uses the same final output column.

## Top-Level Sections

| Section | Type | Default | Purpose |
|---|---|---|---|
| `project` | mapping | optional | Skim paths and standalone CLI paths. |
| `skim_files` | list | required after path resolution | Compatibility input promoted from `project.skim_files`. Prefer main-config paths for integrated use and `project.skim_files` for standalone use. |
| `activitysim` | mapping | required | Prepared trip/tour source column names. |
| `defaults` | mapping | built-in lookup defaults | Origin, destination, output prefix, missing-data policy, and sentinels. |
| `zone_mapping` | mapping | no mapping name | OMX zone lookup name behavior. |
| `dimensions` | mapping | `{}` | Placeholder definitions for matrix names. |
| `ignore_modes` | list | `[]` | Trip modes allowed to have no lookup rules. |
| `modes` | mapping | required | Mode-specific lookup rules. |

The Pydantic schema rejects unknown keys in typed sections.

## `project`

`project` is a path container. It is not required when the main visualizer
config supplies all paths needed by the integrated workflow.

| Field | Type | Default | Notes |
|---|---|---|---|
| `skim_files` | list of path strings | `[]` | OMX, CSV, HDF5, or H5 skim inputs. Required when the main visualizer config does not supply them, and required by the standalone `inventory` command. |
| `network_los_file` | path string | none | ActivitySim `network_los.yaml`, used when `dimensions.PERIOD.values_from_network_los` is true. |
| `trips_table` | path string | none | Standalone CLI input fallback. The integrated workflow ignores it. Prefer `activitysim.trips_table` for standalone use. |
| `tours_table` | path string | none | Optional standalone CLI input fallback. The integrated workflow ignores it. |
| `output_dir` | path string | none | Required by standalone `inventory`; used as the default output location for other CLI commands. The integrated workflow ignores it. |

```yaml
project:
  skim_files:
    - C:\skims\*.omx
    - C:\skims\maz_stop_walk.csv
  network_los_file: C:\skims\network_los.yaml
  trips_table: C:\prepared\trips.parquet
  tours_table: C:\prepared\tours.parquet
  output_dir: C:\skimjoin_output
```

For the standalone `validate`, `annotate-trips`, `annotate-tours`, and `run`
commands, a trips table must resolve through `activitysim.trips_table` or the
legacy `project.trips_table`. A tours table is optional unless the requested
operation needs tour input. Output flags can replace `project.output_dir` for
annotation commands.

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

Each mode, segment, and component inherits these defaults. A value closer to
the rule takes precedence.

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
| `values_from_network_los` | boolean | `false` | Only supported for `PERIOD`. Requires an effective `network_los_file` from the main config or `project`. |
| `values` | mapping | `{}` | Raw source value to matrix-name token. The loader normalizes keys and values to strings. |

If `values` is empty, skimjoin converts the raw source value to a string and
inserts it into the matrix name. If `values` is present, every observed value
must have a mapping.

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

`ignore_modes` lists trip modes that do not need skim enrichment and therefore
do not require a matching `modes` rule.

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
| `matrix` | string | required | matrix/table value name | Matrix name, `filename::matrix` reference, or template using `{DIMENSION}` placeholders. |
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
on all affected rules. Without this setting, validation reports an output
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
column. Skimjoin adds the corresponding `when` filter for each segment.

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

Validation checks that every observed value for a covered mode has a segment
block.

## `fallbacks`

Fallback entries use the same string or mapping format as primary component
rules. Skimjoin tries them in list order after a previous step fails. A fallback
uses the parent component output unless it sets its own, and all steps in the
chain must use the same final output.

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
structure and can also identify origin and destination columns. For OMX files,
OD lookups use the configured `zone_mapping` lookup name.

```yaml
modes:
  WALK:
    terminal_walk:
      lookup: key
      key_column: MAZ
      matrix: walk_dist_local_bus
      output: skim_walk_dist
```

### Concrete CSV Layouts

A keyed CSV uses its first column as the key and every later numeric column as
a separate inventory value:

```csv
MAZ,terminal_walk,parking_cost
101,2.5,4.00
102,1.8,6.50
```

If the file is `maz_access.csv`, its inventory names are
`maz_access__terminal_walk` and `maz_access__parking_cost`. A key rule can use:

```yaml
terminal_walk:
  lookup: key
  key_column: origin
  matrix: maz_access__terminal_walk
```

An OD CSV is recognized only when its first two normalized headers form one of
these pairs: `origin`/`destination`, `otaz`/`dtaz`, `omaz`/`dmaz`,
`orig`/`dest`, or `from`/`to`. Every later numeric column becomes a separate OD
table:

```csv
OTAZ,DTAZ,time,distance
1,1,0.0,0.0
1,2,12.5,8.1
2,1,13.0,8.1
2,2,0.0,0.0
```

For `auto_md.csv`, refer to these values as `auto_md__time` and
`auto_md__distance`. CSV rows need not form a complete square matrix; an
unlisted pair follows the configured missing-OD policy. Non-numeric columns
after the key or OD pair are ignored by the inventory.

### OMX, HDF5, And H5 Layouts

Skimjoin inventories every two-dimensional dataset in `.omx`, `.h5`, and
`.hdf5` files. The inventory records the full dataset path but uses the final
path component as its unqualified matrix name. For example, dataset
`/data/SOV_TIME` is referred to as `SOV_TIME` when unique. If more than one
file exposes that name, use `filename.omx::SOV_TIME`.

OD matrix row and column positions are resolved with the selected OMX mapping.
Set `zone_mapping.lookup_name`, or use `file_lookup_names` when files use
different mappings. Matrix dimensions and mapping positions must agree; a
missing zone follows `zone_mapping.missing_zone_policy`.

## Trip And Tour Rules

By default, each component creates trip and tour lookup rules:

| Target | Source mode column | Dimension source | Output name |
|---|---|---|---|
| Trips | `activitysim.trip_mode_column` | `trip_source_column` | `output` |
| Outbound tours | `activitysim.tour_mode_column` | `outbound_tour_source_column` | `output_outbound` |
| Inbound tours | `activitysim.tour_mode_column` | `inbound_tour_source_column` | `output_inbound` |

Set `apply_to: trips` or `apply_to: tours` to run a component on only one target
table.

## Missing Data And Reports

During integrated prepare, skimjoin writes these report artifacts:

| Report | Purpose |
|---|---|
| `skim_lookup_summary` | Successful lookup counts and output summaries. |
| `missing_lookup_report` | Missing matrix, missing OD, missing dimension, and skipped lookup details. |
| `fallback_lookup_report` | Fallback attempts and outcomes. |
| `skipped_rule_report` | Rules skipped by missing source columns or other selection conditions. |
| `failure_report` | Runtime failure detail when skimjoin cannot complete. |

The files are under
`<root>/<run-key>/prepared_tables/skimjoin/`. They are CSV except for the
resolved `config_normalized.yaml`. Empty reports are still written with their
declared headers when the integrated run reaches report packaging.

### Report Schemas

| Report | Columns |
|---|---|
| `skim_lookup_summary` | `rule_name`, `mode`, `component`, `output`, `matrix_name`, `n_trips`, `origin_column`, `destination_column`, `mean_value`, `min_value`, `max_value`, `n_missing` |
| `missing_lookup_report` | `rule_name`, `trip_id`, `origin`, `destination`, `matrix_name`, `reason` |
| `skipped_rule_report` | `rule_name`, `reason`, `n_rows` |
| `fallback_lookup_report` | `table_name`, `rule_name`, `output`, `logical_id`, `direction`, `primary_matrix_name`, `fallback_matrix_name`, `fallback_step_index`, `fallback_reason`, `fallback_eligible`, `fallback_attempted`, `fallback_succeeded`, `fallback_exhausted` |
| `failure_report` | `stage`, `error_type`, `detail` |

`n_trips` is the number of lookup rows covered by a rule/matrix combination,
including invalid results; `n_missing` is the invalid subset. In the fallback
report, `logical_id` is the trip or tour ID named by `table_name`, and
`direction` is populated for directional tour work. The `reason` and
`fallback_reason` strings are diagnostic codes/details; treat them as
diagnostics rather than a stable category enumeration for downstream data
exchange.

The final prepared manifest also stores compact run-level fields:

| Manifest field | Meaning |
|---|---|
| `skimjoin_status` | Completed, recorded failure, or other packaged execution state. |
| `skimjoin_config_digest` | Identity of normalized lookup behavior. |
| `skimjoin_resolved_network_los_file` | Effective network LOS path, if used. |
| `skimjoin_applied_outputs` | Enriched trip/tour output names. |
| `skimjoin_skipped_rules` | Compact skipped-rule records. |
| `skimjoin_warning_count`, `skimjoin_fallback_count` | Aggregate diagnostic counts. |
| `skimjoin_fallback_outputs` | Outputs that used fallback values. |
| `skimjoin_failure_detail` | Recorded exception detail under record policy. |

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
