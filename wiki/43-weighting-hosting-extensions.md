# 43 - Weighting And Hosting Extensions

Weighting and hosting cross several runtime boundaries. Configuration handles
standard alternative weights, while the Python registry supports calculations
that column selection cannot express. Hosting remains a limited extension point.

## Worked Example: Add A Weighting Mode

The built-in modes are `weighted` and `unweighted`. A named column mode adds a
set of summary tables, cache entries, dashboard selector state, and export
states. It does not require Python code.

In this example, ActivitySim writes `calibrated_hh_weight`,
`calibrated_person_weight`, and `calibrated_trip_weight` with its standard
weights.

### 1. Define The Named Column Mode

Add the mode under `weighting.modes`, then select its ID under
`summarize.weighting_modes`:

```yaml
weighting:
  modes:
    calibrated:
      label: Calibrated
      columns:
        households: calibrated_hh_weight
        persons: calibrated_person_weight
        trips: calibrated_trip_weight

summarize:
  weighting_modes: [weighted, unweighted, calibrated]
```

`label` is optional; if omitted, the loader creates one from the mode ID. You
must configure at least one column from a supported source table:
`households`, `persons`, or `trips`.

This function differs from the three weight fields on a run. `hh_weight_col`,
`person_weight_col`, and `trip_weight_col` select the primary `weighted`
definition during prepare. `weighting.modes` keeps that primary definition. It
adds named alternatives for comparison in one dashboard.

### 2. Understand Propagation

The configured source columns replace `finalweight` on their prepared tables.
The system then supplies consistent weights to related tables:

- a household source propagates to persons, trips, tours, days, and vehicles
  unless you configure a more specific source;
- a person source propagates to trips, tours, and days;
- a trip source propagates to tours as the mean selected trip weight for each
  `tour_id`; and
- trip and tour hypothetical-skim sidecars inherit the selected trip and tour
  weights.

Configure only the levels that differ. For example, a mode that contains only
`trips` changes trips and tours. Household, person, day, and vehicle weights
keep their primary prepared values.

Before summaries start, the workflow validates source columns for each prepared
run. An incorrect name produces an error identifying the missing table and
column; it does not select a different weight. Prepare usually preserves raw
ActivitySim columns. If you use `prepared_table_map`, include the named source
columns in those prepared files.

