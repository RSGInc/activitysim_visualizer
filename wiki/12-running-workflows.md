# 12 - Running Workflows

The normal user experience is config-driven. Keep one launch command:

```bash
uv run activitysim-viz --config local_config.yaml
```

The config decides which work runs, where artifacts are stored, and whether the
result is a live dashboard or an HTML file. Command-line flags are intended for
development and one-off diagnostics, not normal operation.

## The Three Main Steps

```text
prepare -> summarize -> dashboard
```

- **Prepare** reads raw outputs and creates canonical prepared tables.
- **Summarize** creates the smaller tables used by dashboard pages.
- **Dashboard** serves the live application or writes standalone HTML.

Skimjoin runs inside prepare when selected. Segmentation runs with summarize.

These are requested workflow boundaries, not isolated commands. In particular,
`summarize` must have prepared data: it reuses a valid prepared cache or builds
prepared data from the configured raw/prepared inputs when the cache is missing
or stale. Adding `prepare` explicitly runs and persists that boundary first;
the summarize boundary then reuses the in-memory or cached result rather than
preparing a second time.

| Requested step | What it guarantees | Prerequisites resolved automatically |
|---|---|---|
| `prepare` | Prepared tables are loaded/built and cached. | Raw files or `prepared_table_map`. |
| `summarize` | Default registered summaries are loaded/built and cached. | Prepared data is loaded/built as needed. |
| `dashboard` | Existing summary caches are loaded and displayed/exported. | No summaries are built; required caches must exist or come from `summary_table_map`. |

## Configure A Live Workflow

```yaml
root: artifacts

pipeline:
  steps: [prepare, summarize, dashboard]
  dashboard_mode: live
  refresh: []

dashboard:
  title: Regional Model Comparison
  live:
    pages:
      - overview
      - long_term_choices
      - daily_travel
      - tour_summaries
      - trip_summaries
```

This builds missing or stale artifacts, reuses valid caches, and starts the
dashboard. `dashboard.live.pages` controls which page groups are available.

## Configure An HTML Export

```yaml
root: artifacts

pipeline:
  steps: [prepare, summarize, dashboard]
  dashboard_mode: export
  refresh: []

dashboard:
  export:
    output_path: exports/dashboard.html
```

The configured output is `artifacts/exports/dashboard.html`: relative export
paths resolve below `root`. Use an absolute path when the file must be written
elsewhere. Page and selector choices are covered in
[HTML Export](34-html-export.md).

## Configure A Processor-Only Workflow

Build prepared tables and summaries without opening or exporting a dashboard:

```yaml
pipeline:
  steps: [prepare, summarize]
  dashboard_mode: none
  refresh: []
```

Other focused workflows use the same fields:

| Goal | `pipeline.steps` | `dashboard_mode` |
|---|---|---|
| Prepare tables only | `[prepare]` | `none` |
| Build or reuse summaries, preparing on cache miss | `[summarize]` | `none` |
| Open a live dashboard from existing caches | `[dashboard]` | `live` |
| Export HTML from existing caches | `[dashboard]` | `export` |

For loose dashboard-ready CSV or Parquet inputs, configure
`runs[*].summary_table_map`; do not treat them as cache directories.

## Pipeline Rules

Available logical steps are `prepare`, `skimjoin`, `segment`, `summarize`, and
`dashboard`. Dashboard must be last. `skimjoin` requires `prepare`; `segment`
requires `summarize`.

The default when `pipeline.steps` is omitted is `[summarize, dashboard]`.
That default still prepares raw inputs when a valid prepared cache is not
available. Include `prepare` explicitly when prepared-cache creation is itself
an intended, visible stage or when `skimjoin` is enabled.

Dashboard modes:

- `live`: local Panel server;
- `export`: standalone HTML;
- `none`: no dashboard; and
- `host`: reserved extension point that currently logs a warning and executes
  the normal live server; it does not publish to a hosting provider.

## Artifact And Cache Paths

Prepared and summary caches live under the configured `root`. Each run has a
manifest describing its inputs and config identity.

Set `root` once for the workflow:

```yaml
root: D:\activitysim_visualizer\regional_comparison
```

For two runs labeled `Base` and `Build`, the normal layout is:

```text
regional_comparison/
  base/
    manifest.json                 # summary-bundle manifest
    prepared_tables/
      manifest.json               # final prepared/skimjoin identity
      households.parquet
      persons.parquet
      tours.parquet
      trips.parquet
      ...
    summary_tables/
      weighted/
        <summary>.csv
      unweighted/
        <summary>.csv
  build/
    prepared_tables/
      manifest.json
    summary_tables/
    manifest.json
```

The run-level `manifest.json` belongs to the summary bundle. Each prepared
cache has its own manifest inside its table directory. A prepare-only workflow
therefore writes `prepared_tables/manifest.json` but does not create the
run-level summary manifest.

When skimjoin is enabled, `base_prepared_tables/` contains a second prepared
manifest and the canonical tables before skim enrichment. The enriched tables,
skimjoin reports, and optional hypothetical sidecars remain under
`prepared_tables/`, so summary and dashboard consumers continue to use the
same final path:

