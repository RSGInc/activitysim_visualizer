# 36 - HTML Export Schema

This document defines the Python-to-JavaScript contract for the standalone
dashboard export.

The implementation lives under `dashboard/export/`:

- `dashboard/export/html.py`: entry points that build and write the final
  self-contained HTML document
- `dashboard/export/payload.py`: dashboard-state and top-level payload composition
- `dashboard/export/traversal.py`: page-tree and export-region resolution
- `dashboard/export/selector_states.py`: selector request and canonical-state enumeration
- `dashboard/export/page_serializer.py`: page-shell and region-variant serialization
- `dashboard/export/serializer.py`: Panel-to-payload node serialization
- `dashboard/export/runtime_assets.py`: asset loading and HTML shell assembly
- `dashboard/export/types.py`: typed payload and node definitions
- `dashboard/export/js_runtime/`: readable browser-runtime source split into small files
- `dashboard/export/assets/export_runtime.js`: client runtime that validates and renders the payload
- `dashboard/export/build_export_runtime.py`: concatenates `js_runtime/` into
  the shipped runtime asset

## Top-Level Payload

The exported HTML contains one JSON payload in:

```html
<script id="activitysim-export-data" type="application/json">...</script>
```

`dashboard/export/types.py` defines the payload as `ExportPayload`.

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

Current protocol identifiers are `schema_version: "2.0"`,
`client_runtime: "region-swap-v1"`, and
`page_export_support.client_side_runtime: "dashboard-and-page-selectors"`.
Treat them as compatibility identifiers, not user-visible labels.

### Dashboard Chrome And State Fields

| Object | Complete fields |
|---|---|
| `runs_loaded[*]` | `label`, `color` |
| `chrome` | `layout`, `rail_sections`, `controls_enabled` |
| `chrome.controls_enabled` | Boolean `weighting`, Boolean `values` |
| `dashboard_controls` | `weighting` list and `values` list |
| `default_state` | `weighting`, `values` |
| `page_export_support` | `client_side_runtime`, `enabled_page_selectors` |
| `enabled_page_selectors[*]` | `page_id`, `selector_id` |

The runtime uses the options in `dashboard_controls` to validate
`default_state` and to form state keys. A control can remain in the payload
while `controls_enabled` disables switching because only one value was
exported.

`dashboard/export/payload.py` builds the dashboard state key for `states`:

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
| `selectors` | `list[SelectorMetadataPayload]` | Export metadata for page-local selectors registered on the page instance |
| `children` | `list[PageDescriptorPayload]` | Child page descriptors when this entry is a grouped top-level page |
| `default_page_id` | `str \| None` | Default leaf page used when a grouped export page first loads |

The shared page registry sets the top-level page order. Grouped pages keep their
child pages under one top-level export tab. Content in `states` uses the final
page ID as its key.

## Selector Metadata

Each `SelectorMetadataPayload` contains:

| Field | Type | Purpose |
|---|---|---|
| `id` | `str` | Stable selector id registered with `DashboardPage.selector(...)` |
| `label` | `str` | Human-readable label used in exported widget chrome |
| `available` | `bool` | Whether the selector existed and was available for the current page/config state |
| `request_mode` | `str` | Config request mode such as `default`, `all`, or explicit values |
| `requested_values` | `list[str]` | Raw values requested by config before resolution against widget options |
| `resolved_values` | `list[str]` | Final export values after validation against widget options |
| `default_value` | JSON-compatible value | Selector value restored after variant generation and used for initial page state |
| `options` | `list[str]` | Full live widget options observed during serialization |
| `export_enabled` | `bool` | Whether the selector is interactive in export or rendered as a disabled/static control |
| `parent_selector_id` | `str` (optional) | Parent selector for a dependent option domain |
| `options_by_parent_value` | `dict[str, list[str]]` (optional) | Child options keyed by parent value |
| `disabled_parent_values` | `list[str]` (optional) | Parent values that disable the dependent selector |

Selector config is driven from:

