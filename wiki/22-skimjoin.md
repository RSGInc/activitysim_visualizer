# 22 - Skimjoin

Skimjoin adds skim-derived columns to prepared trips and tours. This optional
final part of prepare runs after the raw output has been normalized.

Use skimjoin when summaries or dashboard pages require values from OMX skims or
sidecar lookup files. Examples are time, cost, distance, walk access, and
combined tour attributes.

For each skimjoin field, lookup rule, default, and example, see
[25 - Skimjoin Config Reference](25-skimjoin-config-reference.md).

Integrated skimjoin uses two YAML files:

- the **main visualizer config** enables the step with `pipeline.steps` and
  specifies files in `skimjoin.defaults` or run overrides; and
- the **standalone skimjoin config** defines `project`, `activitysim`,
  dimensions, mode/component lookup rules, fallbacks, and tour aggregation.

Paths in the first file start from the main configuration file, while paths in
the second start from the standalone skimjoin configuration file. Providing a
configuration path does not enable the step; `pipeline.steps` must contain both
`prepare` and `skimjoin`.

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

## Configuration sections

A skimjoin configuration contains these sections:

| Section | Purpose |
|---|---|
| `project` | Paths such as skim files and `network_los.yaml`. |
| `activitysim` | Source columns in prepared trips/tours. |
| `defaults` | Default origin, destination, output prefix, and missing-data policies. |
| `zone_mapping` | Optional zone lookup behavior. |
| `dimensions` | Time period or other dimensions used to resolve matrix names. |
| `modes` | Mode-specific lookup rules. |
| `tour_aggregation` | How trip skim values roll up to tours. |

Run overrides in the main visualizer configuration can change the skim files,
`network_los_file`, or skimjoin configuration path.

## Adding A Skim Output

Start with the [Basic OD Lookup](25-skimjoin-config-reference.md#basic-od-lookup)
for a complete mode rule. Add dimensions, fallback rules, or tour aggregation
only when the new output requires them.

Checklist:

1. Make sure prepared trips or tours contain the required lookup columns.
2. Add or update a lookup rule in the skimjoin config.
3. Select an output name. Use the `skim_` prefix unless the interface requires a different prefix.
4. Set the missing-matrix and missing-OD policies.
5. Add fallback lookup rules only when a valid fallback value is available.
6. If tours need the value, configure tour aggregation or directional outputs.
7. Add/update a summary in `processor/summarize/summaries/skimjoin.py` if the
   dashboard needs aggregate reporting.
8. Regenerate wiki catalogs if summary declarations or dashboard requirements
   changed.

Set `skimjoin.create_hypothetical_skim_tables: true` globally or in a run
override to create hypothetical skim sidecar tables. The default is `false`
because this option creates more output and artifacts.

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
| `annotate-tours` | `--out PATH`, `--preview` | Writes annotated tours, `tour_aggregation_summary.csv`, and `missing_lookup_report.csv`. The default table is `<output_dir>/tours_with_skims.parquet`. |
| `run` | `--out-trips PATH`, `--out-tours PATH`, `--preview` | Executes both annotations and writes their validation and QA reports. Uses the two file names above by default. |

Each command requires `--config`; output flags are optional only when
`project.output_dir` is configured. Standalone input tables come from
`activitysim.trips_table` and `activitysim.tours_table`. Chapter 25 describes
the legacy `project.trips_table` and `project.tours_table` fallback. Input and
output tables must be CSV or Parquet. For annotation commands, `--preview` adds
a short output-column inventory but does not limit rows or prevent writes.

## Debugging Skimjoin

First, examine these skimjoin artifacts for the prepared run:

- `skim_lookup_summary`
- `missing_lookup_report`
- `fallback_lookup_report`
- `skipped_rule_report`
- `tour_aggregation_summary`
- `failure_report`

Common causes:

| Symptom | Check |
|---|---|
| No skim columns appear | `pipeline.steps`, resolved config path, run overrides, and skim file glob resolution. |
| Rule skipped | Source mode, `when` clause, ignored modes, and required dimensions. |
| Missing matrix | Matrix naming pattern, dimensions, network LOS periods, and OMX contents. |
| Missing OD values | Origin/destination columns, zone mapping, sentinel values, and missing OD policy. |
| Tours missing values | Tour aggregation config and outbound/inbound source columns. |

## Where To Change Code

| Task | Start here |
|---|---|
| Config shape or validation | `processor/skimjoin/config/schema.py` |
| Config normalization | `processor/skimjoin/config/normalize.py` |
| Skim store behavior | `processor/skimjoin/skimstore/` |
| Trip annotation | `processor/skimjoin/annotate/trips.py` |
| Tour annotation | `processor/skimjoin/annotate/tours.py` |
| Runtime reports | `processor/skimjoin/runtime_reports.py` |
| Skim summary tables | `processor/summarize/summaries/skimjoin.py` |

## Related Chapters

- [13 - Configuration Reference](13-configuration-reference.md#skimjoin)
- [25 - Skimjoin Config Reference](25-skimjoin-config-reference.md)
- [23 - Summary Functions](23-summary-functions.md)
- [90 - Troubleshooting](90-troubleshooting.md)
