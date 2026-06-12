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

## Export Command

```bash
python run.py --config local_config.yaml --export-html exports\dashboard.html
```

You can also configure:

```yaml
pipeline:
  steps: [summarize, dashboard]
  dashboard_mode: export

dashboard:
  export:
    output_path: exports\dashboard.html
```

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

## Important Files

| File | Role |
|---|---|
| `dashboard/export/html.py` | Builds and writes the final HTML document. |
| `dashboard/export/payload.py` | Builds export payloads and selector variants. |
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
4. Rebuild `assets/export_runtime.js`.
5. Add/update fixture, contract, and smoke tests.
6. Bump `EXPORT_SCHEMA_VERSION` if older payloads are no longer safe.
7. Update this wiki chapter if user-visible behavior changed.

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