```yaml
dashboard:
  export:
    pages:
      <page_id>:
        <selector_id>: ...
```

You can also configure grouped child pages as follows:

```yaml
dashboard:
  export:
    pages:
      <group_id>:
        children:
          <page_id>:
            <selector_id>: ...
```

The shared page registry supplies these validation rules:

- unknown page ids fail in `validate_page_export_config()`
- unknown selector ids fail in `validate_page_export_config()`
- unavailable configured selectors write one warning to the log and use a static region or page

## Page Content Shape

`PageContentPayload` always has these fields:

| Field | Type | Purpose |
|---|---|---|
| `kind` | `"page"` | Discriminator |
| `content` | `ExportNode` | Serialized page shell that starts with a standard export node tree |

Pages without export-enabled selectors create a standard page shell whose tree
has no `region` nodes. Pages with export-enabled selectors create one stable
page shell with one or more `region` nodes.

## Region Nodes

`region` is an `ExportNode` kind that changes one part of a node tree.

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
| `variant_aliases` | `dict[str, str]` | Alternate selector keys mapped to a canonical rendered variant |

`dashboard.export.serializer.variant_key()` generates JSON variant-key strings.

Example:

```json
["All","DRIVE"]
```

The value order in the key must agree with `selector_ids`.

If a configured selector is unavailable at export time, the region has empty
`selector_ids` and `default_content`. It has no interactive variants.

## Supported Node Kinds

The browser runtime supports only the node kinds in `dashboard/export/types.py`.

| Kind | Produced from | Important fields |
|---|---|---|
| `container` | `pn.Column`, `pn.Row` | `layout`, `children`, `child_count`, `styles`, `css_classes` |
| `card` | `pn.Card` | `title`, `children` |
| `tabs` | `pn.Tabs` | `tabs` |
| `region` | exportable `DashboardPage.section(...)` registrations | `region_id`, `selector_ids`, `default_content`, `variants` |
| `plotly` | `pn.pane.Plotly` | `figure` |
| `table` | `pn.widgets.Tabulator` | `columns`, `rows` |
| `widget` | registered Panel widgets | `widget_type`, `name`, `value`, `options`, `step`, `disabled`, `selector_id`, `export_enabled`, optional dependent-selector fields |
| `html` | `pn.pane.Markdown`, `pn.pane.HTML`, plain strings, unsupported fallback markup | `html` |
| `spacer` | `pn.Spacer` | no extra fields |

An unsupported object becomes an `html` node with a visible fallback panel. An
unknown node kind is an error, which the runtime shows in an error panel.

The supported widget types are `select`, `radio_button_group`, `float_input`,
`checkbox`, and `button`. `SelectorMetadataPayload.default_value` and widget
values can be all JSON-compatible values. They are not limited to strings.

### Complete Node Fields

Every node has a `kind` discriminator and only the fields for that kind:

| Kind | Required fields | Optional fields |
|---|---|---|
| `container` | `layout`, `children`, `child_count`, `styles`, `css_classes` | none |
| `card` | `title`, `children` | none |
| `tabs` | `tabs`; each tab has `title`, `content` | tab `full_title` |
| `plotly` | `figure` | `height`, `aspect_ratio` |
| `table` | `columns`, `rows` | `column_tooltips` |
| `widget` | `widget_type`, `name`, `value`, `options`, `step`, `disabled`, `selector_id`, `export_enabled` | `parent_selector_id`, `options_by_parent_value`, `disabled_parent_values` |
| `html` | `html` | none |
| `spacer` | none | none |
| `region` | `region_id`, `selector_ids`, `content_mode`, `default_key`, `default_content`, `variants`, `variant_aliases` | none |

`container.layout` is `row` or `column`. `widget_type` is one of
`radio_button_group`, `select`, `float_input`, `checkbox`, or `button`.
`region.content_mode` is currently `snapshot`.

Plotly's `figure` field is its JSON-compatible figure dictionary. Table rows
are dictionaries keyed by the ordered `columns`. HTML is already serialized
markup; the browser runtime does not execute Python pane logic.