Column validation checks presence and castability during use; it does not
enforce finite, non-null, or nonnegative values. Validate those properties in
the producing workflow. Zero and negative values can produce zero denominators
or subtract from counts, and null source weights can be omitted by aggregation.
See [Summary Functions](25-summary-functions.md#weight-resolution-and-edge-cases)
for primary-mode fallback and sample-rate behavior.

### 3. Cache, Dashboard, And Outside-Summary Behavior

The summary cache identity includes the mode ID, source columns, and column-mode
implementation version. A source column change invalidates incompatible summary
caches. Live and export dashboard selectors use the configured label.

Declarative column modes reject mode-independent `summary_table_map` input. An
aggregated external table does not contain enough information to calculate
a different weighting mode. Use generated summaries for these modes. Or supply
external data through a custom workflow that defines its weighting rules.

## Advanced: Custom Weight Calculations

Use a Python weighting module only when column selection is insufficient. For
example, use one to limit, scale, join, or calculate weights from multiple
prepared columns.

### 1. Create An Importable Extension Module

This example adds a limited form of the primary prepared weights. Create
`my_project/weighting.py` in an installed package or another location on
`PYTHONPATH`:

```python
import polars as pl

from processor.models import map_run_data_tables
from runtime.weighting import WeightingModeDefinition, WeightingModeRegistry


def cap_weights(run, config):
    maximum = float(
        config.extension_settings.get("capped", {}).get("maximum", 10.0)
    )

    def cap(_table_name, table: pl.DataFrame) -> pl.DataFrame:
        if "finalweight" not in table.columns:
            return table
        return table.with_columns(
            pl.col("finalweight").cast(pl.Float64).clip(upper_bound=maximum)
        )

    return map_run_data_tables(run, cap)


def register_weighting_modes(registry: WeightingModeRegistry) -> None:
    registry.register(
        WeightingModeDefinition(
            mode_id="capped",
            label="Capped",
            transform=cap_weights,
            version="1",
            required_columns={
                "hh": ("finalweight",),
                "per": ("finalweight",),
                "tours": ("finalweight",),
                "trips": ("finalweight",),
            },
            external_summary_policy="reject",
        )
    )
```

`map_run_data_tables()` copies the complete `RunData` and transforms each data
frame while preserving availability metadata, diagnostics, skims, and skimjoin
artifacts. A transform must return a new `RunData` without changing its input.

The registration fields are:

| Field | Meaning |
|---|---|
| `mode_id` | Stable lowercase config/cache ID. |
| `label` | Unique dashboard/export label. |
| `transform` | Callable receiving `(RunData, Config)` and returning `RunData`. |
| `version` | Cache-facing implementation version. Change it when results can change. |
| `required_columns` | Prepared columns validated before the transform runs. |
| `external_summary_policy` | `copy` permits mode-independent `summary_table_map` data; `reject` fails instead of silently mislabeling it. |
| `default_enabled` | Whether omission/empty `summarize.weighting_modes` includes the mode. Custom modes should normally leave this `false`. |

### 2. Load And Configure The Extension

Use `extensions.modules` for an importable project module. Put extension
settings under `extensions.settings`:

```yaml
extensions:
  modules:
    - my_project.weighting
  settings:
    capped:
      maximum: 10.0

summarize:
  weighting_modes: [weighted, unweighted, capped]
```

Module imports execute code, so treat any configuration with extensions as
trusted. Summary cache identity includes the extension settings along with each
selected definition's version, requirements, and external summary policy.

An installed package can advertise the same registration function with a
Python entry point instead:

```toml
[project.entry-points."activitysim_visualizer.weighting_modes"]
capped = "my_project.weighting:register_weighting_modes"
```

For one definition, use the installed entry point or `extensions.modules`. Do
not use both. Duplicate IDs and labels cause an error during configuration load.

### 3. Runtime Behavior

The weighting definition contract controls configuration validation, summary
transforms, prepared-data transforms, display labels, and cache compatibility:

- config preserves the requested mode order and rejects unknown IDs;
- the summary workflow applies each registered transform before running builders;
- cache directories and manifests use `mode_id`, while plugin `version` enters
  the summary config digest;
- dashboard/export selectors use `label` without deriving text from the ID;
- `PageData.prepared()` and `prepared_runs()` apply the selected mode lazily and
  cache the result for the dashboard session; and
- required source columns fail before a transform can silently fall back.

Standard pages do not branch on particular modes:

```python
prepared = self.data.prepared("trips")

# Only specialized code that deliberately requests another mode supplies it:
weighted = self.data.prepared("trips", weighting_mode="weighted")
```

### 4. Outside Summary Tables

Built-in `weighted` and `unweighted` definitions use
`external_summary_policy="copy"`. A custom mode uses `reject` by default. A run
with `summary_table_map` then causes an error. The runtime cannot verify that an
aggregated file represents the custom mode.

Set the custom definition to `copy` only when the external table does not
depend on the mode. The system does not support file maps for each mode.

### 5. Test The Whole Mode

At a minimum, verify these behaviors:

- config accepts, orders, deduplicates, and rejects mode names correctly;
- both module and installed-entry-point discovery use the registration contract;
- the transform replaces weights on every relevant prepared table;
- a known summary produces expected custom-weight values;
- cache write/load retains all modes;
- dashboard state selects the correct summary and prepared runs;
- export enumerates configured custom states; and
- outside summary behavior is explicit.

Useful suites:

```bash
uv run --with pytest pytest --basetemp .pytest_tmp tests/test_weighting_registry.py
uv run --with pytest pytest --basetemp .pytest_tmp tests/test_config_refactor_phase1.py tests/test_summary_cache.py
uv run --with pytest pytest --basetemp .pytest_tmp tests/test_dashboard_live.py tests/test_export_payload.py
```

## Worked Example: Connect A Hosting Script

This section is for developers who need to deploy the live Python/Panel
application. To publish an existing standalone HTML export instead, use
[17 - Publish An Export With Posit Connect Cloud](17-posit-connect-cloud.md).
Static publishing does not require a hosting adapter or server-side caches.

The first hosting extension should be a small deployment entry point. Use the
existing configuration, cache loader, page requirements, and `build_dashboard()`.
Do not duplicate prepare or summarize logic.

The current `pipeline.dashboard_mode: host` is a placeholder. `run.py` writes a
warning and uses live `pn.serve`. Validation accepts the `dashboard.host` keys.
The loader does not put them in `Config`, and the runtime does not use them.

## Option A: Provider Script Without Core Runtime Changes

Create a deployment-specific script such as `scripts/host_dashboard.py`:

```python
from __future__ import annotations

import os

from dashboard.app import build_dashboard
from dashboard.page_registry import live_data_requirements
from runtime.workflows import (
    load_prepared_runs_for_dashboard,
    load_runtime_config,
    load_summary_runs_from_cache,
    summary_cache_root,
)


config = load_runtime_config(
    os.environ.get("ACTIVITYSIM_VIZ_CONFIG", "config.yaml")
)
requirements = live_data_requirements(config)
summary_runs = load_summary_runs_from_cache(
    config=config,
    cache_root=summary_cache_root(config, create=False),
    explicit_cache_dirs=None,
    run_entries=config.runs,
    required_summary_ids=requirements.required_summary_ids,
)
prepared_runs = []
if requirements.prepared_data_mode != "none":
    prepared_runs = load_prepared_runs_for_dashboard(
        config=config,
        run_entries=config.runs,
        required_run_keys=[run.run_key for run in summary_runs],
        required_prepared_tables=requirements.required_prepared_tables,
    )

dashboard = build_dashboard(
    prepared_runs,
    config,
    summary_runs=summary_runs,
)
dashboard.servable()
```

Start it locally from the repository root:

```powershell
$env:ACTIVITYSIM_VIZ_CONFIG = "C:\deploy\activitysim_viz\config.yaml"
uv run panel serve scripts/host_dashboard.py --address 127.0.0.1 --port 5006
```

For a service behind a reverse proxy, bind the process to all container/host
interfaces and allow the public WebSocket origin:

```powershell
uv run panel serve scripts/host_dashboard.py --address 0.0.0.0 --port 5006 --allow-websocket-origin dashboard.example.org
```

Use the scheme/host value expected by the deployed Panel version when the
public URL is nonstandard, and repeat the origin option if the deployment has
several valid hosts. The proxy must forward WebSocket upgrade headers as well
as ordinary HTTP. Terminate TLS and enforce authentication in the proxy or the
chosen hosting provider unless the deployment deliberately adds those concerns
to the application.

A provider SDK can instead receive `dashboard` from the same script. Put
secrets and deployment IDs in environment variables, a secret store, or
provider configuration. Do not put them in the main visualizer YAML.

This approach has the following properties:

- hosting imports a ready-to-serve object instead of calling blocking
  `pn.serve()`;
- summary and prepared cache contracts remain identical to local mode;
- enabled pages determine the data loaded; and
- provider dependencies can live in an optional dependency group.

For a hosted service, caches must exist in persistent storage. To build caches
at startup, call the public prepare and summarize workflows before
`build_dashboard()`. Make the runtime cost and write permissions explicit.

### Deployment Requirements

Before treating the command as a production service, verify:

| Requirement | Deployment rule |
|---|---|
| Code/imports | Install the package or start from a working directory where `dashboard`, `processor`, and `runtime` are importable. Keep the deployed code version aligned with the cache schema. |
| Configuration | Set `ACTIVITYSIM_VIZ_CONFIG` to an explicit readable file. Resolve relative paths intentionally; absolute cache/input paths are safer in containers. |
| Summary caches | Mount `<root>` as persistent readable storage. All enabled summary-backed pages need compatible run manifests. |
| Prepared caches | Mount them when any enabled live page has optional or required prepared data. HTML export alone cannot replace this live requirement. |
| Permissions | Read-only cache mounts are sufficient when artifacts are built before deployment. Grant writes only when startup intentionally builds or refreshes caches. |
| Network | Expose the selected port, configure the public WebSocket origin, and preserve WebSocket upgrades through the proxy/load balancer. |
| Sessions and memory | Panel creates server-side sessions. Size workers for the loaded summary/prepared data and expected concurrent sessions; do not assume a standalone HTML memory profile. |
| Security | Put TLS, authentication, secrets, and access logs in the provider/proxy boundary unless a reviewed adapter owns them. |
| Startup failure | Fail the deployment when config or required caches cannot load. Do not serve a process that silently has no configured runs. |

The `panel serve` command above loads caches and serves the app. It does not run
prepare or summarize. Build and validate artifacts in a separate deployment
step unless startup generation is an explicit operational choice.

## Option B: Make `dashboard_mode: host` A Core Adapter

Use this approach only when one hosting provider must be a supported runtime mode.

1. Add a typed `HostSettings` model in `runtime/config/models.py`.
2. Normalize `dashboard.host` in a focused parser and pass it into `Config`.
3. Add hosting settings to the presentation signature, excluding secrets.
4. Create a narrow adapter such as `runtime/hosting.py`:

   ```python
   def publish_dashboard(*, dashboard, settings: HostSettings) -> None:
       """Hand a built Panel object to the configured hosting provider."""
   ```

5. Let `resolve_dashboard_execution_mode("host")` remain `host` instead of
   converting it to `live`.
6. Reuse the standard workflow loading and `build_dashboard()` path, then call
   the adapter instead of `pn.serve()`.
7. Put provider SDKs in a `hosting` optional dependency group in
   `pyproject.toml`.
8. Test dispatch with a fake adapter; do not contact the provider in unit tests.

The boundary should look like:

```text
config + validated caches
  -> standard dashboard data requirements
  -> build_dashboard(...)
  -> provider adapter
  -> hosted application
```

Do not put provider logic in pages, `dashboard/app.py`, or summary workflows.
These layers must operate locally, in export, and with a future host.

## Hosting Test Matrix

- missing config/cache produces an actionable startup error;
- summary-only hosting does not load prepared tables;
- prepared-data pages load only declared tables;
- provider adapter receives the built dashboard and typed settings;
- secrets do not enter logs, signatures, manifests, or exports;
- live and export modes remain unchanged; and
- `host` no longer emits the fallback warning once implemented.

## Related Chapters

- [12 - Running Workflows](12-running-workflows.md)
- [17 - Publish An Export With Posit Connect Cloud](17-posit-connect-cloud.md)
- [34 - HTML Export](34-html-export.md)
- [40 - Developer Workflows](40-developer-workflows.md)
- [41 - Data Extension Cookbook](41-data-extension-cookbook.md)
- [42 - Config, Columns, And Labels](42-config-column-label-cookbook.md)
