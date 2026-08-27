# 12 - Running Workflows

One configuration controls the standard workflow, and every workflow uses the
same start command:

```bash
uv run activitysim-viz --config local_config.yaml
```

The configuration selects the work, artifact location, and dashboard mode.
Reserve command-line flags for development or one-time diagnostics.

## Workflow Order

```text
prepare -> optional skimjoin -> optional segmentation -> summarize -> dashboard
```

- **Prepare** reads raw outputs and creates canonical prepared tables.
- **Summarize** creates the smaller tables used by dashboard pages.
- **Dashboard** starts the live application or writes standalone HTML.

Skimjoin runs inside the prepare boundary when selected. Segmentation resolves
and slices prepared data inside the summarize boundary. Geography enrichment
runs during prepare and geography-aware aggregations run during summarize; it
is a feature, not a separate pipeline step.

The written order of non-dashboard values in `pipeline.steps` does not control
runtime order. Those values select logical capabilities, and the runtime
resolves the fixed dependency order above. `dashboard`, when present, must be
the last listed value. Use the canonical order in every example and local
configuration because it makes intent clear:

```yaml
pipeline:
  steps: [prepare, skimjoin, segment, summarize, dashboard]
```

These steps are workflow boundaries, not independent commands. The `summarize`
step requires prepared data, so it reuses a valid prepared cache or builds the
data from the configured input. If the workflow includes `prepare`, the runtime
completes and stores that step first; `summarize` then uses the result from
memory or the cache without preparing it again.

| Requested step | What it guarantees | Prerequisites resolved automatically |
|---|---|---|
| `prepare` | The runtime loads or builds prepared tables and writes the cache. | Raw files or `prepared_table_map`. |
| `summarize` | The runtime loads or builds default registered summaries and writes the cache. | The runtime loads or builds prepared data as necessary. |
| `dashboard` | The runtime loads existing summary caches and shows or exports them. | The runtime does not build summaries. Required caches must exist or come from `summary_table_map`. |

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

This workflow reuses valid caches, builds any missing or stale artifacts, and
starts the dashboard. `dashboard.live.pages` selects the available page groups.

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

This configuration writes `artifacts/exports/dashboard.html`. Relative export
paths start from `root`. Use an absolute path to write the file to a different
location. For page and selector choices, see
[HTML Export](34-html-export.md).

## Configure A Processor-Only Workflow

Build prepared tables and summaries without a dashboard:

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

For dashboard-ready CSV or Parquet files, configure
`runs[*].summary_table_map`. Do not use the files as cache directories.

## Pipeline Rules

The logical steps are `prepare`, `skimjoin`, `segment`, `summarize`, and
`dashboard`. Values must be lowercase, unique, and valid. Put `dashboard` last.
`skimjoin` requires `prepare`, and `segment` requires `summarize`. The runtime
uses step membership, not the listed order, to form the prepare, summarize,
and dashboard boundaries.

If you omit `pipeline.steps`, it defaults to `[summarize, dashboard]` and
prepares raw input when no valid prepared cache is available. Add `prepare`
when cache creation must be a visible step or when you enable `skimjoin`.

Add `segment` when the summarize workflow must build configured subsets:

```yaml
pipeline:
  steps: [segment, summarize, dashboard]
  dashboard_mode: live
  refresh: []
```

The `segment` step requires `summarize`. Its configuration alone does not
enable segmentation.

Dashboard modes:

- `live`: local Panel server;
- `export`: standalone HTML;
- `none`: no dashboard; and
- `host`: reserved extension point. It writes a warning to the log and starts
  the standard live server. It does not publish to a hosting provider.

To host an exported dashboard as a public static file, use
[17 - Publish An Export With Posit Connect Cloud](17-posit-connect-cloud.md).
That workflow uses `dashboard_mode: export`, not `host`.

## Artifact And Cache Paths

The visualizer stores prepared and summary caches under the configured `root`.
Each run has a manifest that describes its input and configuration identity.

Set `root` once for the workflow:

```yaml
root: D:\activitysim_visualizer\regional_comparison
```

For two runs labeled `Base` and `Build`, the standard layout is:

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

The run-level `manifest.json` describes the summary bundle, while each prepared
cache has a manifest in its table directory. A prepare-only workflow therefore
writes `prepared_tables/manifest.json` but does not create the run-level summary
manifest.

When you enable skimjoin, `base_prepared_tables/` contains a second prepared
manifest and the canonical tables before skim enrichment. The visualizer stores
enriched tables, skimjoin reports, and optional hypothetical sidecar tables
under `prepared_tables/`, giving summary and dashboard consumers one final path:

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

