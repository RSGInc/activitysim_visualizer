# 15 - Cache And Manifest Reference

Prepared and summary caches are stored contracts, not temporary copies of
arbitrary files. Each cache directory has a `manifest.json` that records its
schema, inputs, configuration identity, table inventory, and diagnostics.

Do not edit a manifest by hand. Change the source data or configuration and let
the workflow rebuild the affected stage.

## Directory Layout

For run key `base`, the standard layout is:

```text
<root>/base/
  manifest.json                         # summary manifest
  summary_tables/
    weighted/<summary>.csv
    unweighted/<summary>.csv
    weighted/segments/<type>/<id>/<summary>.csv
  base_prepared_tables/                 # present when skimjoin is enabled
    manifest.json
    <prepared tables>
  prepared_tables/
    manifest.json                       # final prepared/skimjoin manifest
    <prepared tables>
    <hypothetical sidecars, if enabled>
    skimjoin/<reports>
```

Without skimjoin, prepare writes only `prepared_tables`. With skimjoin,
`base_prepared_tables` stores the reusable pre-skim boundary and
`prepared_tables` stores the enriched result.

## Prepared Manifest

The current prepared schema version is an implementation value. The loader can
read a limited set of earlier versions, but users should rely on the fields,
not a hard-coded version number. A shortened example is:

```json
{
  "schema_version": 11,
  "source": "activitysim-visualizer-prepared-cache",
  "label": "Base",
  "run_key": "base",
  "source_run_dir": "C:\\models\\base\\output",
  "prepare_config_digest": "...",
  "table_format": "parquet",
  "table_root": "prepared_tables",
  "table_files": {
    "households": "households.parquet",
    "persons": "persons.parquet",
    "tours": "tours.parquet",
    "trips": "trips.parquet"
  },
  "table_states": {
    "households": "available",
    "day": "unavailable"
  },
  "table_diagnostics": {
    "day": "Cannot find 'final_day.parquet' or 'final_day.csv' ..."
  },
  "run_fingerprint": {},
  "identity": {
    "raw_inputs": {},
    "prepare_config": "...",
    "skimjoin_config": null,
    "skim_inputs": []
  }
}
```

Important fields:

| Field | Meaning |
|---|---|
| `schema_version`, `source`, `generated_at_utc` | Storage format, producer, and write time. |
| `label`, `run_key`, `source_run_dir` | Display identity, cache identity, and raw source location. |
| `config_path`, `prepare_config_digest` | Configuration source and normalized prepare identity. |
| `table_format`, `table_root`, `table_files` | How to find each prepared table. |
| `sidecar_root`, `sidecar_files` | Optional hypothetical skim sidecar files. |
| `table_states`, `table_diagnostics` | Per-table `available`, `empty`, `unavailable`, or `failed` state and reason. |
| `unavailable_tables`, `failed_tables` | Compatibility views of the same table diagnostics. |
| `source_file_map`, `run_fingerprint` | Resolved raw input mapping, file identities, skims, run weights, and run-level overrides. |
| `identity` | Compact upstream identity used by later stages. |
| `hh_weight_col`, `person_weight_col`, `trip_weight_col`, `day_weight_col` | Primary run-level source weight fields. |
| `prepare_diagnostics` | Recorded preparation warnings and relationship results. |
| `skimjoin_*` | Enabled/status/config/input identity, applied outputs, skipped rules, warning/fallback counts, failure detail, and sidecar row counts. |

Every configured prepared table has an entry in `table_files`, including empty
or unavailable tables. Those tables are stored with the internal empty
sentinel and restored according to `table_states`.

## Summary Manifest

The run-level summary manifest covers the full run and every segment. A
shortened example is:

```json
{
  "schema_version": 15,
  "source": "activitysim-visualizer-summary-cache",
  "label": "Base",
  "run_key": "base",
  "summary_config_digest": "...",
  "weighting_modes": ["weighted", "unweighted"],
  "summary_ids": ["population_totals", "trip_mode_by_tour_purpose_and_tour_mode"],
  "summary_files": {
    "population_totals": "population_totals.csv"
  },
  "summary_states": {
    "weighted": {"population_totals": "available"}
  },
  "summary_diagnostics": {"weighted": {}},
  "summary_digests": {
    "weighted": {"population_totals": "..."}
  },
  "prepared_manifest_identity": {},
  "segmentation_enabled": true,
  "segmentation_types": []
}
```

Important fields:

