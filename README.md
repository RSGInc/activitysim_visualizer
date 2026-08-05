# ActivitySim Visualizer

ActivitySim Visualizer turns [ActivitySim](https://activitysim.github.io/)
outputs into an interactive dashboard for exploring one model run, comparing
several runs side by side, or comparing model outputs to survey results.

It can:

- prepare and summarize ActivitySim household, person, tour, and trip outputs;
- compare travel patterns, model choices, and validation measures across runs;
- reuse cached results so subsequent launches are faster; and
- serve a local dashboard or create a standalone HTML file for sharing.

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

Copy `config.yaml` to `local_config.yaml`. In the new file, update the entries
under `runs` so they point to your ActivitySim output directories:

```yaml
runs:
  - dir: C:\models\base\output
    label: Base
  - dir: C:\models\build\output
    label: Build
```

The default file names are `final_households`, `final_persons`, `final_tours`,
`final_trips`, `final_joint_tour_participants`, and `final_land_use`. Both CSV
and Parquet inputs are supported.

For a smaller example configuration and help with nonstandard files or zones,
see [Getting Started](wiki/10-getting-started.md) and
[Configuring Your Data](wiki/11-configuring-your-data.md).

### 3. Start the visualizer

```bash
uv run activitysim-viz --config local_config.yaml
```

The first run prepares the inputs, builds the summary tables needed by the
dashboard, and opens a local server at
[http://localhost:5006](http://localhost:5006). Later runs reuse valid caches.
Stop the server with `Ctrl+C`.

If something is missing or the first run fails, start with
[Troubleshooting](wiki/90-troubleshooting.md).

## How It Works

```text
ActivitySim outputs
  -> prepare canonical tables
  -> summarize travel measures
  -> display a live dashboard or export standalone HTML
```

The configuration selects the inputs, workflow steps, output location, and
dashboard mode. Most users can keep using the same launch command and change
the YAML when they want a different workflow.

| Goal | Where to learn more |
|---|---|
| Use raw ActivitySim output folders | [Configuring Your Data](wiki/11-configuring-your-data.md#raw-activitysim-output) |
| Use already-prepared tables | [Already-Prepared Tables](wiki/11-configuring-your-data.md#already-prepared-tables) |
| Use dashboard-ready summary tables | [Dashboard-Ready Summary Tables](wiki/11-configuring-your-data.md#dashboard-ready-summary-tables) |
| Run only the processor | [Processor-Only Workflow](wiki/12-running-workflows.md#configure-a-processor-only-workflow) |
| Create a standalone HTML dashboard | [HTML Export](wiki/34-html-export.md) |
| Understand caches and workflow steps | [Running Workflows](wiki/12-running-workflows.md) |
| Find an exact configuration field | [Configuration Reference](wiki/13-configuration-reference.md) |
| Understand a summary table or field | [Summary Catalog](wiki/24-summary-catalog.md) |

## Documentation

The [wiki home](wiki/00-home.md) is the main documentation index.

For normal use, these three chapters cover the usual path:

1. [Getting Started](wiki/10-getting-started.md)
2. [Configuring Your Data](wiki/11-configuring-your-data.md)
3. [Running Workflows](wiki/12-running-workflows.md)

Additional user references:

- [Output Visualizer](wiki/30-output-visualizer.md) explains the dashboard.
- [Dashboard Pages](wiki/31-dashboard-pages.md) lists the available analyses.
- [HTML Export](wiki/34-html-export.md) covers offline sharing.
- [Summary Catalog](wiki/24-summary-catalog.md) documents every summary table.
- [Glossary](wiki/99-glossary.md) defines project terminology.
- [Troubleshooting](wiki/90-troubleshooting.md) covers common failures.

## For Contributors

Start with [Architecture](wiki/01-architecture.md) and
[Developer Workflows](wiki/40-developer-workflows.md). Task-specific guides are
available for:

- [extending prepared data](wiki/41-data-extension-cookbook.md);
- [adding a summary function](wiki/44-summary-function-cookbook.md);
- [adding dashboard pages, figures, or widgets](wiki/45-dashboard-extension-cookbook.md);
- [changing configuration, columns, or labels](wiki/42-config-column-label-cookbook.md);
- [skim enrichment](wiki/22-skimjoin.md); and
- [testing](wiki/46-testing.md).

Run focused tests while developing. The standard full test command is:

```bash
uv run pytest --basetemp .pytest_tmp
```

After changing summary declarations or dashboard page definitions, regenerate
the code-backed wiki catalogs:

```bash
uv run python scripts/generate_wiki_catalogs.py
```

## License

This project is licensed under the GNU General Public License v3.0. See
[`LICENSE.txt`](LICENSE.txt).
