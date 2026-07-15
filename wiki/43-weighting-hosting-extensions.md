# 43 - Weighting And Hosting Extensions

Weighting and hosting both cross major runtime boundaries. This chapter shows
the extension seams and the places where current behavior is deliberately
limited.

## Worked Example: Add A Weighting Mode

The current modes are `weighted` and `unweighted`. They are not just labels:
each mode produces a complete set of summary tables, its own cache directory,
dashboard state, and export states.

Suppose prepared tables gain a `calibrated_weight` column and the application
needs a third `calibrated` mode that uses it as `finalweight`.

## 1. Centralize The Mode And Transformation

`processor/summarize/cache_types.py` currently owns
`SUPPORTED_WEIGHTING_MODES` and `strip_weights()`. Add the mode and a transformer:

```python
SUPPORTED_WEIGHTING_MODES = ("weighted", "unweighted", "calibrated")


def use_calibrated_weights(run: RunData) -> RunData:
    def replace_weight(table: pl.DataFrame) -> pl.DataFrame:
        if "calibrated_weight" not in table.columns:
            return table
        return table.with_columns(
            pl.col("calibrated_weight")
            .cast(pl.Float64)
            .alias("finalweight")
        )

    return replace_run_tables(run, replace_weight)
```

The repository currently uses an explicit `RunData(...)` copy in
`strip_weights()`. Before adding more modes, extract that copy into a tested
helper such as `replace_run_tables()` so every prepared table, availability
record, skimjoin artifact, and sidecar is preserved consistently.

In `processor/summarize/builder.py`, replace the hard-coded two-mode dictionary
with one transform per mode:

```python
WEIGHTING_TRANSFORMS = {
    "weighted": lambda run: run,
    "unweighted": strip_weights,
    "calibrated": use_calibrated_weights,
}


def _runs_by_weighting_mode(run, config, weighting_modes):
    modes = normalize_weighting_modes(weighting_modes or config.weighting_modes)
    return {mode: WEIGHTING_TRANSFORMS[mode](run) for mode in modes}
```

Fail early if required calibrated columns are unavailable. Silently falling
back to ordinary weights would create plausible but incorrect results.

## 2. Remove Duplicate Config Validation

`runtime/config/loader.py` currently has its own literal set containing
`weighted` and `unweighted`. Make it call the shared
`normalize_weighting_modes()` or import `SUPPORTED_WEIGHTING_MODES`; otherwise
the YAML parser will reject a mode that the summary layer supports.

The config can then select:

```yaml
summarize:
  weighting_modes: [weighted, unweighted, calibrated]
```

`summary_signature_payload()` already includes the configured mode list, so the
summary cache identity changes. Cache manifests and storage are mostly
mode-generic, but tests must prove the new directory and manifest entries are
read and written.

## 3. Update Prepared-Data Dashboard Access

Summary-backed pages are already mostly generic:

- `SummaryRun.summaries_by_mode` is keyed by mode string;
- `DashboardState` builds selector labels from configured modes; and
- export selection uses configured modes.

Prepared-data access is still binary. `DashboardPreparedRunProvider` caches
weighted and unweighted runs, and several pages ask for
`weighted=(self.weighting_key == "weighted")`.

Change that API to accept a mode key:

```python
@dataclass
class DashboardPreparedRunProvider:
    runs_by_mode: dict[str, list[tuple[str, RunData]]]

    def get_runs_if_loaded(self, *, weighting_mode: str):
        if not self.is_loaded:
            return None
        return list(self.runs_by_mode[weighting_mode])
```

Or lazily build modes through the same transform registry used by summaries.
Update:

- `DashboardState.get_prepared_runs_if_loaded()`;
- `PageData.prepared*` accessors;
- skim summary pages and parking location; and
- tests for every prepared-data page under the new mode.

Do not map every non-`weighted` mode to unweighted. That is the current binary
assumption and would make `calibrated` wrong.

## 4. Decide How Outside Summaries Behave

`summary_table_map` currently copies one already-aggregated outside table into
every configured weighting mode. That is appropriate only when the outside
table is mode-independent.

If calibrated outside tables differ, extend the config contract explicitly,
for example:

```yaml
runs:
  - label: External
    summary_table_map_by_weighting:
      weighted:
        regional_emissions: inputs/emissions_weighted.csv
      calibrated:
        regional_emissions: inputs/emissions_calibrated.csv
```

That would require schema normalization, file identity, loading, overlay, and
cache-manifest tests. Do not infer filenames or silently reuse one table when
the semantics differ.

## 5. Test The Whole Mode

At minimum, prove:

- config accepts, orders, deduplicates, and rejects mode names correctly;
- the transform replaces weights on every relevant prepared table;
- a known summary produces expected calibrated values;
- cache write/load retains all modes;
- dashboard state selects the correct summary and prepared runs;
- export enumerates configured calibrated states; and
- outside summary behavior is explicit.

Useful suites:

```bash
pytest tests/test_config_refactor_phase1.py tests/test_summary_cache.py
pytest tests/test_dashboard_live.py tests/test_export_payload.py
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
