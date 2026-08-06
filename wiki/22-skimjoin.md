# 22 - Skimjoin

Skimjoin adds skim-derived columns to prepared trips and tours. This optional
final part of prepare runs after the raw output has been normalized.

Use skimjoin when summaries or dashboard pages require values from OMX skims or
sidecar lookup files. Examples are time, cost, distance, walk access, and direct
trip or tour attributes.

For each skimjoin field, lookup rule, default, and example, see
[23 - Skimjoin Config Reference](23-skimjoin-config-reference.md).

Integrated skimjoin uses two YAML files:

- the **main visualizer config** enables the step with `pipeline.steps` and
  selects the rules file. It can also supply shared or run-specific data paths.
- the **skimjoin rules file** defines prepared column names, defaults,
  dimensions, mode/component lookup rules, and fallbacks. Its optional
  `project` block supplies data paths for the standalone CLI or as integrated
  defaults.

Paths in the first file start from the main configuration file, while paths in
the second start from the standalone skimjoin configuration file. Providing a
configuration path does not enable the step; `pipeline.steps` must contain both
`prepare` and `skimjoin`.

## Where Path Settings Belong

For integrated use, the main config can own the skim paths while the skimjoin
file contains only reusable lookup rules. This is useful when several model
runs share rules but use different skim files.

Main visualizer config:

```yaml
pipeline:
  steps: [prepare, skimjoin, summarize, dashboard]

skimjoin:
  defaults:
    config_path: configs\skimjoin_rules.yaml
    skim_files:
      - skims\shared\*.omx
    network_los_file: skims\shared\network_los.yaml

runs:
  - dir: C:\models\base\output
    label: Base
  - dir: C:\models\build\output
    label: Build
    skimjoin:
      skim_files:
        - skims\build\*.omx
      network_los_file: skims\build\network_los.yaml
```

`configs\skimjoin_rules.yaml`:

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
    distance: SOV_DIST__{PERIOD}
```

In this pattern, `project` is not required. The integrated prepare workflow
already supplies trip and tour tables, and the main config supplies the skims.

Use `project` when the skimjoin file must be self-contained, especially for the
standalone CLI:

```yaml
project:
  skim_files:
    - C:\skims\*.omx
  network_los_file: C:\skims\network_los.yaml
  trips_table: C:\prepared\trips.parquet
  tours_table: C:\prepared\tours.parquet
  output_dir: C:\skimjoin_output
```

For integrated use, only `project.skim_files` and, when needed,
`project.network_los_file` are relevant. `project.trips_table`,
`project.tours_table`, and `project.output_dir` belong to the standalone CLI.

The effective integrated settings follow these rules:

1. `runs[*].skimjoin.config_path` replaces `skimjoin.defaults.config_path` for
   that run.
2. Main-config `skim_files` and `network_los_file` replace the corresponding
   `project` values in the selected rules file.
3. A run with no override block uses the fully resolved global defaults.
4. When a run override causes the rules file to be reloaded, any omitted skim
   or network path comes from that file. Repeat a required global path in the
   run block if the rules file does not contain it.
5. `network_los_file` is required only when
   `dimensions.PERIOD.values_from_network_los` is `true`.

For predictable overrides, keep integrated skim paths either in `project` or
in the main config, not in the skimjoin file's top-level `skim_files` field.
The top-level form is supported but takes precedence during config promotion
and can prevent a main-config skim override from replacing it.

## Runtime Placement

```text
prepare raw outputs
  -> canonical prepared trips and tours
  -> apply skimjoin rules
  -> enriched trips and tours
  -> prepared cache
  -> summaries
