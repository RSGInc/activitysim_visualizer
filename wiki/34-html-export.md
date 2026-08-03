# 34 - HTML Export

HTML export writes a standalone dashboard file that can be opened without a
Python server.

```text
registered dashboard pages
  -> export payload
  -> serialized Panel nodes
  -> embedded CSS, Plotly, and runtime JS
  -> one HTML file
```

## When To Use Export

Use export when you need:

- an offline deliverable
- a dashboard that can be emailed or archived
- a frozen set of run comparisons
- no Python server dependency for viewers

Use live mode when you need:

- full Python-backed interactivity
- exploratory pages that are not export-ready
- development/debugging feedback

## Export Configuration

Keep the workflow and output path in the main config:

```yaml
root: artifacts

pipeline:
  steps: [summarize, dashboard]
  dashboard_mode: export

dashboard:
  export:
    output_path: exports/dashboard.html
```

Run the same command used for every configured workflow:

```bash
uv run activitysim-viz --config local_config.yaml
```

This writes `artifacts/exports/dashboard.html`. Relative export paths resolve
below `root`; an absolute path writes elsewhere. Change
`pipeline.dashboard_mode` back to `live` when the same config should serve the
dashboard instead.

Export begins with the pages resolved by `dashboard.live.pages`. The
`dashboard.export.pages` mapping modifies matching page selectors and parts; it
does not select the included page set. Use a page override with `enabled: false`,
`exclude_pages`, or `exclude_groups` to narrow the live set. Export cannot add a
page that live configuration omitted.

## Supported Runtime Behavior

The export runtime supports a deliberately small set of rendered objects:

- containers
- cards
- tabs
- Plotly panes
- tables
- Markdown/HTML panes
- registered regions
- registered selector widgets

The Python-to-JavaScript contract lives in `dashboard/export/types.py`, and the
browser runtime lives under `dashboard/export/js_runtime/`.

## Selector Variants

Page-local export interactivity is pre-rendered. During export, the runtime
walks configured selector values, renders page regions, serializes them, and
stores them as variants.

That means:

- exported selectors can only switch among values generated at export time
- large selector domains can make export files large
- pages must register selectors and sections through the page API
- live-only callbacks do not automatically work in export

Selector and part names are author-defined IDs, not widget labels or section
titles. Find selector IDs in a page's `self.select(...)` and
`self.selector(...)` calls, and part IDs in `self.section(...)` calls. Feature
IDs prefix their components (for example, `comparison.metric` and
`comparison.body`). The page/group IDs are listed in the generated catalog in
chapter 31, and chapter 13 contains a complete override example. Invalid page,
selector, part, or selector-value entries fail or produce a targeted warning
rather than being silently guessed.

For a concrete selector/section declaration that works in both modes, see the
[Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md#add-a-dynamic-selector).

## Page Authoring Contract

Export metadata comes from the same page registration graph used by the live
dashboard:

- `@dashboard_page(...)` owns page identity, grouping, order, and data
  requirements.
- `build_page()` creates stable widgets, sections, features, and layout.
- `self.select(...)` registers ordinary dropdowns and their option/default
  policy.
- `self.selector(...)` registers custom widgets.
- `self.section(...)` defines refresh and export-region boundaries.

Keep section renderers deterministic for a given selector state. Set
`export=False` on a section that should remain static in the exported shell,
and `exportable=False` on a selector that should remain live-only. Do not add a
second export-only registry or duplicate selector metadata on the page
definition.

Grouped export configuration addresses children by their leaf `page_id`:

```yaml
dashboard:
  export:
    pages:
      trip_summaries:
        children:
          trip_mode:
            tour_purpose: all
```

Validation rejects unknown page, group, selector, and part IDs against this
shared runtime graph.

## Prepared Data Is A Live-Only Boundary

The export workflow loads summary caches but does not load prepared runs. A
section that reads prepared data must declare that boundary:

```python
trip_table = self.section(
    "trip_table",
    export_data_mode="required",
    render=self.render_trip_table,
)
```

During HTML export, any section whose `export_data_mode` is `optional` or
`required` is skipped. The distinction still documents whether the feature is
optional or essential in live mode. Summary-only sections use the default
`export_data_mode="none"` and remain eligible for export. Split mixed pages
into separate prepared-backed and summary-backed sections so the latter can be
exported safely.

## Important Files

| File | Role |
|---|---|
| `dashboard/export/html.py` | Builds and writes the final HTML document. |
| `dashboard/export/payload.py` | Builds export payloads and selector variants. |
| `dashboard/export/page_serializer.py` | Walks one registered page and serializes its selector states and sections. |
| `dashboard/export/selector_states.py` | Resolves selector domains, configured values, and scoped widget state. |
| `dashboard/export/traversal.py` | Projects registered page components onto the export traversal contract. |
| `dashboard/export/serializer.py` | Converts Panel objects to export nodes. |
| `dashboard/export/types.py` | Defines payload and node dataclasses. |
| `dashboard/export/runtime_assets.py` | Loads CSS and JavaScript runtime assets. |
| `dashboard/export/js_runtime/` | Readable browser runtime source. |
| `dashboard/export/assets/export_runtime.js` | Built browser runtime embedded in exports. |

## Changing Export Runtime Behavior

Checklist:

1. Update Python payload or node types.
2. Update serializer or payload builder.
3. Update JavaScript runtime source.
4. Rebuild `assets/export_runtime.js` with
   `uv run python dashboard/export/build_export_runtime.py`.
5. Add/update fixture, contract, and smoke tests.
6. Bump `EXPORT_SCHEMA_VERSION` if older payloads are no longer safe.
7. Update this wiki chapter if user-visible behavior changed.
8. Update the [HTML Export Schema](36-html-export-schema.md) when the payload
   contract changed.

## Debugging Exports

1. Open the exported HTML in a browser.
2. Open developer tools and check the console.
3. Look for `ExportRuntimeError` messages.
4. Try `?debug_export=1` in the URL.
5. Compare live mode to export mode with the same config and summary caches.

## Related Chapters

- [30 - Output Visualizer](30-output-visualizer.md)
- [32 - Figures and Widgets](32-figures-and-widgets.md)
- [90 - Troubleshooting](90-troubleshooting.md)
- [45 - Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md)
- [36 - HTML Export Schema](36-html-export-schema.md)