```text
base/
  base_prepared_tables/
    manifest.json
    trips.parquet
    tours.parquet
    ...
  prepared_tables/
    manifest.json
    trips.parquet
    tours.parquet
    trip_hypothetical_skims.parquet   # only when enabled and populated
    tour_hypothetical_skims.parquet   # only when enabled and populated
    skimjoin/
      config_normalized.yaml
      <QA reports>.csv
```

Segmented summary CSVs are nested below
`summary_tables/<weighting>/segments/<segmentation-type>/<segment-id>/` and
are described by the run-level summary manifest.

The run-key directory is a filesystem-safe lowercase slug of the run label.
For example, `Build Scenario` becomes `build-scenario`. Colliding labels receive
ordered suffixes such as `build-1` and `build-2`; avoid duplicate labels because
reordering them changes which run receives each suffix.

Relative paths in `dashboard.export.output_path` resolve below this directory.
Input paths follow the path rules documented in
[Configuration Reference](13-configuration-reference.md#reading-this-reference).

Valid caches are reused automatically. To deliberately rebuild every
materialized stage used by the configured steps, temporarily set:

```yaml
pipeline:
  steps: [prepare, summarize, dashboard]
  dashboard_mode: live
  refresh: all
```

Return `refresh` to `[]` after the forced rebuild. To rebuild summaries while
preserving prepared and skimjoined data, use `refresh: [summarize]`.
Presentation-only changes such as labels, colors, or enabled pages normally do
not require cache rebuilding.

The refresh targets are stage-aware:

| Refresh target | Reused | Rebuilt when enabled |
|---|---|---|
| `prepare` | nothing upstream of prepare | base prepared data, skimjoin output, summaries |
| `skimjoin` | `base_prepared_tables` | enriched `prepared_tables`, summaries |
| `summarize` | final `prepared_tables` | stale/default summaries and segmented summaries |

Normal reuse is also content-aware. Prepared manifests record resolved raw
input identities, including path, size, and modification time, plus the
prepare/skimjoin config identity and skim input identities. The summary
manifest records its upstream prepared-manifest identity, summary config, and
per-summary declaration digest. Consequently, a changed raw file invalidates
prepare and downstream output, a changed skim input can rebuild only skimjoin
and downstream output, and a changed summary declaration can rebuild only the
affected summary tables while reusing compatible tables in the bundle.

Use `--explain-cache` to print the per-run reuse/rebuild decisions and exit
without loading tables, deleting caches, or writing artifacts. The report shows
`REUSE`, `REBUILD`, `RUN`, or `DISABLED` for prepare, skimjoin, summarize, and
dashboard, with the cache-validation reason when available.

## CLI Overrides

CLI flags override the configured workflow for one invocation. Users should
normally change YAML so the intended workflow remains reproducible.

| Flag | Behavior |
|---|---|
| `--config PATH`, `-c PATH` | Load the named main config. The default is `config.yaml` next to `run.py`. |
| `--run DIR LABEL` | Replace configured `runs` with one CLI run. Repeat the flag for multiple runs. |
| `--run-skim PATH ...` | Supply one legacy prepare distance-skim path per `--run`, in order. Use `null` or an empty string to inherit `prepare.distance_skim.file`. |
| `--prepare` | Select the coarse prepare boundary for this invocation. |
| `--summarize` | Select the coarse summarize boundary for this invocation. |
| `--dashboard` | Select the dashboard boundary and force live mode unless `--export-html` is also present. |
| `--prepare-only` | Select only prepare; it cannot be combined with the three explicit step flags. |
| `--write-csvs` | Bypass reusable summary tables and force summary CSV/manifest writes; requires summarize. |
| `--from-csvs [CACHE_DIR ...]` | Run dashboard-only and load completed summary-cache directories explicitly. These are cache bundles with manifests, not loose CSV files. |
| `--skip-summary-cache-write` | Build summaries in memory without writing missing or stale summary cache entries; requires summarize. |
| `--refresh-prepared-cache` | Force prepared data and all affected downstream output to rebuild for selected runs. |
| `--refresh-summary-cache` | Preserve prepared directories and force summary output to rebuild. |
| `--refresh-caches` | Force both prepared and summary cache layers to rebuild. |
| `--export-html [PATH]` | Use export mode for a selected dashboard step. An omitted path uses `dashboard.export.output_path`, then `<root>/exported_dashboard.html`. |
| `--port PORT` | Live-server port; default `5006`. |
| `--no-show` | Start the live server without opening a browser. |
| `--explain-cache` | Print the cache plan and exit without executing it. |

If any of `--prepare`, `--summarize`, or `--dashboard` is present, those flags
replace `pipeline.steps` with the selected coarse boundaries. They do not
implicitly enable the logical `skimjoin` or `segment` steps. `--from-csvs`
cannot be combined with processor steps or `--write-csvs`; `--write-csvs` and
`--skip-summary-cache-write` require summarize. Refresh flags require the
corresponding processor boundary. If the config omits dashboard, pair
`--export-html` with `--dashboard` to select it.

## Related Chapters

- [Getting Started](10-getting-started.md)
- [Configuring Your Data](11-configuring-your-data.md)
- [Troubleshooting](90-troubleshooting.md)
