# Summary and Dashboard Workflow

This project now has five logical pipeline steps in config:

1. `prepare`
2. `skimjoin`
3. `summarize`
4. `segment`
5. `dashboard`

At runtime those currently collapse into three executable workflow boundaries:
`prepare`, `summarize`, and `dashboard`. `skimjoin` runs inside prepare, and
`segment` runs inside summarize.

Those steps can be selected explicitly from CLI flags or supplied as defaults in
`pipeline.steps` within the YAML config.

Understanding which workflow you are in makes the rest of the codebase much easier to follow.

## Effective Plan Resolution

`run.py` resolves execution in this order:

1. Load config and normalize any legacy keys to the canonical config schema.
2. Start from `pipeline.steps` when CLI step flags are absent.
3. Apply CLI overrides such as `--prepare-only`, `--summarize`, `--dashboard`,
   `--from-csvs`, and `--no-dashboard`.
4. Collapse logical steps into runtime workflow boundaries.
5. Resolve dashboard mode from CLI first, then `pipeline.dashboard_mode`.

`pipeline.overwrite: true` changes the default cache preference for selected
workflow steps, while explicit refresh flags still force cache deletion and
rebuild behavior.

Dashboard mode supports:

- `none`: do not run dashboard
- `live`: build/serve the live Panel app
- `export`: write standalone HTML
- `host`: reserved for future hosted deployment behavior; current runtime falls back to live mode

## Step 1: Prepare

Typical command:

```bash
python run.py --prepare-only
```

High-level path:

1. `run.py` parses CLI flags.
2. `runtime.workflows.resolve_run_entries()` chooses run inputs from CLI or config.
3. `runtime.workflows.run_prepare_workflow()` tries prepared-cache reuse first.
4. If a run defines `prepared_table_map`, the workflow loads those canonical prepared tables directly and skips raw prepare.
   This path is intended for already-prepared, already-skimjoined tables that may have been filtered or post-processed outside this repo.
5. Otherwise, on a miss, raw runs are read by `processor.prepare.reader` and normalized by `processor.prepare.enrichment.pipeline`.
6. After any prepared run is loaded, the workflow optionally validates cross-table key relationships according to `prepare.validation.relationship_checks` (`warn` by default).
7. `processor.prepare.cache.write_prepared_run_cache()` writes one prepared cache directory per raw-derived run.

Integrated skimjoin, when enabled through `pipeline.steps`, legacy
`skimjoin.enabled`, or run/global skimjoin config, runs against those prepared
tables. That now includes a prepared tour column named
`first_inbound_trip_depart`, derived from the first inbound trip on each tour so
inbound tour PERIOD lookups do not reuse the outbound tour start time.

Prepared cache layout:

```text
<prepared_root>/
  <run_key>/
    manifest.json
    households.parquet|csv
    persons.parquet|csv
    tours.parquet|csv
    trips.parquet|csv
    joint_tour_participants.parquet|csv
    land_use.parquet|csv
```

The standard prepare workflow writes parquet by default, but `prepare.output.file_format`
may switch prepared-cache output to CSV. Custom `prepared_table_map` inputs may also
mix `.parquet` and `.csv` files within the same run because they are loaded directly,
not rewritten into prepared cache in v1. They also do not rerun integrated skimjoin;
if you need skim outputs in that path, they should already exist in the supplied
prepared tables.

Skimjoin source-column selection is explicit in the skimjoin config:

- `activitysim.trip_mode_column` and `activitysim.trip_id_column` control trip lookup inputs
- `activitysim.tour_mode_column` and `activitysim.tour_id_column` control tour lookup inputs
- `dimensions.<NAME>.source_columns.trip_source_column` controls trip placeholder resolution
- `dimensions.<NAME>.source_columns.outbound_tour_source_column` controls outbound tour placeholder resolution
- `dimensions.<NAME>.source_columns.inbound_tour_source_column` controls inbound tour placeholder resolution

For the shared zone columns used by skimjoin defaults and common overrides:

- prepare always materializes `OTAZ` and `DTAZ` on trips and tours
- if `zones.use_maz: true`, prepare also materializes `o_maz` and `d_maz`
- inbound tours reuse those same prepared columns, while skimjoin swaps lookup direction logically in the inbound tour context

## Step 2: Summarize

Typical command:

```bash
python run.py --summarize
```

High-level path:

1. `run.py` resolves the summarize step.
2. `runtime.workflows.run_summary_workflow()` tries summary-cache reuse first.
3. On a summary-cache miss, summarize reuses in-memory prepared runs, then loads custom `prepared_table_map` inputs when configured, then tries prepared cache, then rebuilds prepare from raw inputs only if needed.
4. `processor.summarize.cache.build_mode_summaries_with_metadata()` builds weighted and optionally unweighted tables.
5. If a run defines `summary_table_map`, those dashboard-ready summary files are loaded and overlaid on the generated summaries for the listed summary IDs.
6. `processor.summarize.cache.write_summary_run_cache()` writes one cache directory per run unless `--skip-summary-cache-write` is set.
7. If segmentation is enabled, summary generation also builds segment-specific
   analysis units within this same workflow boundary.

Cache layout:

```text
<summary_root>/
  <run_key>/
    manifest.json
    weighted/
      <summary_file>.csv
    unweighted/
      <summary_file>.csv
```

