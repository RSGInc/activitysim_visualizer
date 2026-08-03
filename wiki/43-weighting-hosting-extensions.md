# 43 - Weighting And Hosting Extensions

Weighting and hosting both cross major runtime boundaries. Ordinary alternative
weights are configuration-driven. A Python registry remains available for
calculations that cannot be expressed as column selection, while hosting remains
a deliberately limited extension point.

## Worked Example: Add A Weighting Mode

The built-in modes are `weighted` and `unweighted`. A named column mode adds
another complete set of summary tables, cache entries, dashboard selector state,
and export states without requiring Python code.

Suppose ActivitySim writes `calibrated_hh_weight`, `calibrated_person_weight`,
and `calibrated_trip_weight` alongside its ordinary weights.

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

`label` is optional; an omitted label is generated from the mode ID. At least one
column must be configured. Supported source tables are `households`, `persons`,
and `trips`.

This differs from the three weight fields on a run. `hh_weight_col`,
`person_weight_col`, and `trip_weight_col` choose the one primary `weighted`
definition during prepare. `weighting.modes` preserves that primary definition
and adds named alternatives that can be compared in one dashboard.

### 2. Understand Propagation

The configured source columns replace `finalweight` on their respective
prepared tables. Related tables then receive consistent weights:

- a household source propagates to persons, trips, tours, days, and vehicles
  unless a more specific source is configured;
- a person source propagates to trips, tours, and days;
- a trip source propagates to tours as the mean selected trip weight for each
  `tour_id`; and
- trip and tour hypothetical-skim sidecars inherit the selected trip and tour
  weights.

You can configure only the levels that differ. For example, a mode containing
only `trips` changes trips and tours while leaving household, person, day, and
vehicle weights at their primary prepared values.

Source columns are validated on every prepared run before summaries begin. A
misspelling therefore produces an error naming the missing table and column
instead of silently reverting to another weight. Raw ActivitySim columns are
normally retained by prepare. When using `prepared_table_map`, include the named
source columns in those prepared files.

### 3. Cache, Dashboard, And Outside-Summary Behavior

The mode ID, selected source columns, and column-mode implementation version are
part of summary cache identity. Changing a source column invalidates incompatible
summary caches. The configured label is used by live and exported dashboard
selectors.

Declarative column modes reject mode-independent `summary_table_map` inputs.
An already aggregated outside table does not contain enough information to
recalculate another weighting mode. Use generated summaries for these modes or
provide the outside data through a custom workflow that makes its weighting
semantics explicit.

## Advanced: Custom Weight Calculations

Use a Python weighting module only when selecting columns is insufficient; for
example, when weights must be capped, scaled, joined from a control table, or
calculated from several prepared columns.

### 1. Create An Importable Extension Module

This example adds a capped form of the primary prepared weights. Create
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

`map_run_data_tables()` copies the complete `RunData`, transforms each DataFrame
table, and preserves availability metadata, diagnostics, skims, and skimjoin
artifacts. A transform must return a new `RunData` and must not mutate its input.

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

Use `extensions.modules` for a project-local/importable module and keep plugin
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

Module imports are executable code, so configuration containing extensions is
trusted configuration. Extension settings and each selected definition's
version, requirements, and outside-summary policy enter summary cache identity.

An installed package can advertise the same registration function with a
Python entry point instead:

```toml
[project.entry-points."activitysim_visualizer.weighting_modes"]
capped = "my_project.weighting:register_weighting_modes"
```

Use either the installed entry point or `extensions.modules`, not both for the
same definition. Duplicate IDs and labels fail during config loading.

### 3. Runtime Behavior

The weighting definition contract is the single source for config validation,
summary transforms, prepared-data transforms, display labels, and cache
compatibility:

- config preserves the requested mode order and rejects unknown IDs;
- the summary workflow applies each registered transform before running builders;
- cache directories and manifests use `mode_id`, while plugin `version` enters
  the summary config digest;
- dashboard/export selectors use `label` without deriving text from the ID;
- `PageData.prepared()` and `prepared_runs()` apply the selected mode lazily and
  cache the result for the dashboard session; and
- required source columns fail before a transform can silently fall back.

Ordinary pages do not branch on particular modes:

```python
prepared = self.data.prepared("trips")

# Only specialized code that deliberately requests another mode supplies it:
weighted = self.data.prepared("trips", weighting_mode="weighted")
```

### 4. Outside Summary Tables

Built-in `weighted` and `unweighted` definitions explicitly use
`external_summary_policy="copy"`, preserving current behavior. A custom mode
defaults to `reject`: a run using `summary_table_map` then fails clearly because
the runtime cannot prove that an already-aggregated file represents that mode.

Set the custom definition to `copy` only when the outside table is genuinely
mode-independent. Per-mode outside file maps are not currently supported.

### 5. Test The Whole Mode

At minimum, prove:

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

The safest first hosting extension is a thin deployment entrypoint that uses
the existing config, cache loader, page requirements, and `build_dashboard()`.
It should not duplicate prepare or summarize logic.

The current `pipeline.dashboard_mode: host` is only a placeholder: `run.py`
logs a warning and falls back to live `pn.serve`. The `dashboard.host` keys are
validated but are not yet normalized into `Config` or consumed.

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

Panel-compatible hosts can launch this module with their normal command. A
provider SDK can instead receive `dashboard` from the same script. Keep secrets
and deployment IDs in environment variables or provider configuration, not the
main visualizer YAML.

This approach has useful properties:

- hosting imports a ready-to-serve object instead of calling blocking
  `pn.serve()`;
- summary and prepared cache contracts remain identical to local mode;
- enabled pages determine the data loaded; and
- provider dependencies can live in an optional dependency group.

For a hosted service, caches must already exist or be available on persistent
storage. If startup should build them, call the public prepare/summarize
workflows before `build_dashboard()` and make the cost and write permissions
explicit.

## Option B: Make `dashboard_mode: host` A Core Adapter

Use this only when the same hosting provider should be a supported runtime
mode.

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
6. Reuse the normal workflow loading and `build_dashboard()` path, then call
   the adapter instead of `pn.serve()`.
7. Put provider SDKs in a `hosting` optional dependency group in
   `pyproject.toml`.
8. Test dispatch with a fake adapter; do not contact the provider in unit tests.

The boundary should look like:

```text
config + validated caches
  -> normal dashboard data requirements
  -> build_dashboard(...)
  -> provider adapter
  -> hosted application
```

Avoid putting provider logic in pages, `dashboard/app.py`, or summary
workflows. Those layers should remain usable locally, in export, and with any
future host.

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
- [34 - HTML Export](34-html-export.md)
- [40 - Developer Workflows](40-developer-workflows.md)
- [41 - Data Extension Cookbook](41-data-extension-cookbook.md)
- [42 - Config, Columns, And Labels](42-config-column-label-cookbook.md)
