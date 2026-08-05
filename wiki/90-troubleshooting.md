# 90 - Troubleshooting

Use this chapter when a run, cache, page, or export is not behaving as expected.

## Fast Triage

1. Confirm the config path you ran.
2. Check the selected pipeline steps and dashboard mode in logs.
3. Check whether the issue appears in prepare, summarize, dashboard, or export.
4. Inspect `<root>/<run-key>/manifest.json` for summary state and
   `<root>/<run-key>/prepared_tables/manifest.json` for final prepared/skimjoin
   state (see the [cache layout](12-running-workflows.md#artifact-and-cache-paths)).
5. Run with `--explain-cache` to inspect reuse and rebuild decisions. If a
   forced rebuild is needed, list only the affected stage in `pipeline.refresh`.

## Symptoms

| Symptom | Likely causes | First checks |
|---|---|---|
| Run missing from dashboard | Missing summary cache, label mismatch, config run omitted | `runs`, cache directories, log run keys |
| Summary cache rebuilds unexpectedly | Input fingerprint changed, upstream prepared identity changed, summary config changed, summary declaration changed | run-level summary manifest and `--explain-cache` |
| Page says data unavailable | Required summary missing, optional raw input absent, prepared column missing | page catalog and summary catalog |
| Counts look wrong | Weighting mode, sample rate, explicit weight columns | `summarize.weighting_modes`, prepared `finalweight` |
| Geography options missing | Geography disabled, land-use columns missing, aggregation config wrong | `zones`, `summarize.geography` |
| Skim pages empty | Skimjoin disabled, no skim outputs, missing lookup rules | skimjoin manifest and reports |
| Export differs from live | Widget/section not registered, selector values omitted, unsupported node | page selector/section registrations |
| Dashboard-only run fails | Summary cache missing or prepared-data page needs prepared cache | `pipeline.steps`, page prepared-data mode |

## Cache Problems

For a reproducible full rebuild, configure the steps and refresh policy:

```yaml
pipeline:
  steps: [prepare, summarize, dashboard]
  dashboard_mode: live
  refresh: all
```

Return `refresh` to `[]` after the rebuild. Developers can use targeted
one-off refresh flags while diagnosing a specific cache layer:

```bash
uv run activitysim-viz --config local_config.yaml --refresh-prepared-cache
uv run activitysim-viz --config local_config.yaml --refresh-summary-cache
uv run activitysim-viz --config local_config.yaml --refresh-caches
```

If only dashboard presentation changed, a refresh usually should not be needed.
Raw-file, skim-file, and relevant config identities are checked automatically;
use a manual refresh only when deliberately overriding a valid cache decision.
Prefer `pipeline.refresh` for reproducible runs. A prepare refresh necessarily
invalidates skimjoin and summary output; a skimjoin refresh preserves
`base_prepared_tables`; a summary refresh preserves final prepared data.

## Missing Page Data

Find the page in [31 - Dashboard Pages](31-dashboard-pages.md) and check:

- required summary IDs
- required prepared tables
- prepared-data mode
- whether the page is enabled in live/export config

Then find each summary in [24 - Summary Catalog](24-summary-catalog.md) and
check the required input tables/columns.

### Worked Triage: A Page Says Data Is Unavailable

Suppose Trip Mode opens but shows the standard unavailable card:

1. Find `trip_mode` in chapter 31. It requires
   `trip_mode_by_tour_purpose_and_tour_mode`.
2. Find that ID in chapter 24. Note its required prepared table and columns.
3. Open `<root>/<run-key>/manifest.json` and inspect the summary entry. If the
   summary is `unavailable`, read its recorded reason before rebuilding
   anything.
4. If a required prepared column is missing, inspect
   `<root>/<run-key>/prepared_tables/manifest.json`, the table schema, and the
   canonical column settings in `columns`.
5. If the contract recently changed, rebuild the configured summarize step
   with `pipeline.refresh: [summarize]`.
6. If the summary is present and valid, confirm the page's `columns=` request
   matches the cached schema and that the selected weighting mode exists.

This sequence moves backward through the declared contracts. It avoids trying
random cache refreshes when the real issue is an input or schema mismatch.

## Skimjoin Problems

Check the skimjoin reports:

- `skim_lookup_summary`
- `missing_lookup_report`
- `fallback_lookup_report`
- `skipped_rule_report`
- `tour_aggregation_summary`
- `failure_report`

Common fixes:

- correct skim file globs
- correct `network_los_file`
- align `activitysim` source columns with prepared tables
- add missing dimension values
- change missing matrix/OD policy only after confirming the missing data is
  expected

## Export Problems

If live mode works but export does not:

1. Confirm the page is included in export page selection.
2. Confirm ordinary dropdowns use `self.select(...)` and custom widgets use
   `self.selector(...)`.
3. Confirm affected content is registered with `self.section(...)`.
4. Check browser console errors.
5. Inspect the adjacent `<export-stem>.diagnostics.json` sidecar.
6. Try `?debug_export=1`.

Export cannot reproduce arbitrary Python callbacks. It can only switch among
serialized states and registered selector variants.

## Still Stuck

Create the smallest reproduction:

1. one run
2. one page or one summary
3. one weighting mode
4. fresh cache root
5. copied log excerpt and manifest diagnostics

That usually makes the owning subsystem obvious.