`manifest.json` is important. Prepared manifests record the schema version, prepare-config digest, run fingerprint, table file mapping, and per-table state/diagnostic metadata. Summary manifests record the schema version, summary ids, weighting modes, summary file mapping, run fingerprint, summary-config digest, and per-summary state/diagnostic metadata used to validate whether a cache is still safe to reuse.

The summarize step also records the prepared-manifest identity it was built from, so summary caches are explicitly layered on top of prepared inputs rather than raw-run assumptions.
That prepared-input identity now covers both standard prepared caches and user-supplied `prepared_table_map` inputs, so summary reuse is invalidated when external prepared files change.

Summary building is now best-effort per summary. Each registered builder can declare a typed output contract and safe prerequisite metadata. The cache layer uses that contract to:

- skip impossible summaries before calling the builder
- write typed empty fallback tables for `empty`, `unavailable`, or `failed` summaries
- continue building the rest of the summary set for the run
- record explicit summary states in the manifest so empty outputs do not hide why they were empty

## Step 3: Dashboard

Typical cache-backed command:

```bash
python run.py --from-csvs
```

High-level path:

1. `run.py` loads config and resolves the effective plan.
2. `runtime.workflows.load_summary_runs_from_cache()` reads each cache directory and validates its manifest, or loads configured `summary_table_map` files directly for summary-only runs.
3. `dashboard.page_registry` resolves the enabled live pages from config.
4. `dashboard.app.build_dashboard()` builds the shared `DashboardState`, the sidebar controls, and the page controllers.
5. Each page pulls one summary table per run from `DashboardState`.

Important behavior:

- Summary-backed pages do not rebuild summary tables.
- Dashboard-only runs can now load summary caches either from explicit
  `--from-csvs` directories or from the configured runs when the summarize step
  is omitted.
- `--from-csvs` still means visualizer summary-cache directories with manifests.
  Loose dashboard-ready CSV/parquet files should be configured with
  `runs[*].summary_table_map`.
- If an enabled page requires disaggregate tables, `run.py` loads prepared runs for that page set from memory, custom `prepared_table_map` inputs, prepared cache, or the prepare workflow.
- Most pages should stay summary-backed and declare their requirements through `PAGE.required_summary_ids`.
- Prepared-data pages must also declare `PAGE.required_prepared_tables`, which lets the workflow prune unused prepared tables before dashboard startup/export.

When you want one invocation to do both processor work and dashboard startup, run
the steps explicitly together:

```bash
python run.py --summarize --dashboard
```

`python run.py` can also follow `pipeline.steps` from config when no CLI step
flags are supplied.

## Standalone HTML Export

Typical command:

```bash
python run.py --from-csvs --export-html output.html
```

Config-driven export is also supported with `pipeline.dashboard_mode: export`,
with the output path coming from `dashboard.export.output_path` when present.
Relative export output paths resolve from `root`.

High-level path:

1. `runtime.workflows.load_summary_runs_from_cache()` loads the same summary inputs used by live mode.
2. `dashboard.page_registry` resolves the export page set.
3. `dashboard.export.html.build_export_html_document()` creates a client-side payload that contains:
   - dashboard-level state combinations
   - serialized page content
   - selector metadata for export-enabled page widgets
4. The export runtime swaps between pre-rendered states in the browser without requiring a Python server.

Important behavior:

- Export never computes missing summaries.
- Export only supports page-local widget behavior that has been registered through `DashboardPage.selector(...)`.
- A live page can render correctly and still be only partially exportable if its selectors or sections are not registered with the public `DashboardPage` authoring API.

## Weighted vs Unweighted

The summary cache layer supports two weighting modes:

- `weighted`: uses the prepared `finalweight` column as-is
- `unweighted`: uses `strip_weights()` to reset `finalweight` to `1.0` before building summaries

Summary builders should always aggregate `finalweight` rather than switching behavior internally based on mode. That keeps weighting behavior centralized in `processor/summarize/cache.py`.

## Where New Contributors Usually Need to Look

| Question | Start here |
|---|---|
| How are runs loaded and normalized? | `processor/prepare/reader.py`, `processor/prepare/enrichment/pipeline.py` |
| Why was a prepared or summary cache reused or rejected? | `runtime/workflows/`, `processor/prepare/cache.py`, `processor/summarize/cache.py` |
| Which summary ids exist? | `processor/summarize/summary_specs.py` |
| Which output columns are considered canonical? | `processor/summarize/schema.py`, derived from builder contracts |
| How does a page get discovered? | `dashboard/page_registry.py` |
| How does export know about page-local selectors? | `dashboard/page_base.py`, `dashboard/export/payload.py`, `dashboard/export/serializer.py` |

For prepare internals, the enrichment package is now split by responsibility:

- `processor/prepare/enrichment/columns.py` for source-column resolution helpers
- `processor/prepare/enrichment/canonicalize.py` for raw-to-canonical field materialization
- `processor/prepare/enrichment/weights.py` for `finalweight` assignment
- `processor/prepare/enrichment/zones.py` for MAZ/TAZ, geography, and skim helpers
- `processor/prepare/enrichment/pipeline.py` for the public `prepare_data()` orchestration entrypoint

## Related Guides

- [architecture.md](architecture.md)
- [adding-summaries.md](adding-summaries.md)
- [adding-dashboard-pages.md](adding-dashboard-pages.md)
- [export_html_schema.md](export_html_schema.md)
- [export_html_contributor_guide.md](export_html_contributor_guide.md)
