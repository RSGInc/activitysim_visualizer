# Summary and Dashboard Workflow

This project now exposes three explicit execution steps:

1. `prepare`
2. `summarize`
3. `dashboard`

Those steps can be run on their own or combined in one invocation.

Understanding which workflow you are in makes the rest of the codebase much easier to follow.

## Step 1: Prepare

Typical command:

```bash
python run.py --prepare-only
```

High-level path:

1. `run.py` parses CLI flags.
2. `runtime_workflows.resolve_run_entries()` chooses run inputs from CLI or config.
3. `runtime_workflows.run_prepare_workflow()` tries prepared-cache reuse first.
4. On a miss, raw runs are read and normalized in `runtime/run_data.py`.
5. `processor.prepare.write_prepared_run_cache()` writes one prepared cache directory per run.

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

## Step 2: Summarize

Typical command:

```bash
python run.py --summarize
```

High-level path:

1. `run.py` resolves the summarize step.
2. `runtime_workflows.run_summary_workflow()` tries summary-cache reuse first.
3. On a summary-cache miss, summarize reuses in-memory prepared runs, then tries prepared cache, then rebuilds prepare from raw inputs only if needed.
4. `processor.summarize.cache.build_mode_summaries()` builds weighted and optionally unweighted tables.
5. `processor.summarize.cache.write_summary_run_cache()` writes one cache directory per run unless `--skip-summary-cache-write` is set.

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

`manifest.json` is important. It records the schema version, summary ids, weighting modes, summary file mapping, run fingerprint, and summary-config digest used to validate whether a cache is still safe to reuse.

The summarize step also records the prepared-manifest identity it was built from, so summary caches are explicitly layered on top of prepared inputs rather than raw-run assumptions.

## Step 3: Dashboard

Typical command:

```bash
python run.py --from-csvs
```

High-level path:

1. `run.py` loads config.
2. `runtime_workflows.load_summary_runs_from_cache()` reads each cache directory and validates its manifest.
3. `dashboard.page_registry` resolves the enabled live pages from config.
4. `dashboard.app.build_dashboard()` builds the shared `DashboardState`, the sidebar controls, and the page controllers.
5. Each page pulls one summary table per run from `DashboardState`.

Important behavior:

- Summary-backed pages do not rebuild summary tables.
- If an enabled page requires disaggregate tables, `run.py` loads prepared runs for that page set from memory, prepared cache, or the prepare workflow.
- Most pages should stay summary-backed and declare their requirements through `PAGE.required_summary_ids`.

When you want one invocation to do both processor work and dashboard startup, run the steps explicitly together:

```bash
python run.py --summarize --dashboard
```

`python run.py` currently remains a compatibility shortcut for that same combination.

## Standalone HTML Export

Typical command:

```bash
python run.py --from-csvs --export-html output.html
```

High-level path:

1. `runtime_workflows.load_summary_runs_from_cache()` loads the same summary inputs used by live mode.
2. `dashboard.page_registry` resolves the export page set.
3. `dashboard.export_html.build_export_html_document()` creates a client-side payload that contains:
   - dashboard-level state combinations
   - serialized page content
   - selector metadata for export-enabled page widgets
4. The export runtime swaps between pre-rendered states in the browser without requiring a Python server.

Important behavior:

- Export never computes missing summaries.
- Export only supports widget behavior that has been explicitly declared through `PageSelectorDefinition`.
- A live page can render correctly and still be only partially exportable if its selectors are not declared in `PAGE.selectors`.

## Weighted vs Unweighted

The summary cache layer supports two weighting modes:

- `weighted`: uses the prepared `finalweight` column as-is
- `unweighted`: uses `strip_weights()` to reset `finalweight` to `1.0` before building summaries

Summary builders should always aggregate `finalweight` rather than switching behavior internally based on mode. That keeps weighting behavior centralized in `processor/summarize/cache.py`.

## Where New Contributors Usually Need to Look

| Question | Start here |
|---|---|
| How are runs loaded and normalized? | `runtime/run_data.py` |
| Why was a prepared or summary cache reused or rejected? | `runtime_workflows.py`, `processor/prepare/cache.py`, `processor/summarize/cache.py` |
| Which summary ids exist? | `processor/summarize/cache.py` |
| Which output columns are considered canonical? | `processor/summarize/schema.py` |
| How does a page get discovered? | `dashboard/page_registry.py` |
| How does export know about page-local selectors? | `dashboard/page_definitions.py`, `dashboard/export_html.py` |

## Related Guides

- [architecture.md](architecture.md)
- [adding-summaries.md](adding-summaries.md)
- [adding-dashboard-pages.md](adding-dashboard-pages.md)
