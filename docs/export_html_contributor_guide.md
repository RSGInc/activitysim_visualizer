# Export HTML Contributor Guide

This guide explains how the standalone HTML export works after the sectioned page API refactor.

Use it when you are:

- adding export support for a page
- changing selector behavior in export
- changing the Python-to-JavaScript payload/runtime contract

## Mental Model

The export path does not save the live Panel app directly.

Instead it:

1. resolves the enabled leaf pages
2. instantiates the same `DashboardPage` objects used by live mode
3. reads registered selectors and sections from each page instance
4. pre-renders the needed selector variants per section
5. serializes the resulting page shell and region snapshots into JSON
6. renders that JSON with `dashboard/export/assets/export_runtime.js`

Export metadata comes from the same runtime `selector(...)` and `section(...)`
registrations used by the live dashboard; pages do not maintain a parallel
export declaration.

## Source of Truth

For new-style pages, export support is derived from:

- `@dashboard_page(...)`
- `DashboardPage.build_page()`
- `self.selector(...)`
- `self.section(...)`

The `@dashboard_page` declaration owns:

- page identity
- ordering
- group membership
- summary/prepared-data requirements

The page instance owns:

- selector widgets
- section dependencies
- exportable section boundaries

## What Makes a Page Export-Friendly

The serializer handles these common Panel types well:

- `pn.Column`
- `pn.Row`
- `pn.Card`
- `pn.Tabs`
- `pn.pane.Markdown`
- `pn.pane.HTML`
- `pn.pane.Plotly`
- `pn.widgets.Tabulator`
- `pn.widgets.Select`
- `pn.widgets.RadioButtonGroup`
- `pn.Spacer`

A good interactive export page usually has:

- a small bounded selector option set
- stable widget instances created in `build_page()`
- sections whose content can be fully pre-rendered

## Export Metadata Derivation

Registered selectors become export selector metadata.

Registered sections become export regions when `export=True`.

Section selector dependencies do double duty:

- they drive live section-aware refresh
- they define the selector dimensions that need offline variants

`export=False` on a section keeps it static in the exported page shell.

`exportable=False` on a selector keeps the control visible in live mode while disabling offline interactivity for that selector.

## Page Authoring Expectations

For export-aware pages:

- create widgets in `build_page()`
- register selectors with stable ids
- register sections with stable ids
- keep section render functions deterministic for a given widget state
- declare dynamic widget options/defaults on `select(...)`; the framework
  reconciles them before each export state is rendered

Do not add new export-only registries or duplicate selector metadata in `PAGE`.

## Config Shape

Standalone page selectors are configured under:

```yaml
dashboard:
  export:
    pages:
      trip_mode:
        tour_purpose: all
```

Grouped page selectors are configured under:

```yaml
dashboard:
  export:
    pages:
      trip_summaries:
        children:
          trip_mode:
            tour_purpose: all
```

Grouped pages are identified by leaf `page_id`, not `child_id`.

## Runtime Validation

Export config validation checks:

- unknown page ids
- unknown group ids
- unknown selector ids
- unknown part ids

Selector ids and part ids resolve from the runtime registration graph shared by
live and export modes.

## When You Change the Contract

If you change the payload or runtime behavior:

1. update `dashboard/export/types.py`
2. update `dashboard/export/payload.py`
3. update `dashboard/export/serializer.py` if node serialization changed
4. update `dashboard/export/assets/export_runtime.js`
5. update `docs/export_html_schema.md`
6. update the export payload and smoke tests

The generated runtime asset is now built from `dashboard/export/js_runtime/` by
`dashboard/export/build_export_runtime.py`. Make source changes in `js_runtime/`, then
rebuild the committed asset.

## Recommended Tests

At minimum, touch the relevant subset of:

- `tests/test_export_payload.py`
- `tests/test_export_html.py`
- `tests/test_export_html_smoke.py`
- `tests/test_export_serializer.py`
- `tests/test_export_warnings.py`

Good export-focused assertions now include:

- selector metadata derives from `selector(...)`
- region metadata derives from `section(...)`
- grouped descriptors use `default_page_id`
- grouped config resolves children by leaf `page_id`
- unrelated sections do not produce unnecessary selector variants
