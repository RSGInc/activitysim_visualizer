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
    manifest.json
    prepared_tables/
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
    manifest.json
    prepared_tables/
    summary_tables/
```

When skimjoin is enabled, `base_prepared_tables/` preserves the prepared input
before skim enrichment. The enriched tables remain in `prepared_tables/` so
existing summary and dashboard consumers continue to use the same final path.

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

Use `--explain-cache` to print the per-run reuse/rebuild decisions and exit
without executing the pipeline.

## CLI Overrides

CLI step, refresh, export-path, and port flags remain available for developers
and troubleshooting. They override the configured workflow for that one
invocation. Users should normally change the YAML and continue running the same
command so the intended workflow remains reproducible.

## Related Chapters

- [Getting Started](10-getting-started.md)
- [Configuring Your Data](11-configuring-your-data.md)
- [Troubleshooting](90-troubleshooting.md)
