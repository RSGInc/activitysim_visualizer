# JavaScript Runtime Guide for Python Developers

This guide explains how `dashboard/export/js_runtime/` works in plain English.

The short version:

- Python builds a JSON payload.
- The exported HTML embeds that payload plus CSS, Plotly, and one generated JavaScript file.
- The browser runtime reads the payload and turns it into DOM elements.
- When a user clicks a tab or selector, the runtime updates in-memory state and re-renders part or all of the page.

This is intentionally a small support library, not a frontend app framework.

## The Mental Model

If you mostly think in Python, it helps to map the runtime to a few familiar ideas:

- `payload`
  A plain data structure, like a nested `dict` loaded from JSON.
- `state`
  The current user selection state, similar to a mutable Python object that tracks active page, active child page, and selector values.
- `context`
  A small dependency container. It holds the current `payload`, current `state`, the DOM root, the Plotly manager, and a small registry of rendered regions.
- `actions`
  Named state transition functions. Instead of random code mutating globals, the runtime now has explicit entrypoints like `setWeighting(...)` and `setPageSelector(...)`.
- `renderers`
  Functions that convert payload nodes into DOM nodes.

If you want one sentence for the whole runtime, it is this:

> Parse payload, validate it, create a runtime context, render a page tree, and re-render when state changes.

## Start Here: Bootstrap

The entrypoint is [`js_runtime/index.js`](js_runtime/index.js).

Helpful landmarks in the current file:

- `createRuntimeContext(...)` at `index.js:8`
- `createRuntimeActions(...)` at `index.js:19`
- payload parsing and validation at `index.js:66`
- first render at `index.js:100`

The bootstrap flow is:

```js
payload = parsePayload();
validatePayloadSchema(payload);

const runtimeContext = createRuntimeContext({
  payload: payload,
  state: getInitialState(payload),
  logger: logger,
  plotManager: plotManager,
  app: app,
});

const runtimeActions = createRuntimeActions(runtimeContext);
renderApp(runtimeContext, runtimeActions);
```

Why this matters:

- Almost all important runtime data is created in one place.
- The rest of the code receives `context` and `actions` explicitly.
- That makes the JS read more like ordinary Python code that passes objects into functions.

## What Is in `context`?

`context` is the runtime's shared object. It lives in [`js_runtime/index.js`](js_runtime/index.js) and currently contains:

```js
{
  payload,
  state,
  logger,
  plotManager,
  app,
  renderedRegions,
}
```

In Python terms, this is basically a small object that bundles everything most renderer functions need.

The important fields are:

- `context.payload`
  The export JSON from Python.
- `context.state`
  The current browser-side selection state.
- `context.app`
  The root DOM element where everything gets rendered.
- `context.plotManager`
  The helper object that knows how to render and resize Plotly charts.
- `context.renderedRegions`
  A registry of region wrapper elements so selector-driven region updates do not need to search the whole DOM again.

## What Is in `state`?

The state helpers live in [`js_runtime/state.js`](js_runtime/state.js).

Good places to start:

- `buildDashboardStateKey(...)` at `state.js:9`
- `getLeafPageId(...)` at `state.js:55`
- `normalizeState(...)` at `state.js:100`
- `getInitialState(...)` at `state.js:123`
- `updateSelectorState(...)` at `state.js:163`

The state object looks like this:

```js
{
  weighting: "Weighted",
  values: "Percent",
  activePage: "trip_summaries",
  activeChildPage: {
    trip_summaries: "trip_mode",
  },
  pageSelectors: {
    trip_mode: {
      tour_purpose: "All",
    },
  },
}
```

### Why `normalizeState(...)` exists

One subtle improvement in the refactor is that "defaulting" now happens in one explicit place.

`normalizeState(...)` in [`state.js`](js_runtime/state.js) is responsible for things like:

- choosing the first page if `activePage` is missing
- resolving the active child page for grouped pages
- keeping read helpers like `getLeafPageId(...)` side-effect free

That is much easier to reason about than older code where a function that sounded like a getter also mutated global state.

## Actions: How User Events Change State

The runtime actions also live in [`js_runtime/index.js`](js_runtime/index.js), starting at `index.js:19`.

Current actions:

- `setWeighting(value)`
- `setValues(value)`
- `setActivePage(pageId)`
- `setActiveChildPage(pageId, childPageId)`
- `setPageSelector(selectorId, value, options)`

These are the browser-side equivalent of a small reducer or a group of clearly named controller methods.

For example:

```js
setActivePage: function (pageId) {
  context.state = setActivePageInState(context.payload, context.state, pageId);
  renderApp(context, runtimeActions);
}
```

That pattern is important:

1. Compute a new state.
2. Store it on `context.state`.
3. Re-render.

For selectors, there is one extra optimization:

```js
if (
  options
  && options.preferPartialRegionUpdate
  && updateRenderedRegions(context, runtimeActions, leafPageId, selectorId)
) {
  return;
}
renderApp(context, runtimeActions);
```

In plain English:

- If only a selector-driven region needs to change, try to update just that region.
- If that is not possible, do a full render of the page shell.

## Rendering: How JSON Becomes HTML

The top-level shell renderer is [`js_runtime/renderers/app.js`](js_runtime/renderers/app.js).

Helpful landmarks:

- `renderControls(...)` at `app.js:40`
- `renderRail(...)` at `app.js:151`
- `renderPageTabs(...)` at `app.js:160`
- `resolveActivePageNode(...)` at `app.js:205`
- `renderPagePanel(...)` at `app.js:239`
- `renderShell(...)` at `app.js:255`
- `renderApp(...)` at `app.js:282`

The important idea is that the runtime renders from the outside in:

1. Build the export shell.
2. Build the rail and page tabs.
3. Resolve the current leaf page.
4. Render that page's content tree.

At the top level, `renderApp(...)` does roughly this:

```js
context.state = normalizeState(context.payload, context.state);
clearRenderedRegionRegistry(context);
clearElement(context.app);
context.app.appendChild(renderShell(context, actions));
context.plotManager.renderPendingPlots(context.app);
context.plotManager.observeLayout(context.app);
context.plotManager.scheduleResize();
```

That is a good "main loop" to keep in your head.

## Node Renderers

The node dispatcher lives in [`js_runtime/renderers/nodes.js`](js_runtime/renderers/nodes.js).

This file answers the question:

> Given one payload node, which renderer should build the DOM for it?

The registry looks like this:

```js
const NODE_RENDERERS = {
  container: renderContainer,
  card: renderCard,
  html: renderTrustedHtml,
  plotly: renderPlot,
  table: renderTable,
  widget: renderWidget,
  tabs: renderTabs,
  spacer: renderSpacer,
  region: renderRegion,
};
```

This is intentionally similar to a Python dictionary that maps `"kind"` to a handler function.

If you add a new node kind, this is one of the first places you will touch.

## Regions: The Most Important Runtime Trick

If there is one part of the runtime worth understanding deeply, it is regions.

Regions are explained in [`js_runtime/renderers/regions.js`](js_runtime/renderers/regions.js).

Helpful landmarks:

- `buildRenderedRegionKey(...)` at `regions.js:9`
- `buildRegionVariantKey(...)` at `regions.js:37`
- `resolveRegionContent(...)` at `regions.js:48`
- `renderRegion(...)` at `regions.js:60`
- `updateRenderedRegions(...)` at `regions.js:97`

### What a region is

A region is a place in the page where Python precomputed multiple possible content variants.

For example, a page might contain a selector like `tour_purpose`, and one region might have:

- content for `"All"`
- content for `"eatout"`
- default content if no exact variant is found

The runtime does not re-run Python. It only swaps between already-serialized variants.

### How the variant lookup works

The key contract is:

- Python serializes variant keys in selector order.
- JavaScript must build the same key in the same order.

That is why the runtime uses:

```js
function buildRegionVariantKey(selectorValues) {
  return JSON.stringify(selectorValues);
}
```

And why `resolveRegionContent(...)` first gathers values in `node.selector_ids` order.

If Python builds a key like:

```json
["All", "Outbound"]
```

then JS must build exactly the same array in the same order before calling `JSON.stringify(...)`.

### Why `renderedRegions` exists

During a full render, each region wrapper is registered in `context.renderedRegions`.

That lets `updateRenderedRegions(...)` do a focused update later:

```js
const wrapper = context.renderedRegions[
  buildRenderedRegionKey(leafPageId, regionNode.region_id)
];
```

So instead of searching the DOM by selector every time:

- the runtime already knows where the region wrapper lives
- it clears that wrapper
- it renders just the new region content
- it lets Plotly re-render inside that region if needed

This is the main reason selector updates can be cheaper than full-page rerenders.

## Plotly: Why There Is a Separate Lifecycle Module

Plot rendering is isolated in [`js_runtime/plotly_lifecycle.js`](js_runtime/plotly_lifecycle.js).

Helpful landmarks:

