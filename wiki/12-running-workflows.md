# 12 - Running Workflows

The logical pipeline has five steps:

1. `prepare`
2. `skimjoin`
3. `summarize`
4. `segment`
5. `dashboard`

At runtime these collapse into three workflow boundaries:

| Logical steps | Runtime boundary |
|---|---|
| `prepare`, `skimjoin` | prepare workflow |
| `summarize`, `segment` | summarize workflow |
| `dashboard` | dashboard workflow |

## Step Resolution

`run.py` resolves the effective plan in this order:

1. Load and normalize the config.
2. Start from `pipeline.steps` when no CLI step flags are supplied.
3. Apply CLI flags such as `--prepare-only`, `--summarize`, `--dashboard`,
   `--from-csvs`, and `--no-dashboard`.
4. Collapse logical steps into runtime workflow boundaries.
5. Resolve dashboard mode from CLI first, then `pipeline.dashboard_mode`.

## Dashboard Modes

| Mode | Meaning |
|---|---|
| `none` | Do not run dashboard. |
| `live` | Serve the Panel dashboard locally. |
| `export` | Write standalone HTML and exit. |
| `host` | Reserved; current runtime falls back to live behavior. |

## CLI Flags

| Flag | Use |
|---|---|
| `--config PATH` | Load a specific config. |
| `--prepare-only` | Run prepare and exit. |
| `--prepare` | Include prepare in an explicit step set. |
| `--summarize` | Include summarize in an explicit step set. |
| `--dashboard` | Include dashboard in an explicit step set and prefer live mode. |
| `--from-csvs [DIR...]` | Dashboard-only run from existing summary caches. |
| `--export-html [PATH]` | Export standalone HTML; optional path overrides config. |
| `--refresh-prepared-cache` | Delete selected prepared caches before rebuilding. |
| `--refresh-summary-cache` | Delete selected summary caches before rebuilding. |
| `--refresh-caches` | Refresh both prepared and summary caches. |
| `--skip-summary-cache-write` | Summarize without writing missing/stale summary caches. |
| `--port 5006` | Serve live dashboard on a specific port. |
| `--no-show` | Do not open a browser automatically. |

## Cache Behavior

Prepared caches contain canonical tables per run. Summary caches contain
dashboard-ready CSVs per run and weighting mode.

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

Summary cache layout:

```text
<summary_root>/
  <run_key>/
    manifest.json
    weighted/
      <summary_file>.csv
    unweighted/
      <summary_file>.csv
```

Manifests record input fingerprints, config digests, schema versions, table
states, summary states, and diagnostics. Presentation-only config changes
usually should not force summary rebuilds; input or summary-contract changes
should.

## Common Workflows

### Build Everything In Config Order

```bash
python run.py --config local_config.yaml
```

### Prepare Only

```bash
python run.py --config local_config.yaml --prepare-only
```

### Summarize And Then Open Dashboard

```bash
python run.py --config local_config.yaml --summarize --dashboard
```

### Dashboard From Existing Summary Cache

```bash
python run.py --config local_config.yaml --from-csvs
```

Use explicit cache directories when needed:

```bash
python run.py --config local_config.yaml --from-csvs artifacts\base artifacts\build
```

### Export HTML

```bash
python run.py --config local_config.yaml --export-html exports\dashboard.html
```

## When To Refresh Caches

| Situation | Recommended command |
|---|---|
| Raw output files changed | `--refresh-caches` |
| Prepare config changed | `--refresh-caches` |
| Summary logic changed | `--refresh-summary-cache` |
| Summary page asks for a newly added summary | Usually no manual refresh; missing tables can backfill. |
| Dashboard-only display config changed | Usually no cache refresh. |

## Related Chapters

- [20 - Output Processor](20-output-processor.md)
- [30 - Output Visualizer](30-output-visualizer.md)
- [90 - Troubleshooting](90-troubleshooting.md)

