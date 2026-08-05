# 22 - Skimjoin

Skimjoin enriches prepared trips and tours with skim-derived columns. It runs as
an optional late-prepare step after raw outputs have been normalized.

Use skimjoin when summaries or dashboard pages need values from OMX skims or
sidecar lookup files, such as time, cost, distance, walk access, or composed
tour-level attributes.

For full field-by-field skimjoin config options, lookup-rule grammar, defaults,
and examples, see
[25 - Skimjoin Config Reference](25-skimjoin-config-reference.md).

Two YAML files participate in integrated use:

- the **main visualizer config** enables the stage with `pipeline.steps` and
  points at files through `skimjoin.defaults` or per-run overrides; and
- the **standalone skimjoin config** defines `project`, `activitysim`,
  dimensions, mode/component lookup rules, fallbacks, and tour aggregation.

Paths in the first file resolve from the main config; paths owned by the second
resolve from the standalone skimjoin config. Supplying a config path alone does
not enable the stage—`pipeline.steps` must contain `prepare` and `skimjoin`.

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

## Config Anatomy

A skimjoin config describes:

| Section | Purpose |
|---|---|
| `project` | Paths such as skim files and `network_los.yaml`. |
| `activitysim` | Source columns in prepared trips/tours. |
| `defaults` | Default origin, destination, output prefix, and missing-data policies. |
| `zone_mapping` | Optional zone lookup behavior. |
| `dimensions` | Time period or other dimensions used to resolve matrix names. |
| `modes` | Mode-specific lookup rules. |
| `tour_aggregation` | How trip skim values roll up to tours. |

Per-run overrides in the main visualizer config can change selected skim files,
`network_los_file`, or the whole skimjoin config path.

## Adding A Skim Output

Start with the [Basic OD Lookup](25-skimjoin-config-reference.md#basic-od-lookup)
for a complete mode rule, then add dimensions, fallbacks, or tour aggregation
only when the new output requires them.

Checklist:

1. Confirm the prepared trips/tours contain the source columns needed for lookup.
2. Add or update a lookup rule in the skimjoin config.
3. Choose the output name and keep the `skim_` prefix convention unless there is
   a strong reason not to.
4. Set missing matrix and missing OD policies deliberately.
5. Add fallback lookup rules only when a real fallback is meaningful.
6. If tours need the value, configure tour aggregation or directional outputs.
7. Add/update a summary in `processor/summarize/summaries/skimjoin.py` if the
   dashboard needs aggregate reporting.
8. Regenerate wiki catalogs if summary declarations or dashboard requirements
   changed.

Set `skimjoin.create_hypothetical_skim_tables: true` (globally or in a run
override) when the configured lookups should also produce hypothetical skim
sidecar tables. This is opt-in because it adds output work and artifacts.

## Standalone Skimjoin CLI

The integrated pipeline is the normal visualizer path. A standalone CLI is
also available for inspecting and validating a skimjoin config or producing
annotated tables without running the full visualizer:

```bash
uv run python -m processor.skimjoin.cli COMMAND --config skimjoin.yaml
```

| Command | Additional flags | Output |
|---|---|---|
| `inventory` | `--preview` | Writes `skim_inventory.csv` and `inventory_debug.log` under `project.output_dir`. Preview also writes trip/tour column inventories and ActivitySim value counts when the configured tables are available. |
| `validate` | none | Strictly validates config, inventory, and configured ActivitySim tables; writes `config_normalized.yaml` and `validation_report.txt`. Returns exit code 1 and writes a failure report when validation fails. |
| `annotate-trips` | `--out PATH`, `--preview` | Writes annotated trips plus validation, lookup-summary, and missing-lookup artifacts. The default table is `<output_dir>/trips_with_skims.parquet`. |
| `annotate-tours` | `--out PATH`, `--preview` | Writes annotated tours, `tour_aggregation_summary.csv`, and `missing_lookup_report.csv`. The default table is `<output_dir>/tours_with_skims.parquet`. |
| `run` | `--out-trips PATH`, `--out-tours PATH`, `--preview` | Runs both annotations and writes their validation/QA reports. Defaults to the two filenames above. |

`--config` is required for every command. Output flags are optional only when
`project.output_dir` is configured. Standalone table inputs come from
`activitysim.trips_table` and `activitysim.tours_table`, with the legacy
`project.trips_table`/`project.tours_table` fallback described in chapter 25.
Input and output tables must be CSV or Parquet. `--preview` on annotation
commands adds a compact output-column inventory; it does not limit rows or
make the command a dry run.

## Debugging Skimjoin

Start with the skimjoin artifacts on the prepared run:

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