| Field | Meaning |
|---|---|
| `schema_version`, `source`, `generated_at_utc` | Storage format, producer, and write time. |
| `label`, `run_key`, `source_run_dir` | Run identity and source location. |
| `summary_config_digest` | Normalized configuration that can affect summaries. |
| `weighting_modes` | Stored mode IDs in dashboard order. |
| `summary_ids`, `summary_files` | Registered IDs and their cache filenames. |
| `empty_summaries`, `summary_states` | Per-mode empty/state inventory. |
| `unavailable_summaries`, `failed_summaries`, `summary_diagnostics` | Per-mode problem inventory and explanations. |
| `summary_digests` | Per-mode declaration/implementation identity. It allows one changed builder to rebuild without discarding unrelated tables. |
| `run_fingerprint` | Run and external-summary input identity. |
| `prepared_manifest_identity` | Exact prepared source/config identity used by the summaries. |
| `identity` | Compact upstream-prepared and summary-config identity. |
| `segmentation_enabled`, `segmentation_types` | Stored analysis-unit definitions and segment metadata. |

Each entry in `segmentation_types` contains the definition name and source,
plus a `segments` list. Each segment records its ID, label, matched values,
source columns or CSV join, summary roots, states, diagnostics, and digests.

## What Makes A Cache Stale

The cache identity is intentionally stage-specific:

| Change | Earliest affected stage |
|---|---|
| Raw file path, size, or modification time | prepare |
| Raw file mapping, run weight fields, prepare enrichment settings | prepare |
| Skimjoin rules or resolved skim inputs | skimjoin |
| Geography mapping rows | prepare, then summarize |
| Segmentation definition or values | affected summary analysis units |
| Weighting definition or summary configuration | summarize |
| One summary declaration, builder location, schema, or requirements | that summary in each affected analysis unit |
| Dashboard labels, page selection, or layout | presentation only; no processor rebuild |

File identity uses resolved path, byte size, and nanosecond modification time.
It does not hash the full file contents. Replacing content while preserving all
three values can defeat automatic detection; use an explicit refresh in that
unusual case.

## Read `--explain-cache` Output

Run:

```bash
uv run activitysim-viz --config local_config.yaml --explain-cache
```

The command does not load tables, execute builders, create the cache root, or
start the dashboard. It prints one plan per run:

```text
Pipeline plan - Base
  prepare    REUSE
  skimjoin   DISABLED
  summarize  REBUILD - 1 analysis-unit summary tables are stale; 0 analysis units are obsolete
  dashboard  RUN
```

| Action | Meaning |
|---|---|
| `REUSE` | The stored manifest agrees with current identity and requirements. |
| `REBUILD` | The cache is missing, explicitly refreshed, stale, incompatible, or downstream of a rebuilding stage. The rest of the line gives the reason. |
| `RUN` | The non-persistent dashboard action will execute. |
| `DISABLED` | The logical step is not selected. |

A summarize `REBUILD` decision does not always mean every summary will run.
The summarize cache can reuse compatible tables and rebuild only stale summary
IDs or analysis units.

## Refresh Boundaries

Prefer the narrowest repeatable refresh:

```yaml
pipeline:
  refresh: [skimjoin]
```

| Refresh | Rebuilds | Keeps |
|---|---|---|
| `prepare` | raw prepare, enabled skimjoin, and summaries | nothing downstream |
| `skimjoin` | final skimjoined prepared cache and summaries | `base_prepared_tables` |
| `summarize` | full and segmented summaries | final prepared cache |
| `all` | every enabled stored stage | dashboard has no stored stage to refresh |

After a one-time diagnostic refresh, remove it or set `refresh: []` so normal
reuse resumes.

## Safe Inspection And Recovery

1. Run `--explain-cache` before deleting anything.
2. Read the manifest state and diagnostic fields.
3. Confirm the run key; duplicate normalized labels can add `-1`, `-2`, and so
   on.
4. Use `pipeline.refresh` when the cache is valid but you intentionally need a
   rebuild.
5. If a cache is corrupt, remove only the exact run/stage directory and rerun
   the selected workflow. A removed cache is recoverable only by rebuilding it.

Do not move one run's manifest into another run directory, copy tables without
their manifest, or change digests to force reuse. These actions bypass the
identity checks that protect cross-run comparisons.

## Related Chapters

- [12 - Running Workflows](12-running-workflows.md)
- [14 - Input Data Contract](14-input-data-contract.md)
- [21 - Prepared Tables](21-prepared-tables.md)
- [24 - Segmentation](24-segmentation.md)
- [90 - Troubleshooting](90-troubleshooting.md)
