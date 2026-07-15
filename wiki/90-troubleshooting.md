# 90 - Troubleshooting

Use this chapter when a run, cache, page, or export is not behaving as expected.

## Fast Triage

1. Confirm the config path you ran.
2. Check the selected pipeline steps and dashboard mode in logs.
3. Check whether the issue appears in prepare, summarize, dashboard, or export.
4. Inspect cache manifests for the affected run.
5. Run the narrowest refresh command that matches the failure.

## Symptoms

| Symptom | Likely causes | First checks |
|---|---|---|
| Run missing from dashboard | Missing summary cache, label mismatch, config run omitted | `runs`, cache directories, log run keys |
| Summary cache rebuilds unexpectedly | Input fingerprint changed, config digest changed, summary contract changed | summary `manifest.json` |
| Page says data unavailable | Required summary missing, optional raw input absent, prepared column missing | page catalog and summary catalog |
| Counts look wrong | Weighting mode, sample rate, explicit weight columns | `summarize.weighting_modes`, prepared `finalweight` |
| Geography options missing | Geography disabled, land-use columns missing, aggregation config wrong | `zones`, `summarize.geography` |
| Skim pages empty | Skimjoin disabled, no skim outputs, missing lookup rules | skimjoin manifest and reports |
| Export differs from live | Widget/section not registered, selector values omitted, unsupported node | page selector/section registrations |
| Dashboard-only run fails | Summary cache missing or prepared-data page needs prepared cache | `--from-csvs`, page prepared-data mode |

## Cache Problems

Use targeted refresh flags:

```bash
python run.py --config local_config.yaml --refresh-prepared-cache
python run.py --config local_config.yaml --refresh-summary-cache
python run.py --config local_config.yaml --refresh-caches
```

If only dashboard presentation changed, a refresh usually should not be needed.
If raw inputs or prepare config changed, refresh both caches.

## Missing Page Data

Find the page in [31 - Dashboard Pages](31-dashboard-pages.md) and check:

- required summary IDs
- required prepared tables
- prepared-data mode
- whether the page is enabled in live/export config

Then find each summary in [24 - Summary Catalog](24-summary-catalog.md) and
check the required input tables/columns.

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
5. Try `?debug_export=1`.

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
