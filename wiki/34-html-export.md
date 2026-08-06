# 34 - HTML Export

HTML export writes a standalone dashboard that opens without a Python server.

```text
registered dashboard pages
  -> export payload
  -> serialized Panel nodes
  -> embedded CSS, Plotly, and runtime JS
  -> one HTML file + diagnostics JSON sidecar
```

## When To Use Export

Use export for these requirements:

- an offline deliverable
- a dashboard that you can send or archive
- a fixed set of run comparisons
- no Python server dependency for viewers

Use live mode for these requirements:

- full Python-backed interactivity
- exploratory pages that are not export-ready
- development or debug feedback

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

Use the standard command for a configured workflow:

```bash
uv run activitysim-viz --config local_config.yaml
```

This command writes `artifacts/exports/dashboard.html`. Relative export paths
start from `root`; use an absolute path for a different location. To start the
live dashboard from the same configuration, set `pipeline.dashboard_mode` to
`live`.

The command also writes `artifacts/exports/dashboard.diagnostics.json`, a
sidecar file that records export warnings and size or state analysis. The HTML
file does not depend on this sidecar.

The sidecar distinguishes rendered, partial, and skipped visualization inputs
for every exported dashboard state and region variant. It also reports raw,
valid, aliased, and pruned selector combinations plus estimated JSON bytes by
state, page, and region. See
[36 - HTML Export Schema](36-html-export-schema.md#diagnostics-sidecar-schema)
for every field and current warning threshold.

For one override, use `--export-html [PATH]`. If you do not give a path, the
command uses the configured output path. If that path is absent, it uses
`<root>/exported_dashboard.html`. You must also select the dashboard step. Add
`--dashboard` if `pipeline.steps` does not contain it.

Export starts with the pages from `dashboard.live.pages`. The
`dashboard.export.pages` mapping changes matching page selectors and parts. It
does not select the page set. Use `enabled: false`, `exclude_pages`, or
`exclude_groups` to remove pages. Export cannot add a page that the live
configuration omits.

## Supported Runtime Behavior

The export runtime supports these rendered objects:

- containers
- cards
- tabs
- Plotly panes
- tables
- Markdown/HTML panes
- registered regions
- registered selector widgets

Use the header button to close or open the export sidebar. Plotly charts change
size after the layout changes. Long run names use short, unique tab and legend
labels. Tab tooltips and chart hover text show the full names.

The Python-to-JavaScript contract lives in `dashboard/export/types.py`, and the
browser runtime lives under `dashboard/export/js_runtime/`.

## Selector Variants

Before writing the file, the exporter processes configured selector values,
renders page regions, and stores those regions as export-data variants.

These rules apply:

- exported selectors can only switch among values generated at export time
- large selector domains can make export files large
- pages must register selectors and sections through the page API
- live-only callbacks do not automatically work in export

Selector and part names are IDs from the author. They are not widget labels or
section titles. Find selector IDs in `self.select(...)` and
`self.selector(...)` calls. Find part IDs in `self.section(...)` calls. Feature
IDs are prefixes for their components. Examples are `comparison.metric` and
`comparison.body`. The generated catalog in chapter 31 lists page and group
IDs. Chapter 13 contains a complete override example. An invalid page,
selector, part, or selector value causes an error or a specific warning.

For a concrete selector/section declaration that works in both modes, see the
[Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md#add-a-dynamic-selector).

## Page Authoring Contract

Live mode and export use the same page registration graph for metadata:

- `@dashboard_page(...)` owns page identity, grouping, order, and data
  requirements.
- `build_page()` creates stable widgets, sections, features, and layout.
- `self.select(...)` registers standard selection lists and their option/default
  policy.
- `self.selector(...)` registers custom widgets.
- `self.section(...)` defines refresh and export-region boundaries.

Make sure a section renderer gives the same result for a specified selector
state. Set `export=False` on a section that must stay static in the
exported shell. Set `exportable=False` on a live-only selector. Do not add an
export-only registry. Do not copy selector metadata to the page definition.

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

Validation compares page, group, selector, and part IDs with this shared runtime
graph. It rejects unknown IDs.

## Prepared Data Is A Live-Only Boundary

The export workflow loads summary caches. It does not load prepared runs. A
section that reads prepared data must declare this limit:

```python
trip_table = self.section(
    "trip_table",
    export_data_mode="required",
    render=self.render_trip_table,
)
```

HTML export omits sections whose `export_data_mode` is `optional` or `required`;
these values indicate whether a prepared-data feature is optional or required
in live mode. Summary-only sections use the default
`export_data_mode="none"` and can be exported. On a mixed page, separate the
prepared-data and summary-data sections so the latter can remain in the export.

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

## Export Write And Python APIs

`dashboard.export` exposes two entry points:

| API | Behavior |
|---|---|
| `build_export_html_document(runs, config, summary_runs=None) -> str` | Build, serialize, and validate a complete HTML document in memory. Useful for tests and callers that need the string. |
| `write_export_html_document(output_path, runs, config, summary_runs=None) -> Path` | Build the payload and stream JSON into a temporary HTML file.<br>Write the diagnostics sidecar through a temporary file.<br>Replace each destination only after the temporary file is complete.<br>This is the standard workflow method. |

Payload construction cleans NumPy and Pandas values before JSON encoding:
nonfinite numbers become JSON `null`, timestamps become ISO strings, and closing
script tags are escaped. The writer streams the JSON without creating a second
payload or final HTML string, which reduces peak memory use for exports with
many selector states. If conversion, shell creation, writing, or finalization
fails, an `ExportBuildError` identifies the phase and the writer removes its
temporary files.

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
3. Inspect the adjacent `<stem>.diagnostics.json` file for build warnings and
   size/state analysis.
4. Look for `ExportRuntimeError` messages.
5. Try `?debug_export=1` in the URL.
6. Compare live mode to export mode with the same config and summary caches.

## Related Chapters

- [30 - Output Visualizer](30-output-visualizer.md)
- [32 - Figures and Widgets](32-figures-and-widgets.md)
- [90 - Troubleshooting](90-troubleshooting.md)
- [45 - Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md)
- [36 - HTML Export Schema](36-html-export-schema.md)
