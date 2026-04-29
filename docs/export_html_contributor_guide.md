# Export HTML Contributor Guide

This guide explains how to extend the standalone HTML export safely.

Use it when you are:

- adding export support for a new page
- adding export support for a page-local selector
- changing the export payload/runtime contract
- deciding whether a page should stay static in export mode

## Mental Model

The export path is a custom client-side renderer. It does not save the live Panel app directly.

The flow is:

1. `runtime_workflows.run_dashboard_workflow()` calls `dashboard.export.html.write_export_html_document()`.
2. `dashboard.export.payload.build_export_payload()` resolves export pages, selector config, and dashboard-level states.
3. `dashboard.export.serializer.serialize_viewable()` converts supported Panel objects into a JSON-safe node tree, substituting declared export regions with embedded region nodes.
4. `dashboard.export.runtime_assets.build_export_html_shell()` embeds the payload plus the runtime assets into one HTML file.
5. `dashboard/export/assets/export_runtime.js` validates the payload and renders the offline UI in the browser.

This approach exists to keep the output:

- single-file
- smaller than a full live-app export
- explicit about which state combinations are shipped offline

## Source of Truth

Page and selector metadata is page-owned.

That means export support should come from:

- `dashboard/pages/<page>.py`
- `dashboard/pages/<group>/<child>.py` for grouped child pages
- the module-level `PAGE = DashboardPageDefinition(...)`
- `dashboard/pages/<group>/__init__.py` when the page lives inside a top-level group
- `PAGE.selectors` entries declared with `PageSelectorDefinition(...)`

Do not add a second export-only registry.

Shared registry helpers in `dashboard/page_registry.py` already provide:

- page discovery
- page id validation
- selector id validation
- live page ordering
- export page ordering
- exportable selector discovery

## How Export Discovers Pages

`dashboard.page_registry.all_page_definitions()` imports standalone modules in `dashboard/pages/` plus child modules one level below grouped directories and looks for a module-level `PAGE`.

Export page selection then happens through `resolve_export_page_definitions(config)`.

Rules:

- if `visualizer.export_html.pages` is omitted, export uses the default-enabled pages
- if `visualizer.export_html.pages` is present, export uses those page/group ids in config order
- invalid page ids fail before rendering
- invalid selector ids fail before rendering

## Adding Export Support for a Page

### 1. Make sure the page is registry-backed

The page must already follow the standard page pattern:

- `DashboardPage` subclass
- module-level `PAGE = DashboardPageDefinition(...)`
- stable `page_id`
- `controller_cls` set on `PAGE`

### 2. Keep the page view export-safe

The serializer currently supports:

- `pn.Column`
- `pn.Row`
- `pn.Card`
- `pn.Tabs`
- `pn.pane.Plotly`
- `pn.widgets.Tabulator`
- `pn.widgets.Select`
- `pn.widgets.RadioButtonGroup`
- `pn.pane.Markdown`
- `pn.pane.HTML`
- `pn.Spacer`
- plain strings

If the page uses a different Panel object type, export will currently fall back to an unsupported-item panel or fail in the runtime if a new `kind` is emitted without runtime support.

### 3. Decide whether the page should be static or selector-driven offline

A page should remain static in export mode when:

- local controls are too expensive to pre-expand into variants
- the widget type is not supported by the export serializer/runtime
- the page depends on server callbacks or dynamic data fetching
- exporting all selector combinations would create an unreasonably large artifact

A page is a good candidate for selector-driven export when:

- it uses a small bounded set of options
- the view can be fully precomputed during export
- the widget meaning is important for offline review

### 4. Declare explicit export regions for selector-driven pages

Pages with export-enabled selectors must declare `PAGE.export_regions`.

Example:

```python
PAGE = DashboardPageDefinition(
    page_id="trip_mode",
    title="Trip Mode",
    controller_cls=TripModePage,
    selectors=(...),
    export_regions=(
        PageExportRegionDefinition(
            region_id="trip_summary_mode_body",
            view_attr="_body",
            selector_ids=("tour_purpose", "tour_mode"),
        ),
    ),
)
```

Rules:

- `region_id` must be unique within the page
- `view_attr` must resolve to a stable page attribute pointing at the root viewable for that dynamic subtree
- `selector_ids` must reference declared page selectors
- every export-enabled selector on the page must be referenced by at least one region
- regions must not overlap or nest in v1

Prefer meaningful sections over per-chart micromanagement. Static content should stay outside regions whenever it does not depend on page selectors.

### 5. Verify missing-data behavior

Export instantiates the same page controllers used by live mode. If a page can render a friendly fallback in live mode when summaries or raw data are missing, that same behavior will serialize into export.

## Adding Export Support for a Selector

### 1. Declare the selector in `PAGE.selectors`

Example:

```python
PAGE = DashboardPageDefinition(
    page_id="trip_mode",
    title="Trip Mode",
    controller_cls=TripModePage,
    selectors=(
        PageSelectorDefinition(
            selector_id="tour_purpose",
            widget_attr="tour_purpose_sel",
            label="Tour Purpose",
        ),
    ),
)
```

Selector fields:

- `selector_id`: stable config-facing id under `visualizer.export_html.pages.<page_id>.<selector_id>` for standalone pages, or under `visualizer.export_html.pages.<group_id>.children.<child_id>.<selector_id>` for grouped child pages
- `widget_attr`: attribute on the page instance that resolves to the actual Panel widget
- `label`: serialized label shown in export
- `enabled_when`: optional predicate when selector availability depends on page/config state
- `exportable`: set `False` when you want metadata but not offline interactivity

### 2. Keep the widget instance stable

Create widgets in `__init__` and update values/options in `_refresh()`. Export finds widgets by object identity and uses that mapping during serialization.

### 3. Make the option set deterministic

Export resolves actual selector values against `widget.options`. That means:

- options should be fully populated before export serialization
- invalid configured values should fail clearly
- current `widget.value` should be a valid default

### 4. Configure export values in YAML

Example:

```yaml
visualizer:
  export_html:
    pages:
      trip_mode:
        tour_purpose: all
        tour_mode:
          - All
          - DRIVE
      tours:
        children:
          summary:
            person_type: all
```

Supported request patterns depend on `runtime.config.ExportSelectorRequest`, but the export builder currently handles:

- default value only
- all options
- explicit values validated against actual widget options

### 5. Understand fallback behavior

If a selector is configured but unavailable at export time:

- export logs one warning
- the selector is marked unavailable in metadata
- any affected region falls back to non-interactive default content for that selector

## Required Tests

When changing export support, update tests in the same change.

Minimum expectations:

- `tests/test_page_registry_contract.py` if page registration or export contract behavior changed
- `tests/test_export_payload.py` for payload shape, page descriptors, selector metadata, and region structure
- `tests/test_export_serializer.py` if the serializer learned a new node kind or widget behavior
- `tests/test_export_html_smoke.py` if the final HTML wiring changed
- `tests/test_export_warnings.py` for degraded/fallback selector behavior
- `tests/test_export_size_budget.py` if the representative export grows materially

## When You Change the Runtime Contract

If you add a new node kind or otherwise change the Python/JS contract:

1. Update `dashboard/export/types.py`.
2. Update `dashboard/export/serializer.py`.
3. Update `dashboard/export/assets/export_runtime.js`.
4. Update any page modules that need new or changed `export_regions`.
4. Update `docs/export_html_schema.md`.
5. Update the relevant tests.

Do not ship a Python-side schema change without the matching runtime change.

## Useful Commands

Typical export-focused test slice:

```powershell
$env:UV_CACHE_DIR = (Resolve-Path .).Path + '\.uv_cache'
uv run --with pytest pytest --basetemp .pytest_tmp `
  tests\test_export_html.py `
  tests\test_export_html_smoke.py `
  tests\test_export_payload.py `
  tests\test_export_serializer.py `
  tests\test_export_size_budget.py `
  tests\test_export_warnings.py `
  tests\test_page_registry_contract.py `
  tests\test_page_ordering.py
```

## Extension Checklist

Before opening a PR, confirm:

1. The page or selector is declared in the page module, not in an export-only registry.
2. The live dashboard still works.
3. `--export-html` still produces one self-contained file.
4. New selector values are bounded and intentional.
5. Tests cover payload shape and any new runtime behavior.
6. The schema doc is updated if the payload/runtime contract changed.