## Diagnostics Sidecar Schema

`write_export_html_document()` writes `<stem>.diagnostics.json` beside the
HTML. It is build-time diagnostic data and is not required to open the HTML.
The top-level shape is:

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | integer, currently `1` | Diagnostics format version; separate from export payload `2.0`. |
| `title` | string | Dashboard title. |
| `states` | mapping | Page and region diagnostics keyed by `<Weighting>||<Values>`. |
| `size_analysis` | mapping | Estimated compact-JSON bytes by state, page, and region. |

For each dashboard state, `states[state_key][page_id]` is a mapping containing:

- `default`: visualization diagnostics for the default page state;
- `export_region:<region_id>`: selector enumeration counts; and
- `region:<region_id>:<variant_key>`: visualization diagnostics captured for
  one rendered region variant.

A visualization diagnostic has these fields:

| Field | Meaning |
|---|---|
| `visualization_id` | Summary or prepared input used as the diagnostic boundary. |
| `render_state` | `rendered`, `partial`, or `skipped`. |
| `input_kind` | `summary`, `prepared`, or `mixed`. |
| `input_ids` | Source summary/prepared IDs. |
| `usable_run_labels` | Runs included in that output. |
| `excluded_runs` | Per-run exclusions. |

Each excluded run contains `label`, `status`, `detail`, `source_kind`,
`source_id`, and `missing_columns`. An export-region enumeration record
contains `selector_ids`, `selector_counts`, `raw_state_count`,
`valid_state_count`, `alias_count`, and `pruned_state_count`.

`size_analysis` contains:

| Field | Contents |
|---|---|
| `warning_thresholds` | Byte thresholds for total, strong-total, page, static-region, and selector-region warnings. |
| `total_payload_bytes`, `state_count` | Whole payload estimate and number of dashboard states. |
| `states` | Per-state `payload_bytes`; each page has `payload_bytes` and region metrics. |
| `page_peaks` | Largest state for each page. |
| `region_peaks` | Largest state for each page/region. |

Region size metrics contain `selector_ids`, `variant_count`,
`default_content_bytes`, `variants_bytes`, and `total_bytes`. Current warning
thresholds are 100 MiB total, 250 MiB strong total, 10 MiB per page, 5 MiB for
a static region, and 1 MiB for a selector region. These are warnings, not hard
limits.

## Runtime Validation Rules

The embedded runtime validates these items:

- payload presence and JSON parseability
- `schema_version` compatibility
- presence of `pages`
- presence of `default_state`
- presence of `states`
- presence of `dashboard_controls`

At render time, it shows an error for these conditions:

- unknown rail sections
- unknown widget types
- unknown node kinds
- missing page state for the current dashboard selection
- missing region state for the active selector combination
- Plotly runtime failures

The HTML shows failures in a visible error panel and also writes them to the
browser console.

## Schema Versioning Policy

`EXPORT_SCHEMA_VERSION` currently lives in `dashboard/export/types.py`.

Rules:

1. Change `schema_version` when the browser runtime cannot safely use payloads
   from older Python code.
2. Keep the runtime check strict. A mismatch must show an error and must not
   render incorrect content.
3. Update this document, the readable files under
   `dashboard/export/js_runtime/`, rebuild the generated asset, and update the
   export payload/runtime tests in the same change.

## Checklist for Adding a New Node Kind

To add a serialized node kind:

1. Add the new typed shape to `dashboard/export/types.py`.
2. Emit it from `dashboard/export/serializer.py`.
3. Render it in `dashboard/export/js_runtime/`.
4. Run `uv run python dashboard/export/build_export_runtime.py` to rebuild
   `dashboard/export/assets/export_runtime.js`; do not edit the built asset.
5. Add serializer coverage in `tests/test_export_serializer.py`.
6. Add or update payload/smoke assertions if the new node can appear in representative exports.
7. Update this document.

## Related Chapters

- [34 - HTML Export](34-html-export.md)
- [45 - Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md)
- [46 - Testing](46-testing.md)