- `PLOT_RESIZE_RETRY_DELAYS_MS` at `plotly_lifecycle.js:9`
- `createPlotManager(...)` at `plotly_lifecycle.js:12`
- `scheduleResize(...)` at `plotly_lifecycle.js:74`
- `registerPlot(...)` at `plotly_lifecycle.js:103`
- `renderPendingPlots(...)` at `plotly_lifecycle.js:111`

The runtime does not call `Plotly.react(...)` directly from every renderer. Instead:

1. `renderPlot(...)` builds a placeholder `div`.
2. It registers the serialized figure with `plotManager`.
3. After the DOM is painted, `plotManager.renderPendingPlots(...)` finds those placeholders and calls Plotly.

That separation matters because Plotly is sensitive to layout timing.

The resize logic exists because plots often need a second or third resize after the browser layout settles. The current implementation intentionally names those retries:

```js
const PLOT_RESIZE_RETRY_DELAYS_MS = [60, 180, 320];
```

So if you ever see a chart sizing bug, this file is the first place to inspect.

## Validation: Where the Runtime Rejects Bad Payloads

Payload validation lives in [`js_runtime/schema.js`](js_runtime/schema.js).

This file checks more than just "is there JSON?" It also validates cross-field consistency, including:

- schema version
- top-level payload fields
- duplicate page IDs
- invalid grouped-page `default_page_id`
- selector defaults not present in selector options
- missing leaf-page state entries
- duplicate region IDs within a leaf page
- regions that reference selectors the page does not define

That means many payload mistakes now fail early with a clear runtime error instead of producing a half-rendered export.

## DOM Helpers: Intentionally Small

The DOM helpers live in [`js_runtime/dom.js`](js_runtime/dom.js).

These are meant to be boring:

- `el(...)`
- `appendChildren(...)`
- `clearElement(...)`
- `makeButton(...)`

The runtime deliberately does not have a mini UI framework. If a helper starts hiding too much behavior, it becomes harder to read the code.

One small example:

```js
makeButton({
  label: page.title,
  active: page.id === context.state.activePage,
  onClick: () => {
    actions.setActivePage(page.id);
  },
  className: "page-tab-button",
});
```

That should feel close to constructing a small config object in Python and passing it to a helper.

## Errors and Debugging

Two files help when something goes wrong:

- [`js_runtime/errors.js`](js_runtime/errors.js)
- [`js_runtime/debug.js`](js_runtime/debug.js)

Useful debugging steps:

1. Open the exported HTML in a browser.
2. Open DevTools.
3. Look for `ExportRuntimeError` output in the console.
4. If needed, enable debug logging with:
   - `?debug_export=1`
   - `localStorage.setItem("debug_export", "1")`
   - `payload.debug = true` before export generation

The debug logger can print a summary of the payload, including page counts, selector counts, region counts, and plot counts.

## A Good Reading Order

If you want to learn the runtime without getting overwhelmed, read files in this order:

1. [`README.md`](README.md)
2. [`js_runtime/index.js`](js_runtime/index.js)
3. [`js_runtime/state.js`](js_runtime/state.js)
4. [`js_runtime/renderers/app.js`](js_runtime/renderers/app.js)
5. [`js_runtime/renderers/nodes.js`](js_runtime/renderers/nodes.js)
6. [`js_runtime/renderers/regions.js`](js_runtime/renderers/regions.js)
7. [`js_runtime/plotly_lifecycle.js`](js_runtime/plotly_lifecycle.js)
8. [`js_runtime/schema.js`](js_runtime/schema.js)

That order follows the runtime's actual execution path pretty well.

## When You Change the Runtime

If you edit the source files under `js_runtime/`, remember to rebuild the generated asset:

```powershell
.\.venv\Scripts\python.exe scripts/build_export_runtime.py
```

Then run the export runtime tests:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp .pytest_tmp `
  tests\test_export_runtime_build.py `
  tests\test_export_runtime_contract.py `
  tests\test_export_html_smoke.py
```

## Common Questions

### Why does the runtime sometimes fully re-render instead of updating one tiny thing?

Because full rerenders are simpler and safer. The runtime only uses partial updates in the narrow case where a selector change can safely swap already-known region content.

### Why does the runtime store Plotly figures separately from the DOM?

Because the DOM node is only the placeholder. The figure data belongs to the Plotly lifecycle manager, which decides when it is safe to call `Plotly.react(...)`.

### Why do region keys use JSON strings instead of something custom?

Because Python already serializes selector combinations in a JSON-compatible way, and `JSON.stringify(...)` gives JS a simple, deterministic way to match that representation.