The visualizer stores segmented summary CSV files in
`summary_tables/<weighting>/segments/<segmentation-type>/<segment-id>/`. The
run-level summary manifest describes these files. With `refresh: []`, summary
reuse is evaluated separately for the full run and for each configured segment.
Enabling a new segment therefore reuses compatible full summaries and builds
only the new segment summaries. Changing one segment rebuilds that segment;
removing one deletes its obsolete cached summary directory on the next summary
cache write. The prepared cache is loaded to resolve segment membership, but a
valid prepared or skimjoin cache is not recomputed.

The run-key directory uses a lowercase, file-system-safe form of the run label;
for example, `Build Scenario` becomes `build-scenario`. Avoid duplicate labels,
which receive ordered suffixes such as `build-1` and `build-2`. Changing their
order also changes each suffix.

Relative paths in `dashboard.export.output_path` resolve below this directory.
Input paths follow the path rules documented in
[Configuration Reference](13-configuration-reference.md#reading-this-reference).

The visualizer reuses valid caches automatically. To rebuild every stored stage
for the configured steps, temporarily set:

```yaml
pipeline:
  steps: [prepare, summarize, dashboard]
  dashboard_mode: live
  refresh: all
```

Set `refresh` to `[]` after the rebuild. To rebuild summaries and keep prepared
and skimjoined data, use `refresh: [summarize]`. Changes to labels, colors, or
enabled pages do not usually require a cache rebuild.

The refresh targets are stage-aware:

| Refresh target | Reused | Rebuilt when enabled |
|---|---|---|
| `prepare` | nothing upstream of prepare | base prepared data, skimjoin output, summaries |
| `skimjoin` | `base_prepared_tables` | enriched `prepared_tables`, summaries |
| `summarize` | final `prepared_tables` | all default summaries for the full run and every configured segment |

Cache reuse also depends on file metadata. Prepared manifests record the path,
size, and modification time of each raw input, along with the prepare, skimjoin,
and skim input identities. The summary manifest records the prepared-manifest
identity, summary configuration, and declaration digest for each summary. A
changed raw file invalidates prepare and all later output, while a changed skim
input can rebuild only skimjoin and its later output. A changed declaration can
rebuild only the affected summary table for each analysis unit. Segment
definitions are tracked separately from the full-summary configuration, so
compatible full and segment tables remain in the bundle.

Use `--explain-cache` to print the cache decision for each run. The command
then exits without table loads, cache deletions, or artifact writes. The report
shows `REUSE`, `REBUILD`, `RUN`, or `DISABLED` for each workflow step. It also
shows the cache-validation reason when one is available.

For annotated manifest examples, every stored field, and cache-recovery rules,
see [15 - Cache And Manifest Reference](15-cache-manifest-reference.md).

## CLI Overrides

Command-line flags override the configured workflow for one run. For normal
operation, change the YAML so that the workflow remains reproducible.

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
| `--log-path PATH` | Write this process's runtime log to an explicit file instead of the default shared log. |

If you use `--prepare`, `--summarize`, or `--dashboard`, these flags replace
`pipeline.steps` with the selected main boundaries. They do not enable the
`skimjoin` or `segment` steps. Do not combine `--from-csvs` with processor steps
or `--write-csvs`. The `--write-csvs` and `--skip-summary-cache-write` flags
require summarize. Each refresh flag requires its corresponding processor
boundary. If the configuration omits dashboard, use `--export-html` with
`--dashboard`.

Each running visualizer process holds a lock in its configured output root. A
second process targeting the same root exits before reading or writing caches.

### SIMOR scenario runner

The SIMOR runner exports the Metro, LCOG, and SKATS dashboards with bounded
parallelism, then exports the comparison dashboard after all three succeed:

```bash
uv run python scripts/run_simor_scenarios.py
```

It defaults to two concurrent area builds and writes separate runtime and
console logs under `simor_project_outputs/logs/scenario_runner/`. Use
`--dry-run` to inspect commands, `--max-parallel 1` for sequential execution,
or `--refresh-caches` to forward a full cache refresh to every build. Use
`--no-skimjoin` to run prepare, summarize, and HTML export while skipping the
skimjoin step.

## Related Chapters

- [Getting Started](10-getting-started.md)
- [Configuring Your Data](11-configuring-your-data.md)
- [Input Data Contract](14-input-data-contract.md)
- [Cache And Manifest Reference](15-cache-manifest-reference.md)
- [Segmentation](24-segmentation.md)
- [Geography](27-geography.md)
- [Troubleshooting](90-troubleshooting.md)
