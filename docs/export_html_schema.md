# Export HTML Schema

This document defines the Python-to-JavaScript contract used by the standalone offline dashboard export.

The implementation lives under `dashboard/export/`:

- `dashboard/export/html.py`: entry points that build and write the final self-contained HTML document
- `dashboard/export/payload.py`: payload assembly, page-shell construction, and region-local selector expansion
- `dashboard/export/serializer.py`: Panel-to-payload node serialization
- `dashboard/export/runtime_assets.py`: asset loading and HTML shell assembly
- `dashboard/export/types.py`: typed payload and node definitions
- `dashboard/export/assets/export_runtime.js`: client runtime that validates and renders the payload

## Top-Level Payload

The exported HTML embeds one JSON payload inside:

```html
<script id="activitysim-export-data" type="application/json">...</script>
```

The payload shape is defined in `dashboard/export/types.py` as `ExportPayload`.

Top-level fields:

| Field | Type | Purpose |
|---|---|---|
| `schema_version` | `str` | Versioned schema identifier checked by the browser runtime before rendering |
| `title` | `str` | Dashboard title shown in the export header |
| `runs_loaded` | `list[dict[str, str]]` | Run labels and colors used for the export legend |
| `chrome` | `ExportChrome` | Shell layout metadata and dashboard-control enablement flags |
| `dashboard_controls` | `DashboardControlsPayload` | Exported dashboard-wide weighting and values options |
| `default_state` | `DefaultStatePayload` | Initial dashboard control values used on load |
| `pages` | `list[PageDescriptorPayload]` | Ordered page descriptors shown as page tabs |
| `states` | `dict[str, dict[str, PageContentPayload]]` | Serialized page content for each dashboard-level state combination |
| `page_export_support` | `PageExportSupportPayload` | Metadata about export-enabled page selectors |
| `client_runtime` | `str` | Runtime family identifier for diagnostic/debugging purposes |

`states` is keyed by the dashboard state key built in `dashboard/export/payload.py`:

```text
<weighting_mode>||<value_mode>
```

Example:

```text
Weighted||Percent
```

## Page Descriptors

Each `PageDescriptorPayload` contains:

| Field | Type | Purpose |
|---|---|---|
| `id` | `str` | Stable page id from `DashboardPageDefinition.page_id` |
| `title` | `str` | Display title shown in the export page tabs |
| `selectors` | `list[SelectorMetadataPayload]` | Export metadata for page-local selectors declared in the page definition |
| `children` | `list[PageDescriptorPayload]` | Child page descriptors when this entry is a grouped top-level page |
| `default_child_id` | `str \| None` | Default child page used when a grouped export page first loads |

The top-level page order is resolved through the shared page registry. Grouped pages keep their child pages nested under a single top-level export tab, while serialized page content in `states` remains keyed by leaf page id.

## Selector Metadata

Each `SelectorMetadataPayload` contains:

| Field | Type | Purpose |
|---|---|---|
| `id` | `str` | Stable selector id from `PageSelectorDefinition.selector_id` |
| `label` | `str` | Human-readable label used in exported widget chrome |
| `available` | `bool` | Whether the selector existed and was available for the current page/config state |
| `request_mode` | `str` | Config request mode such as `default`, `all`, or explicit values |
| `requested_values` | `list[str]` | Raw values requested by config before resolution against widget options |
| `resolved_values` | `list[str]` | Final export values after validation against widget options |
| `default_value` | `str | None` | Selector value restored after variant generation and used for initial page state |
| `options` | `list[str]` | Full live widget options observed during serialization |
| `export_enabled` | `bool` | Whether the selector is interactive in export or rendered as a disabled/static control |

Selector config is driven from:

```yaml
visualizer:
  export_html:
    pages:
      <page_id>:
        <selector_id>: ...
```

Grouped child pages may also be configured as:

```yaml
visualizer:
  export_html:
    pages:
      <group_id>:
        children:
          <child_id>:
            <selector_id>: ...
```

Validation comes from the shared page registry:

