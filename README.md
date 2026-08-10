# ActivitySim Visualizer

ActivitySim Visualizer turns [ActivitySim](https://activitysim.github.io/)
output into an interactive dashboard. Use it to examine one model run, compare
multiple runs, or compare model results with survey data.

ActivitySim Visualizer can:

- prepare and summarize household, person, tour, and trip output;
- compare travel patterns, model choices, and validation measures for multiple runs;
- reuse valid cached results for faster startup; and
- launch a local dashboard or create a standalone HTML file.

## Quick Start

### 1. Install the project

From the repository root, use `uv` to create the environment and install the
locked dependencies:

```bash
uv sync --locked
```

If Windows reports a hardlink problem, use:

```bash
uv sync --locked --link-mode=copy
```

### 2. Create a configuration

Copy `config.yaml` to `local_config.yaml`, then set each `runs.dir` value to an
ActivitySim output directory:

```yaml
runs:
  - dir: C:\models\base\output
    label: Base
  - dir: C:\models\build\output
    label: Build
```

The default file names are `final_households`, `final_persons`, `final_tours`,
`final_trips`, `final_joint_tour_participants`, and `final_land_use`. The
visualizer accepts CSV and Parquet input files.

For a small example configuration and instructions for nonstandard files or
zones, see [Getting Started](wiki/10-getting-started.md) and
[Configuring Your Data](wiki/11-configuring-your-data.md).

### 3. Start the visualizer

```bash
uv run activitysim-viz --config local_config.yaml
```

On the first run, the visualizer prepares the input, builds the required summary
tables, and starts a local server at
[http://localhost:5006](http://localhost:5006). Later runs reuse valid caches.
Press `Ctrl+C` to stop the server.

If data is missing or the first run fails, see
[Troubleshooting](wiki/90-troubleshooting.md).

## How It Works

```text
ActivitySim outputs
  -> prepare canonical tables
  -> summarize travel measures
  -> display a live dashboard or export standalone HTML
```

The YAML configuration selects the input, workflow steps, output location, and
dashboard mode. The start command stays the same for every workflow.

| Goal | Where to learn more |
|---|---|
| Use raw ActivitySim output directories | [Configuring Your Data](wiki/11-configuring-your-data.md#raw-activitysim-output) |
| Use already-prepared tables | [Already-Prepared Tables](wiki/11-configuring-your-data.md#already-prepared-tables) |
| Use dashboard-ready summary tables | [Dashboard-Ready Summary Tables](wiki/11-configuring-your-data.md#dashboard-ready-summary-tables) |
| Run only the processor | [Processor-Only Workflow](wiki/12-running-workflows.md#configure-a-processor-only-workflow) |
| Create a standalone HTML dashboard | [HTML Export](wiki/34-html-export.md) |
| Understand caches and workflow steps | [Running Workflows](wiki/12-running-workflows.md) |
| Build summaries for configured subsets | [Segmentation](wiki/24-segmentation.md) |
| Add district, county, or other zone groupings | [Geography](wiki/27-geography.md) |
| Find an exact configuration field | [Configuration Reference](wiki/13-configuration-reference.md) |
| Verify raw or prepared table requirements | [Input Data Contract](wiki/14-input-data-contract.md) |
| Interpret cache manifests and rebuild decisions | [Cache And Manifest Reference](wiki/15-cache-manifest-reference.md) |
| Understand a summary table or field | [Summary Catalog](wiki/26-summary-catalog.md) |

## Documentation

The [wiki home](wiki/00-home.md) is the main documentation index.

For a standard setup, read these chapters in order:

1. [Getting Started](wiki/10-getting-started.md)
2. [Configuring Your Data](wiki/11-configuring-your-data.md)
3. [Running Workflows](wiki/12-running-workflows.md)

Other user references:

- [Output Visualizer](wiki/30-output-visualizer.md) explains the dashboard.
- [Dashboard User Guide](wiki/16-dashboard-user-guide.md) lists the available
  analyses and explains how to interpret them.
- [Posit Connect Cloud](wiki/17-posit-connect-cloud.md) explains how to publish
  a standalone dashboard with the free public plan.
- [Input Data Contract](wiki/14-input-data-contract.md) defines source and canonical table boundaries.
- [Cache And Manifest Reference](wiki/15-cache-manifest-reference.md) explains stored identities and diagnostics.
- [HTML Export](wiki/34-html-export.md) explains how to create an offline file.
- [Summary Catalog](wiki/26-summary-catalog.md) documents every summary table.
- [Segmentation](wiki/24-segmentation.md) explains subset summaries and their caches.
- [Geography](wiki/27-geography.md) explains zone mappings and spatial outputs.
- [Glossary](wiki/99-glossary.md) defines project terminology.
- [Troubleshooting](wiki/90-troubleshooting.md) covers common failures.

## For Contributors

Start with [Architecture](wiki/01-architecture.md) and
[Developer Workflows](wiki/40-developer-workflows.md), then use the guide for
your task:

- [extending prepared data](wiki/41-data-extension-cookbook.md);
- [adding a summary function](wiki/44-summary-function-cookbook.md);
- [adding dashboard pages, figures, or widgets](wiki/45-dashboard-extension-cookbook.md);
- [changing configuration, columns, or labels](wiki/42-config-column-label-cookbook.md);
- [skim enrichment](wiki/22-skimjoin.md); and
- [testing](wiki/46-testing.md).

Run focused tests during development. To run the full test suite, use:

```bash
uv run pytest --basetemp .pytest_tmp
```

If you change summary declarations or dashboard page definitions, regenerate
the wiki catalogs from the code:

```bash
uv run python scripts/generate_wiki_catalogs.py
```

## License

The GNU General Public License v3.0 applies to this project. See
[`LICENSE.txt`](LICENSE.txt).
