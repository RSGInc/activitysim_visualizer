# Summary and Dashboard Workflow

This project supports three closely related workflows:

1. Raw ActivitySim outputs -> summary cache
2. Summary cache plus optional raw runs -> live dashboard
3. Summary cache -> standalone HTML export

Understanding which workflow you are in makes the rest of the codebase much easier to follow.

## Workflow 1: Build or Refresh Summary Caches

Typical command:

```bash
python run.py --write-csvs --no-dashboard
```

High-level path:

1. `run.py` parses CLI flags.
2. `runtime_workflows.resolve_run_entries()` chooses run inputs from CLI or config.
3. `runtime_workflows.run_summary_workflow()` tries cache-first or raw-run-first execution depending on flags.
4. Raw runs are read and normalized in `runtime/run_data.py`.
5. `summarize.cache.build_mode_summaries()` builds weighted and optionally unweighted tables.
6. `summarize.cache.write_summary_run_cache()` writes one cache directory per run.

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

## Workflow 2: Serve the Dashboard from Precomputed Summaries

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
- If an enabled page requires raw runs, `run.py` loads them only for that page set.
- Most pages should stay summary-backed and declare their requirements through `PAGE.required_summary_ids`.

## Workflow 3: Export a Standalone HTML Dashboard

Typical command:

```bash
python run.py --from-csvs --export-html output.html
```

High-level path:

1. `runtime_workflows.load_summary_runs_from_cache()` loads the same summary inputs used by live mode.
2. `dashboard.page_registry` resolves the export page set.
3. `dashboard.export.html.build_export_html_document()` creates a client-side payload that contains:
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

Summary builders should always aggregate `finalweight` rather than switching behavior internally based on mode. That keeps weighting behavior centralized in `summarize/cache.py`.

## Where New Contributors Usually Need to Look

| Question | Start here |
|---|---|
| How are runs loaded and normalized? | `runtime/run_data.py` |
| Why was a cache reused or rejected? | `runtime_workflows.py`, `summarize/cache.py` |
| Which summary ids exist? | `summarize/cache.py` |
| Which output columns are considered canonical? | `summarize/schema.py` |
| How does a page get discovered? | `dashboard/page_registry.py` |
| How does export know about page-local selectors? | `dashboard/page_definitions.py`, `dashboard/export/payload.py`, `dashboard/export/serializer.py` |

## Related Guides

- [architecture.md](architecture.md)
- [adding-summaries.md](adding-summaries.md)
- [adding-dashboard-pages.md](adding-dashboard-pages.md)
- [export_html_schema.md](export_html_schema.md)
- [export_html_contributor_guide.md](export_html_contributor_guide.md)
