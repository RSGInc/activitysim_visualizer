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

## Configure A Live Workflow

```yaml
root: artifacts

pipeline:
  steps: [prepare, summarize, dashboard]
  dashboard_mode: live
  overwrite: false

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
  overwrite: false

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
  overwrite: false
```

Other focused workflows use the same fields:

| Goal | `pipeline.steps` | `dashboard_mode` |
|---|---|---|
| Prepare tables only | `[prepare]` | `none` |
| Build or reuse summaries only | `[summarize]` | `none` |
| Open a live dashboard from existing caches | `[dashboard]` | `live` |
| Export HTML from existing caches | `[dashboard]` | `export` |

For loose dashboard-ready CSV or Parquet inputs, configure
`runs[*].summary_table_map`; do not treat them as cache directories.

## Pipeline Rules

Available logical steps are `prepare`, `skimjoin`, `segment`, `summarize`, and
`dashboard`. Dashboard must be last. `skimjoin` requires `prepare`; `segment`
requires `summarize`.

Dashboard modes:

- `live`: local Panel server;
- `export`: standalone HTML;
- `none`: no dashboard; and
- `host`: reserved extension point that currently falls back to live mode.

## Artifact And Cache Paths

Prepared and summary caches live under the configured `root`. Each run has a
manifest describing its inputs and config identity.

Set `root` once for the workflow:

```yaml
root: D:\activitysim_visualizer\regional_comparison
```

Relative paths in `dashboard.export.output_path` resolve below this directory.
Input paths follow the path rules documented in
[Configuration Reference](13-configuration-reference.md#reading-this-reference).

Valid caches are reused automatically. To deliberately rebuild every cache
used by the configured steps, temporarily set:

```yaml
pipeline:
  steps: [prepare, summarize, dashboard]
  dashboard_mode: live
  overwrite: true
```

Return `overwrite` to `false` after the forced rebuild. Presentation-only
changes such as labels, colors, or enabled pages normally do not require cache
rebuilding.

## CLI Overrides

CLI step, refresh, export-path, and port flags remain available for developers
and troubleshooting. They override the configured workflow for that one
invocation. Users should normally change the YAML and continue running the same
command so the intended workflow remains reproducible.

## Related Chapters

- [Getting Started](10-getting-started.md)
- [Configuring Your Data](11-configuring-your-data.md)
- [Troubleshooting](90-troubleshooting.md)
