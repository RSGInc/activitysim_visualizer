# 12 - Running Workflows

For normal use, run one command:

```bash
uv run activitysim-viz --config local_config.yaml
```

With the default settings, the visualizer builds or reuses summaries and opens
the live dashboard.

## The Three Main Steps

```text
prepare -> summarize -> dashboard
```

- **Prepare** reads raw outputs and creates canonical prepared tables.
- **Summarize** creates the smaller tables used by dashboard pages.
- **Dashboard** serves the live application or writes standalone HTML.

Skimjoin runs inside prepare when selected. Segmentation runs with summarize.

## Common Commands

| Goal | Command |
|---|---|
| Run the configured workflow | `uv run activitysim-viz --config local_config.yaml` |
| Prepare only | `uv run activitysim-viz --config local_config.yaml --prepare-only` |
| Build/reuse summaries and exit | `uv run activitysim-viz --config local_config.yaml --summarize` |
| Open from existing summary caches | `uv run activitysim-viz --config local_config.yaml --from-csvs` |
| Export standalone HTML | `uv run activitysim-viz --config local_config.yaml --export-html exports/dashboard.html` |
| Use another live port | `uv run activitysim-viz --config local_config.yaml --dashboard --port 5010` |

`--from-csvs` means visualizer cache directories with manifests. For loose CSV
or Parquet files, use `runs[*].summary_table_map` instead.

## Configure The Default Workflow

```yaml
pipeline:
  steps: [summarize, dashboard]
  dashboard_mode: live
```

Available logical steps are `prepare`, `skimjoin`, `segment`, `summarize`, and
`dashboard`. Dashboard must be last. `skimjoin` requires `prepare`; `segment`
requires `summarize`.

Dashboard modes:

- `live`: local Panel server;
- `export`: standalone HTML;
- `none`: no dashboard; and
- `host`: reserved extension point that currently falls back to live mode.

## Caches

Prepared caches sit beside the configured `root`; summary caches live under
`root`. Each run has a manifest describing its inputs and config identity.

Valid caches are reused automatically. Refresh only when you need to force a
rebuild:

| Changed | Command |
|---|---|
| Raw files or prepare behavior | `--refresh-caches` |
| Summary logic only | `--refresh-summary-cache` |
| Prepared data only | `--refresh-prepared-cache` |
| Dashboard labels/colors/pages only | No refresh normally needed |

Example:

```bash
uv run activitysim-viz --config local_config.yaml --refresh-caches
```

## Export

One-off output path:

```bash
uv run activitysim-viz --config local_config.yaml --export-html exports/dashboard.html
```

Or configure it:

```yaml
pipeline:
  steps: [summarize, dashboard]
  dashboard_mode: export

dashboard:
  export:
    output_path: exports/dashboard.html
```

For page and selector choices, read [HTML Export](34-html-export.md).

## Related Chapters

- [Getting Started](10-getting-started.md)
- [Configuring Your Data](11-configuring-your-data.md)
- [Troubleshooting](90-troubleshooting.md)
