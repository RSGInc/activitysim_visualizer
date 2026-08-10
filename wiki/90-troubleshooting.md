# 90 - Troubleshooting

Use this chapter when a run, cache, page, or export does not behave as expected.

## Initial checks

1. Make sure you used the correct configuration path.
2. Find the selected pipeline steps and dashboard mode in the log.
3. Identify whether the problem occurs in prepare, summarize, dashboard, or export.
4. Inspect `<root>/<run-key>/manifest.json` for summary state and
   `<root>/<run-key>/prepared_tables/manifest.json` for final prepared/skimjoin
   state (see the [cache layout](12-running-workflows.md#artifact-and-cache-paths)).
5. Use `--explain-cache` to examine reuse and rebuild decisions. If you
   must rebuild, list only the relevant step in `pipeline.refresh`.

## Symptoms

| Symptom | Likely causes | First checks |
|---|---|---|
| Run missing from dashboard | Missing summary cache, label mismatch, config run omitted | `runs`, cache directories, log run keys |
| Summary cache rebuilds unexpectedly | Input fingerprint changed, upstream prepared identity changed, summary config changed, summary declaration changed | run-level summary manifest and `--explain-cache` |
| Page says data unavailable | Required summary missing, optional raw input absent, prepared column missing | page catalog and summary catalog |
| Counts look wrong | Weighting mode, sample rate, explicit weight columns | `summarize.weighting_modes`, prepared `finalweight` |
| Geography options missing | Geography disabled, zone columns missing, lookup config wrong | [Geography](27-geography.md) and `summarize.geography` |
| Segmented series missing | Segment step disabled, source values do not match, dashboard visibility hides them | [Segmentation](24-segmentation.md), `pipeline.steps`, and `segment.dashboard` |
| Skim pages empty | Skimjoin disabled, no skim outputs, missing lookup rules | skimjoin manifest and reports |
| Export differs from live | Widget/section not registered, selector values omitted, unsupported node | page selector/section registrations |
| Dashboard-only run fails | Summary cache missing or prepared-data page needs prepared cache | `pipeline.steps`, page prepared-data mode |

## Configuration And Startup Problems

| Symptom | Cause to distinguish | Action |
|---|---|---|
| Unknown top-level or section key | Typo, removed field, or field at the wrong nesting level | Use the replacement in the error and compare the field with chapter 13. Do not move it until you confirm its owning section. |
| Path exists in YAML but file is not found | Relative path uses a different base than expected | Use the path-resolution table in chapter 13. Raw `files` start from each run directory; most other main-config paths start from the config directory. |
| `skimjoin` or `segment` config appears ignored | The configuration block does not enable its logical step | Add the step and its prerequisite to `pipeline.steps`. Use canonical step order. |
| Dashboard starts instead of exporting | `dashboard_mode` is live or a CLI override selected live mode | Set `pipeline.dashboard_mode: export`, or use `--dashboard --export-html`. |
| `dashboard_mode: host` does not publish | Core host mode is a placeholder | Use the explicit Panel hosting script in chapter 43. |
| Port is already in use | Another server owns the selected port | Stop that process or use `--port <other-port>`. |

Configuration validation is strict at documented typed boundaries but some
extension/nested mappings are intentionally free-form. If a nested setting has
no effect and no error, confirm its exact spelling and add a focused config
load test rather than assuming it was applied.

## Raw Input And Prepare Problems

| Symptom | Check | Interpretation |
|---|---|---|
| Raw table is unavailable | Effective `files` plus `runs[*].file_map`, run directory, extension, fallback path | A stem tries Parquet before CSV. An explicit extension tries only that file. |
| Entire run is skipped | Availability of households, persons, tours, and trips | The run is skipped when none of these four core tables is usable. One missing core table instead causes partial summary coverage. |
| Prepared column is missing | Source alias, owning raw table, enrichment prerequisites, prepared manifest | Prepare only materializes a canonical field when it finds the source needed for that field. |
| CSV reads with an unexpected type | Mixed values or inference | Prefer Parquet for controlled schemas or normalize the raw column before prepare. Prepared finalization casts only known canonical fields. |
| Relationship warning reports orphans | Source/target key values and types | Direct summaries can count orphan rows while joined summaries can drop them. Fix the relationship instead of comparing those totals as equivalent. |
| `prepared_table_map` lacks derived fields | External process supplied raw-like rather than canonical tables | That input bypasses all prepare enrichment, weighting, geography, and skimjoin. Materialize the prepared contract upstream. |
| Optional table has zero columns after cache load | Stored `empty`, `unavailable`, or `failed` state | Read `table_states` and `table_diagnostics`; the cache loader converted its sentinel back to an empty frame. |

Use [14 - Input Data Contract](14-input-data-contract.md) to identify the
expected keys and relationship checks. Use chapter 26 to work backward from one
unavailable summary to its exact prepared columns.

## Weighting, Totals, And Units

If counts differ from expectation, inspect the prepared `finalweight` values on
the table that the summary actually aggregates. Do not infer trip weights from
household weights without checking propagation.

| Symptom | Likely reason | Check |
|---|---|---|
| Weighted equals unweighted | No source weight/sample rate, all source weights are one, or a mapped external summary was copied to both modes | Prepared `finalweight`, run weight fields, `summary_table_map` behavior |
| Household totals are not sample-expanded | Any explicit run weight field disables automatic household sample-rate expansion | `hh_weight_col`, `person_weight_col`, `trip_weight_col`, `columns.sample_rate` |
| Some rows disappear from weighted totals | Null source weights or builder filters | Null/nonfinite weight counts and summary requirements |
| Negative or infinite result | Negative weights, zero sample rate, or zero weighted denominator | Validate finite nonnegative weights and positive sample rates upstream |
| Distance/time/cost differs by a fixed factor | Runs or skims use different units | Prepared source columns and skim documentation; the visualizer does not convert units |
| Percent chart does not sum to 100 | Fixed count/rate chart, missing categories, separate traces, or a builder-specific denominator | Axis title, `value_mode` used by the page, and calculation note |

The first run is the comparison base where a page reports differences. Confirm
run order before treating a changed difference as a processor regression.

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

If only dashboard presentation changed, a refresh is usually unnecessary. The
system automatically checks raw-file, skim-file, and relevant configuration
identities. Use a manual refresh only to override a valid cache decision, and
use `pipeline.refresh` for repeatable runs. A prepare refresh
invalidates skimjoin and summary output. A skimjoin refresh keeps
`base_prepared_tables`. A summary refresh keeps final prepared data.

## Missing Page Data

Find the page in
[31 - Dashboard Page Contract](31-dashboard-pages.md) and check:

- required summary IDs
- required prepared tables
- prepared-data mode
- whether the live or export configuration enables the page

Then find each summary in [26 - Summary Catalog](26-summary-catalog.md). Check
the required input tables and columns.

### Worked Triage: A Page Says Data Is Unavailable

If Trip Mode shows the standard unavailable card, follow these steps:

1. Find `trip_mode` in chapter 31. It requires
   `trip_mode_by_tour_purpose_and_tour_mode`.
2. Find that ID in chapter 26. Note its required prepared table and columns.
3. Open `<root>/<run-key>/manifest.json` and examine the summary entry. If the
   summary is `unavailable`, read its recorded reason before a rebuild.
4. If a required prepared column is missing, inspect
   `<root>/<run-key>/prepared_tables/manifest.json`, the table schema, and the
   canonical column settings in `columns`.
5. If the contract recently changed, rebuild the configured summarize step
   with `pipeline.refresh: [summarize]`.
6. If the summary is valid, make sure that the page's `columns=` request agrees
   with the cached schema.
7. Make sure the selected weighting mode exists.

This sequence works backward through the declared contracts and avoids
unnecessary cache refreshes when the problem is an input or schema mismatch.

## Skimjoin Problems

Check the skimjoin reports:

- `skim_lookup_summary`
- `missing_lookup_report`
- `fallback_lookup_report`
- `skipped_rule_report`
- `failure_report`

Common corrections:

- correct skim file globs
- correct `network_los_file`
- align `activitysim` source columns with prepared tables
- add missing dimension values
- change missing matrix/OD policy only after confirming the missing data is
  expected

Also inspect `config_normalized.yaml` to verify the effective rules and paths.
For CSV skims, confirm whether the file was inventoried as a keyed table or an
OD table and use the generated `<file-stem>__<value-column>` matrix name. For
OMX/HDF5, qualify duplicate matrix names with `filename::matrix` and verify the
selected zone mapping.

With `failure_policy: record`, a failure is expected to leave the original
prepared trip/tour tables in place and record a `failure_report`. With `error`,
the same failure stops the workflow. Do not interpret “run continued” as proof
that skim values were applied; read `skimjoin_status` and
`skimjoin_applied_outputs`.

## Segmentation Problems

| Symptom | Check |
|---|---|
| Definition or ID rejected | Lowercase path-safe pattern and no leading/trailing punctuation. |
| CSV-backed segment is empty | Quote numeric-looking `segments[*].values`; CSV segment values are stored as strings. |
| Prepared-column segment is empty | Match the prepared column's value and type exactly. |
| Household/person totals look too broad | The anchor may be trip/tour based; relationship expansion retains related parents and children. |
| Segment totals exceed full total | Values overlap with `allow_overlapping: true`, or the counted population differs from the anchor. |
| Mapped external summary is identical in every segment | `summary_table_map` is overlaid unchanged because aggregated rows cannot be re-segmented. |
| Only one segment changed but many tables rebuilt | Read per-unit/per-summary digests and `--explain-cache`; a shared summary/config change can invalidate all units. |

The run manifest's `segmentation_types` list is the final record of source,
values, stored paths, states, and diagnostics. If a configured segment is not
there, review `on_empty_segment: skip` and whether summarize completed a cache
write.

## Geography Problems

Distinguish preparation from presentation:

1. Confirm `summarize.geography.enabled: true`.
2. Confirm the named aggregation and source zone system in the loaded config.
3. Inspect the role-specific prepared column, such as
   `home_geo__district` or `destination_geo__district`.
4. Confirm non-null mapped values and lookup coverage.
5. Confirm the target summary supports that role in chapter 27.
6. Confirm the summary has rows for the geography type.
7. Only then inspect the dashboard selector and
   `dashboard.enable_maz_geographies`.

A valid named mapping does not add geography to every summary. Parking Location
currently uses its base parking zone, and MAZ presentation can be hidden even
when MAZ summary rows exist.

## Export Problems

If live mode works but export fails:

1. Make sure export page selection includes the page.
2. Make sure standard selection lists use `self.select(...)`.
3. Make sure custom widgets use `self.selector(...)`.
4. Make sure `self.section(...)` registers the relevant content.
5. Check browser console errors.
6. Inspect the adjacent `<export-stem>.diagnostics.json` sidecar.
7. Try `?debug_export=1`.

Export cannot reproduce every Python callback; it can only switch among stored
states and registered selector variants.

Use the diagnostics sidecar to separate three failure classes:

| Evidence | Meaning |
|---|---|
| `render_state: skipped` with excluded runs | Data contract or availability problem before serialization. |
| Large `raw_state_count` or `size_analysis` peak | Selector enumeration made the payload large; export fewer values or disable that part. |
| Browser `ExportRuntimeError` | Payload/runtime schema, node, state, or rendering problem; note its error code. |

If you changed the browser runtime, edit `dashboard/export/js_runtime/`, rebuild
the generated asset, and run runtime build/contract tests. Never patch the
generated asset as the source change.

## Performance And Hosting Problems

| Symptom | First action |
|---|---|
| First run is slow | Separate prepare, skimjoin, summarize, and dashboard timings; later valid runs should reuse caches. |
| Export is very large or slow to open | Inspect `size_analysis.page_peaks` and `region_peaks`; reduce exported weighting/value/selector states. |
| Live server uses much more memory than export | Check enabled prepared-data pages and concurrent Panel sessions. Prepared runs can be loaded for live-only features. |
| Hosted page loads but controls disconnect | Verify reverse-proxy WebSocket upgrades and `--allow-websocket-origin`. |
| Hosted startup has no runs | Use an explicit config path and persistent compatible caches; fail deployment on missing required data. |
| Permission error during hosting | Use read-only caches for serve-only deployment; grant writes only if startup deliberately builds artifacts. |
| Posit Connect Cloud export differs from live mode | Test the local HTML export first; the hosted static file contains only export-supported pages, sections, and selector states. |

For static HTML publishing, see
[17 - Publish An Export With Posit Connect Cloud](17-posit-connect-cloud.md).
For live-server deployment commands and requirements, see
[43 - Weighting And Hosting Extensions](43-weighting-hosting-extensions.md#worked-example-connect-a-hosting-script).

## Create a small test case

Reduce the problem to the smallest test case:

1. one run
2. one page or one summary
3. one weighting mode
4. fresh cache root
5. A copy of the relevant log text and manifest diagnostics.

This usually identifies the responsible subsystem.