```

The runtime adapter is
[`processor/skimjoin/pipeline.py`](../processor/skimjoin/pipeline.py).

## How The Implementation Works

Integrated skimjoin has six main stages:

1. **Resolve one config per run.** The runtime selects the global or run-level
   rules file, applies path overrides, resolves paths, and validates the typed
   schema.
2. **Normalize rules.** Mode, segment, component, dimension, target-table,
   missing-data, and fallback settings become ordered trip and tour lookup
   rules. Strict validation can report output collisions and invalid fallback
   chains before annotation.
3. **Inventory skim inputs.** The runtime scans OMX, HDF5, and CSV inputs and
   records matrix names, qualified source names, shapes, lookup types, and key
   columns. Duplicate file-qualified references are invalid.
4. **Select rows for each rule.** A rule matches the configured trip or tour
   mode, then applies `when`, `segment_on`, target, and dimension conditions.
   Missing source columns can make a rule unusable and appear in diagnostics.
5. **Resolve and execute lookups.** Dimension values fill matrix-name
   placeholders. OD rules map origin and destination IDs through the configured
   OMX lookup; key rules read keyed sidecar values. Sentinel and missing-data
   policies determine whether invalid values fail, warn, or become null.
6. **Package enriched data and diagnostics.** Successful output columns replace
   the prepared `RunData.trips` and `RunData.tours` tables. The runtime stores a
   manifest, lookup reports, and optional hypothetical sidecars in the final
   prepared cache.

Fallback rules run in order only for rows that still lack a valid value. Rules
that write the same output can overlap only when all of them use
`combine: sum`; otherwise validation reports an output collision.

Tour lookups use two directional contexts derived from each prepared tour. The
inbound context swaps origin and destination fields, and dimension settings can
name separate outbound and inbound source columns. This produces direct tour
lookup outputs with `_outbound` and `_inbound` suffixes.

## Configuration sections

A skimjoin configuration contains these sections:

| Section | Purpose |
|---|---|
| `project` | Paths such as skim files and `network_los.yaml`. |
| `activitysim` | Source columns in prepared trips/tours. |
| `defaults` | Default origin, destination, output prefix, and missing-data policies. |
| `zone_mapping` | Optional zone lookup behavior. |
| `dimensions` | Time period or other dimensions used to resolve matrix names. |
| `ignore_modes` | Trip modes allowed to have no lookup rules. |
| `modes` | Mode-specific lookup rules. |

The optional `project` section contains paths, not lookup behavior. Main-config
defaults or run overrides can supply the integrated skim paths instead.

## Adding A Skim Output

Start with the [Basic OD Lookup](23-skimjoin-config-reference.md#basic-od-lookup)
for a complete mode rule. Add dimensions or fallback rules only when the new
output requires them.

Checklist:

1. Make sure prepared trips or tours contain the required lookup columns.
2. Add or update a lookup rule in the skimjoin config.
3. Select an output name. Use the `skim_` prefix unless the interface requires a different prefix.
4. Set the missing-matrix and missing-OD policies.
5. Add fallback lookup rules only when a valid fallback value is available.
6. Set `apply_to` when the component belongs only on trips or tours.
7. Add or update a summary in `processor/summarize/summaries/skimjoin.py` if the
   dashboard needs aggregate reporting.
8. Regenerate wiki catalogs if summary declarations or dashboard requirements
   changed.

Set `skimjoin.create_hypothetical_skim_tables: true` globally or in a run
override to create hypothetical skim sidecar tables. The default is `false`
because this option creates more output and artifacts.

Hypothetical sidecars rerun each configured mode's lookup rules against every
eligible observed row. They do not change the observed trip or tour mode and
do not replace the annotated prepared tables. They provide long-form values
for comparisons such as “what would this trip's auto time be under each
configured mode?”

| Trip sidecar field | Type | Meaning |
|---|---|---|
| `trip_id` | `Int64` | Prepared trip identifier. |
| `observed_mode` | string | Original configured trip mode. |
| `hypothetical_mode` | string | Mode whose rules produced the value. |
| `component` | string | Skim output column name. |
| `value` | `Float64` | Looked-up component value, or null. |
| `finalweight` | `Float64` | Prepared trip weight. |

The tour sidecar has the same structure with `tour_id` and one additional
`direction` field. `direction` is `outbound` or `inbound` when the component
ends with the corresponding suffix; it is null for unsuffixed outputs.
Sidecars are empty unless the prepared source contains the configured ID and
mode columns plus `finalweight`.

## Standalone Skimjoin CLI

The integrated pipeline is the standard approach. The standalone command-line
interface is useful for inspecting or validating a skimjoin configuration, or
for creating annotated tables without the full visualizer:

```bash
uv run python -m processor.skimjoin.cli COMMAND --config skimjoin.yaml
```

| Command | Additional flags | Output |
|---|---|---|
| `inventory` | `--preview` | Writes `skim_inventory.csv` and `inventory_debug.log` under `project.output_dir`. Preview also writes trip/tour column inventories and ActivitySim value counts when the configured tables are available. |
| `validate` | none | Strictly validates config, inventory, and configured ActivitySim tables; writes `config_normalized.yaml` and `validation_report.txt`. Returns exit code 1 and writes a failure report when validation fails. |
| `annotate-trips` | `--out PATH`, `--preview` | Writes annotated trips plus validation, lookup-summary, and missing-lookup artifacts. The default table is `<output_dir>/trips_with_skims.parquet`. |
| `annotate-tours` | `--out PATH`, `--preview` | Writes annotated tours and lookup diagnostics. The default table is `<output_dir>/tours_with_skims.parquet`. |
| `run` | `--out-trips PATH`, `--out-tours PATH`, `--preview` | Executes both annotations and writes their validation and QA reports. Uses the two file names above by default. |

Each command requires `--config`; output flags are optional only when
`project.output_dir` is configured. Standalone input tables come from
`activitysim.trips_table` and `activitysim.tours_table`. Chapter 23 describes
the legacy `project.trips_table` and `project.tours_table` fallback. Input and
output tables must be CSV or Parquet. For annotation commands, `--preview` adds
a short output-column inventory but does not limit rows or prevent writes.

## Debugging Skimjoin

First, examine these skimjoin artifacts for the prepared run:

- `skim_lookup_summary`
- `missing_lookup_report`
- `fallback_lookup_report`
- `skipped_rule_report`
- `failure_report`

Integrated artifacts are stored under
`<root>/<run-key>/prepared_tables/skimjoin/`. The prepared manifest records the
status, resolved rules/input identity, applied outputs, skipped rules,
warning/fallback counts, failure detail, and hypothetical sidecar row counts.
Chapter 23 gives the exact report schemas and concrete skim file layouts.

Common causes:

| Symptom | Check |
|---|---|
| No skim columns appear | `pipeline.steps`, resolved config path, run overrides, and skim file glob resolution. |
| Rule skipped | Source mode, `when` clause, ignored modes, and required dimensions. |
| Missing matrix | Matrix naming pattern, dimensions, network LOS periods, and OMX contents. |
| Missing OD values | Origin/destination columns, zone mapping, sentinel values, and missing OD policy. |
| Tours missing values | `apply_to`, tour mode, outbound/inbound source columns, dimensions, and OD columns. |

With `failure_policy: record`, an integrated failure keeps the original
prepared trips and tours, writes empty skim sidecars, and records a
`failure_report`. With `failure_policy: error`, the exception stops the run.

The prepared-cache identity includes the normalized skimjoin rules and resolved
skim inputs. A changed rules file or skim file invalidates skimjoin and later
summaries without requiring raw preparation to run again. Use
`refresh: [skimjoin]` to force that boundary while retaining
`base_prepared_tables`.

## Where To Change Code

| Task | Start here |
|---|---|
| Config shape or validation | `processor/skimjoin/config/schema.py` |
| Main/run override resolution | `runtime/config/normalize_skimjoin.py` |
| Config normalization | `processor/skimjoin/config/normalize.py` |
| Skim inventory | `processor/skimjoin/inventory.py` |
| Skim store behavior | `processor/skimjoin/skimstore/` |
| Trip annotation | `processor/skimjoin/annotate/trips.py` |
| Tour annotation | `processor/skimjoin/annotate/tours.py` |
| Runtime reports | `processor/skimjoin/runtime_reports.py` |
| Integrated execution | `processor/skimjoin/runtime_execution.py` |
| Skim summary tables | `processor/summarize/summaries/skimjoin.py` |

## Related Chapters

- [13 - Configuration Reference](13-configuration-reference.md#skimjoin)
- [23 - Skimjoin Config Reference](23-skimjoin-config-reference.md)
- [25 - Summary Functions](25-summary-functions.md)
- [90 - Troubleshooting](90-troubleshooting.md)
