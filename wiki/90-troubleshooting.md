# 90 - Troubleshooting

Use this chapter when a run, cache, page, or export does not operate correctly.

## Initial checks

1. Make sure that you used the correct configuration path.
2. Find the selected pipeline steps and dashboard mode in the log.
3. Identify whether the problem occurs in prepare, summarize, dashboard, or export.
4. Inspect `<root>/<run-key>/manifest.json` for summary state and
   `<root>/<run-key>/prepared_tables/manifest.json` for final prepared/skimjoin
   state (see the [cache layout](12-running-workflows.md#artifact-and-cache-paths)).
5. Use `--explain-cache` to examine reuse and rebuild decisions. If you
   must rebuild, list only the applicable step in `pipeline.refresh`.

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

To make a repeatable full rebuild, configure the steps and refresh policy:

```yaml
pipeline:
  steps: [prepare, summarize, dashboard]
  dashboard_mode: live
  refresh: all
```

Set `refresh` to `[]` after the rebuild. During a diagnostic run, developers
can use a refresh flag for one cache layer:

```bash
uv run activitysim-viz --config local_config.yaml --refresh-prepared-cache
uv run activitysim-viz --config local_config.yaml --refresh-summary-cache
uv run activitysim-viz --config local_config.yaml --refresh-caches
```

If only dashboard presentation changed, a refresh is usually not necessary.
The system automatically checks raw-file, skim-file, and applicable
configuration identities. Use a manual refresh only to override a valid cache
decision. Use `pipeline.refresh` for repeatable runs. A prepare refresh
invalidates skimjoin and summary output. A skimjoin refresh keeps
`base_prepared_tables`. A summary refresh keeps final prepared data.

## Missing Page Data

Find the page in [31 - Dashboard Pages](31-dashboard-pages.md) and check:

- required summary IDs
- required prepared tables
- prepared-data mode
- whether the live or export configuration enables the page

Then find each summary in [24 - Summary Catalog](24-summary-catalog.md). Check
the required input tables and columns.

### Worked Triage: A Page Says Data Is Unavailable

Use this procedure if Trip Mode shows the standard unavailable card:

1. Find `trip_mode` in chapter 31. It requires
   `trip_mode_by_tour_purpose_and_tour_mode`.
2. Find that ID in chapter 24. Note its required prepared table and columns.
3. Open `<root>/<run-key>/manifest.json` and examine the summary entry. If the
   summary is `unavailable`, read its recorded reason before a rebuild.
4. If a required prepared column is missing, inspect
   `<root>/<run-key>/prepared_tables/manifest.json`, the table schema, and the
   canonical column settings in `columns`.
5. If the contract recently changed, rebuild the configured summarize step
   with `pipeline.refresh: [summarize]`.
6. If the summary is valid, make sure that the page's `columns=` request agrees
   with the cached schema.
7. Make sure that the selected weighting mode exists.

This sequence examines the declared contracts in reverse order. It prevents
unnecessary cache refreshes when the problem is an input or schema mismatch.

## Skimjoin Problems

Check the skimjoin reports:

- `skim_lookup_summary`
- `missing_lookup_report`
- `fallback_lookup_report`
- `skipped_rule_report`
- `tour_aggregation_summary`
- `failure_report`

Common corrections:

- correct skim file globs
- correct `network_los_file`
- align `activitysim` source columns with prepared tables
- add missing dimension values
- change missing matrix/OD policy only after confirming the missing data is
  expected

## Export Problems

If live mode operates correctly but export fails, do these steps:

1. Make sure that export page selection includes the page.
2. Make sure that standard selection lists use `self.select(...)`.
3. Make sure that custom widgets use `self.selector(...)`.
4. Make sure that `self.section(...)` registers the applicable content.
5. Check browser console errors.
6. Inspect the adjacent `<export-stem>.diagnostics.json` sidecar.
7. Try `?debug_export=1`.

Export cannot reproduce all Python callbacks. It can change only between stored
states and registered selector variants.

## Create a small test case

Create the smallest test case:

1. one run
2. one page or one summary
3. one weighting mode
4. fresh cache root
5. A copy of the applicable log text and manifest diagnostics.

This test case usually identifies the applicable subsystem.