- unknown page ids fail in `validate_page_export_config()`
- unknown selector ids fail in `validate_page_export_config()`
- unavailable configured selectors log a warning once and fall back to non-interactive region/static page behavior

## Page Content Shape

`PageContentPayload` is always:

| Field | Type | Purpose |
|---|---|---|
| `kind` | `"page"` | Discriminator |
| `content` | `ExportNode` | Serialized page shell rooted at a normal export node tree |

Pages without export-enabled selectors serialize as a normal page shell whose tree contains no `region` nodes. Pages with export-enabled selectors serialize one stable page shell with one or more embedded `region` nodes.

## Region Nodes

`region` is a first-class `ExportNode` kind used for subtree-level switching.

Fields:

| Field | Type | Purpose |
|---|---|---|
| `kind` | `"region"` | Discriminator |
| `region_id` | `str` | Stable page-owned id for the dynamic subtree |
| `selector_ids` | `list[str]` | Ordered selector ids that affect this region |
| `content_mode` | `"snapshot"` | Region payload mode. v1 always uses pre-rendered subtree snapshots |
| `default_key` | `str` | JSON-encoded selector combination restored on load/fallback |
| `default_content` | `ExportNode` | Serialized subtree for the default selector combination |
| `variants` | `dict[str, ExportNode]` | Mapping from selector-combination key to serialized subtree |

Variant keys are JSON strings generated by `dashboard.export.serializer.variant_key()`.

Example:

```json
["All","DRIVE"]
```

The order of values in the key must match `selector_ids`.

If a configured selector is unavailable for a region at export time, that region serializes with empty `selector_ids`, `default_content`, and no interactive variants.

## Supported Node Kinds

The browser runtime only supports the node kinds declared in `dashboard/export/types.py`.

| Kind | Produced from | Important fields |
|---|---|---|
| `container` | `pn.Column`, `pn.Row` | `layout`, `children` |
| `card` | `pn.Card` | `title`, `children` |
| `tabs` | `pn.Tabs` | `tabs` |
| `region` | explicit `DashboardPageDefinition.export_regions` entries | `region_id`, `selector_ids`, `default_content`, `variants` |
| `plotly` | `pn.pane.Plotly` | `figure` |
| `table` | `pn.widgets.Tabulator` | `columns`, `rows` |
| `widget` | `pn.widgets.Select`, `pn.widgets.RadioButtonGroup` | `widget_type`, `value`, `options`, `selector_id`, `export_enabled` |
| `html` | `pn.pane.Markdown`, `pn.pane.HTML`, plain strings, unsupported fallback markup | `html` |
| `spacer` | `pn.Spacer` | no extra fields |

Unsupported objects currently serialize to an `html` node containing a visible fallback panel. The runtime itself treats unknown node kinds as an error and shows an error panel.

## Runtime Validation Rules

The embedded runtime validates:

- payload presence and JSON parseability
- `schema_version` compatibility
- presence of `pages`
- presence of `default_state`
- presence of `states`
- presence of `dashboard_controls`

At render time it also fails visibly on:

- unknown rail sections
- unknown widget types
- unknown node kinds
- missing page state for the current dashboard selection
- missing region state for the active selector combination
- Plotly runtime failures

Failures are shown in the HTML via a visible error panel and also logged to the browser console.

## Schema Versioning Policy

`EXPORT_SCHEMA_VERSION` currently lives in `dashboard/export/types.py`.

Rules:

1. Change `schema_version` whenever the browser runtime can no longer safely consume payloads emitted by older Python code.
2. Keep the runtime check strict. A mismatch should fail loudly instead of rendering incorrect content.
3. Update this document, `dashboard/export/assets/export_runtime.js`, and the export payload tests in the same change.

## Checklist for Adding a New Node Kind

When adding a new serialized node kind:

1. Add the new typed shape to `dashboard/export/types.py`.
2. Emit it from `dashboard/export/serializer.py`.
3. Render it in `dashboard/export/assets/export_runtime.js`.
4. Add serializer coverage in `tests/test_export_serializer.py`.
5. Add or update payload/smoke assertions if the new node can appear in representative exports.
6. Update this document.
