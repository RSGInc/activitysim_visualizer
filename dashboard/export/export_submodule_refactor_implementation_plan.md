# Export Sub-Module Refactor Implementation Plan

## Purpose

This document outlines a practical implementation plan for refactoring the export sub-module so that it is safer to maintain, easier to test, and more approachable for Python-oriented developers who do not primarily work in JavaScript or web development.

The goal is **not** to turn the export system into a full frontend application. The goal is to make the JavaScript runtime feel like a small, predictable support library: explicit data structures, small pure functions, clear module boundaries, strong test coverage, and easy debugging.

---

## Current State Summary

The export system currently works by having Python generate an offline export payload, then embedding that payload into a standalone HTML document along with CSS, Plotly, and a JavaScript runtime.

At a high level:

1. Python walks the dashboard/page structure.
2. Python serializes supported objects into export nodes.
3. Python builds a JSON payload containing pages, selectors, states, variants, and diagnostics.
4. Python embeds that payload into an HTML shell.
5. The JavaScript runtime renders the payload into the browser DOM.
6. Runtime JavaScript manages navigation, selectors, region updates, and Plotly rendering/resizing.

This architecture is reasonable. The main issue is maintainability: too much browser behavior is concentrated in one large JavaScript file, and the Python/JavaScript contract is only loosely enforced.

---

## Refactor Objectives

The refactor should optimize for the following outcomes:

- Make the JavaScript understandable to Python developers.
- Reduce hidden mutable browser state.
- Replace large imperative functions with small named helpers.
- Add test coverage before making major behavior changes.
- Create a clear contract between Python-generated payloads and JavaScript-rendered output.
- Isolate necessary browser-specific or Plotly-specific workarounds.
- Make runtime failures easier to diagnose from the browser console.
- Keep the export format lightweight and dependency-minimal.

---

## Non-Goals

The following are intentionally out of scope for the first refactor pass:

- Rewriting the runtime in React, Vue, Svelte, or another frontend framework.
- Introducing a large frontend build system.
- Redesigning the export payload format from scratch.
- Changing user-facing export behavior.
- Replacing Plotly.
- Making the export runtime support arbitrary untrusted HTML.

---

## Proposed Target Structure

The current runtime should be split into smaller modules during development, then bundled or concatenated into the existing embedded runtime asset.

Suggested structure:

```text
export/
  assets/
    export.css
    export_runtime.js

  js_runtime/
    index.js
    state.js
    schema.js
    dom.js
    errors.js
    debug.js

    renderers/
      app.js
      nodes.js
      widgets.js
      tables.js
      tabs.js
      plots.js
      regions.js
      errors.js

    plotly_lifecycle.js

  tests/
    fixtures/
      minimal_payload.json
      grouped_pages_payload.json
      selector_region_payload.json
      plot_payload.json
      malformed_payload.json

    test_export_payload.py
    test_serializer.py
    test_runtime_assets.py
    test_runtime_contract.py
```

The final embedded artifact can still be `assets/export_runtime.js`. The source can be split for readability while preserving the existing runtime delivery model.

---

## Guiding Design Principles

### Prefer Boring Code

The runtime should use plain JavaScript with simple patterns:

- objects as dictionaries
- explicit function arguments
- small pure functions
- table-driven dispatch
- clear error messages
- minimal browser magic

Avoid clever JavaScript idioms that would feel unfamiliar to Python developers.

### Separate Pure Logic From Browser Logic

Functions that decide what to render should be separate from functions that manipulate the DOM.

For example, this is good:

```js
function stateKey(state) {
  return `${state.weighting}||${state.values}`;
}
```

This is harder to test:

```js
function updatePage() {
  const key = `${state.weighting}||${state.values}`;
  document.querySelector(...).innerHTML = ...
}
```

### Make State Explicit

Avoid functions that implicitly read or mutate closure-global state. Prefer passing a `context` object:

```js
function renderNode(node, context) {
  ...
}
```

Where `context` includes:

```js
{
  payload,
  state,
  actions,
  plotManager,
  logger
}
```

### Keep Browser Workarounds Isolated

If timeout-based Plotly resizing is necessary, keep it in one file with a clear name and comments explaining why it exists.

### Test the Contract, Not Just the Functions

The most important boundary is the Python-to-JavaScript payload contract. Tests should prove that Python-generated payloads are valid and renderable.

---

# Phase 1: Add Safety Net Before Refactoring

## Goal

Add tests and fixtures before making structural changes. This reduces the risk of breaking export behavior while cleaning up the runtime.

## Tasks

### 1. Add Payload Fixtures

Create small representative payload fixtures:

```text
tests/fixtures/minimal_payload.json
tests/fixtures/grouped_pages_payload.json
tests/fixtures/selector_region_payload.json
tests/fixtures/plot_payload.json
tests/fixtures/malformed_payload.json
```

Each fixture should be intentionally small and readable.

The minimal fixture should include:

- one page
- one card/container
- one trusted HTML node
- no selectors
- no Plotly dependency

The selector-region fixture should include:

- at least one selector
- at least two selector values
- a region node with variants
- a missing variant fallback case if supported

The plot fixture should include:

- one Plotly node
- a minimal Plotly figure
- enough layout data to exercise resizing behavior

### 2. Add Python Tests for Existing Behavior

Add unit tests for existing Python functions before changing implementation.

Recommended test targets:

- payload assembly
- payload sanitization
- selector value resolution
- region resolution
- variant key creation
- page export config validation
- runtime asset injection
- HTML shell construction

Example test cases:

```text
test_variant_key_is_stable
test_sanitize_export_payload_removes_nan
test_sanitize_export_payload_removes_infinity
test_selector_values_are_resolved_from_config
test_region_variants_are_built_for_selector_values
test_html_shell_embeds_schema_version
test_runtime_asset_replaces_schema_placeholder
```

### 3. Add Smoke Test for Generated HTML

Add a test that builds a small export and verifies that the output HTML contains:

- the payload script tag
- the runtime script
- the CSS
- the expected schema version
- the Plotly script or Plotly dependency hook
- no raw `NaN`
- no raw `Infinity`

### 4. Add Initial Runtime Contract Test

Add a test that validates known fixture payloads against the expected schema version and required top-level fields.

At minimum, assert the presence and basic shape of:

```text
schema_version
pages
initial_state
selectors
diagnostics
```

## Deliverables

- Fixture payloads committed to the test suite.
- Python unit tests covering existing export behavior.
- HTML smoke test.
- Initial runtime contract test.

## Acceptance Criteria

- Tests pass against the current implementation.
- Fixtures are small enough for developers to read.
- No runtime behavior is intentionally changed in this phase.

---

# Phase 2: Add Developer Documentation

## Goal

Document how the export system works before restructuring it.

## Tasks

Create or update:

```text
export/README.md
```

Suggested README sections:

```md
# Offline HTML Export

## Data Flow

1. Python builds an `ExportPayload`.
2. Python serializes dashboard objects into export nodes.
3. Python embeds the payload, CSS, Plotly, and runtime JS into an HTML shell.
4. The browser runtime renders the JSON tree.
5. Runtime JS manages page navigation, selectors, regions, and Plotly resizing.

## Important Files

- `payload.py`: builds pages, selectors, states, and region variants.
- `serializer.py`: converts supported Python/Panel objects into export nodes.
- `types.py`: defines payload and node shapes.
- `runtime_assets.py`: loads CSS and JS assets into the HTML shell.
- `assets/export_runtime.js`: browser runtime used by exported HTML.

## When Changing Payload Structure

1. Update Python payload types.
2. Update JavaScript schema validation.
3. Add or update fixture payloads.
4. Add contract tests.
5. Bump `EXPORT_SCHEMA_VERSION`.

## Debugging Exports

- Open the exported HTML in a browser.
- Open developer tools.
- Check console errors for `ExportRuntimeError`.
- Use debug mode if available.
```

## Deliverables

- `export/README.md`
- brief architecture explanation
- debugging guidance
- schema-change checklist

## Acceptance Criteria

- A Python developer can read the README and understand the data flow.
- The README explains where to add new node types.
- The README explains when to update schema version and fixtures.

---

# Phase 3: Split Runtime Into Small Source Modules

## Goal

Break the large JavaScript runtime into smaller source files while keeping the final embedded runtime behavior unchanged.

## Tasks

### 1. Create `js_runtime/`

Move source code into development modules:

```text
js_runtime/index.js
js_runtime/state.js
js_runtime/schema.js
js_runtime/dom.js
js_runtime/errors.js
js_runtime/debug.js
js_runtime/renderers/
js_runtime/plotly_lifecycle.js
```

### 2. Preserve Existing Embedded Runtime

Continue producing:

```text
assets/export_runtime.js
```

Options:

1. Use a simple Python build script that concatenates files in dependency order.
2. Use a minimal JavaScript bundler if the project already has Node tooling.
3. Avoid introducing a heavy frontend toolchain in the first pass.

Recommended first approach:

```text
python scripts/build_export_runtime.py
```

The script should:

- read files from `js_runtime/`
- concatenate in a known order
- inject a header comment
- write `assets/export_runtime.js`

### 3. Keep Behavior Identical

During this phase, avoid logic rewrites. Only move code into named files and functions.

## Deliverables

- split runtime source files
- build script for `assets/export_runtime.js`
- tests ensuring generated runtime asset exists and contains schema version placeholder/replacement

## Acceptance Criteria

- Exported HTML still works as before.
- Existing tests still pass.
- Generated `assets/export_runtime.js` is reproducible.
- Developers can edit small source files instead of one large runtime file.

---

# Phase 4: Extract Pure Runtime State Logic

## Goal

Move state calculation logic into pure, testable functions.

## Candidate Functions

Extract functions such as:

```js
function stateKey(state) { ... }

function findPageById(payload, pageId) { ... }

function hasChildren(page) { ... }

function resolveActiveChildPageId(page, state) { ... }

function currentLeafPageId(payload, state) { ... }

function getInitialState(payload) { ... }

function updateSelectorState(state, selectorId, value) { ... }
```

## Example Refactor

Before:

```js
function currentLeafPageId() {
  const page = findPageById(state.activePage);
  if (!page) return null;
  if (page.children && page.children.length) {
    return state.activeChildPage[page.id] || page.default_child_id || page.children[0].id;
  }
  return page.id;
}
```

After:

```js
function currentLeafPageId(payload, state) {
  const page = findPageById(payload, state.activePage);
  if (!page) return null;

  if (hasChildren(page)) {
    return (
      state.activeChildPage[page.id] ||
      page.default_child_id ||
      page.children[0].id
    );
  }

  return page.id;
}
```

## Tests

Add pure tests for:

```text
stateKey
findPageById
hasChildren
resolveActiveChildPageId
currentLeafPageId
updateSelectorState
```

These should not require a browser.

## Deliverables

- `state.js`
- unit tests for state functions
- reduced global state access in render code

## Acceptance Criteria

- State functions can be tested without DOM.
- State transitions are explicit.
- Render functions receive state through context instead of reading globals directly where practical.

---

# Phase 5: Introduce DOM Helper Utilities

## Goal

Reduce repetitive DOM manipulation code and make renderers easier to read.

## Tasks

Create:

```text
js_runtime/dom.js
```

Suggested helpers:

```js
function el(tag, options = {}, children = []) {
  const element = document.createElement(tag);

  if (options.className) {
    element.className = options.className;
  }

  if (options.text !== undefined && options.text !== null) {
    element.textContent = String(options.text);
  }

  if (options.attrs) {
    for (const [name, value] of Object.entries(options.attrs)) {
      if (value !== undefined && value !== null) {
        element.setAttribute(name, String(value));
      }
    }
  }

  for (const child of children) {
    if (child !== undefined && child !== null) {
      element.appendChild(child);
    }
  }

  return element;
}
```

Also consider:

```js
function clearChildren(element) { ... }

function appendChildren(parent, children) { ... }

function setClass(element, className, enabled) { ... }

function button(options) { ... }
```

## Example Refactor

Before:

```js
const title = document.createElement("h2");
title.className = "rail-section-title";
title.textContent = "Display Options";
shell.appendChild(title);
```

After:

```js
shell.appendChild(el("h2", {
  className: "rail-section-title",
  text: "Display Options",
}));
```

## Deliverables

- `dom.js`
- render code updated to use helpers where it improves readability

## Acceptance Criteria

- DOM code is shorter and easier to scan.
- Helper functions remain simple and obvious.
- No helper becomes a mini-framework.

---

# Phase 6: Replace Render Branching With Renderer Registry

## Goal

Replace long `if`/`else` or `switch` chains with a table-driven renderer registry.

## Proposed Pattern

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

function renderNode(node, context) {
  assertObject(node, "export node");

  const renderer = NODE_RENDERERS[node.kind];

  if (!renderer) {
    throw new ExportRuntimeError(
      `Unknown export node kind: ${node.kind}`,
      { node },
      "UNKNOWN_NODE_KIND"
    );
  }

  return renderer(node, context);
}
```

## Benefits

- Adding a new node type becomes obvious.
- Each renderer can be tested independently.
- The code resembles a Python dictionary of handlers.
- Error messages become more specific.

## Tasks

1. Create `renderers/nodes.js`.
2. Move each node renderer into a named function.
3. Register renderers in `NODE_RENDERERS`.
4. Add tests for unknown node kinds.
5. Add README instructions for adding node types.

## Deliverables

- renderer registry
- named renderer functions
- tests for known and unknown node kinds

## Acceptance Criteria

- No giant render dispatcher remains.
- Unknown node kinds produce clear typed errors.
- Adding a new node kind requires touching predictable files only.

---

# Phase 7: Isolate Plotly Lifecycle Handling

## Goal

Move Plotly-specific rendering, resize, and observer logic into one module.

## Current Pain Points

The existing runtime likely needs browser timing workarounds for Plotly, but those workarounds currently make the main runtime harder to understand.

Examples of behavior to isolate:

- delayed resize retries
- `ResizeObserver`
- pending plot rendering
- direct global `Plotly` access
- custom properties stored on DOM nodes

## Proposed API

Create:

```text
js_runtime/plotly_lifecycle.js
```

With an API like:

```js
function createPlotManager({ plotly, logger }) {
  const plotFigures = new WeakMap();

  return {
    registerPlot(element, figure) {
      plotFigures.set(element, figure);
    },

    renderPendingPlots(root) {
      ...
    },

    scheduleResize() {
      ...
    },

    observeLayout(root) {
      ...
    },

    disconnect() {
      ...
    },
  };
}
```

## Replace DOM Custom Properties

Instead of:

```js
div.__plotFigure = figure;
```

Use:

```js
const plotFigures = new WeakMap();
plotFigures.set(div, figure);
```

## Make Resize Retries Explicit

```js
const PLOT_RESIZE_RETRY_DELAYS_MS = [60, 180, 320];
```

Then the retry behavior is named, documented, and testable.

## Deliverables

- `plotly_lifecycle.js`
- plot manager object
- resize retry constants
- Plotly rendering isolated from general app rendering

## Acceptance Criteria

- Main app rendering does not contain Plotly timing details.
- Plotly unavailable errors are clear.
- Plot data is not stored as ad hoc properties on DOM nodes.
- Resize behavior remains functionally equivalent.

---

# Phase 8: Improve Runtime Error Handling and Debugging

## Goal

Make exported HTML easier to debug when something goes wrong.

## Add Typed Runtime Error

Create:

```js
class ExportRuntimeError extends Error {
  constructor(message, detail = null, code = "EXPORT_RUNTIME_ERROR") {
    super(message);
    this.name = "ExportRuntimeError";
    this.code = code;
    this.detail = detail;
  }
}
```

Potential error codes:

```text
PAYLOAD_PARSE_FAILED
SCHEMA_VERSION_UNSUPPORTED
MISSING_PAGE_STATE
UNKNOWN_NODE_KIND
PLOTLY_UNAVAILABLE
REGION_VARIANT_MISSING
INVALID_EXPORT_NODE
INVALID_SELECTOR_STATE
```

## Add Debug Logger

Create:

```js
function createLogger(enabled) {
  return {
    debug(...args) {
      if (enabled) console.debug("[export-runtime]", ...args);
    },

    warn(...args) {
      console.warn("[export-runtime]", ...args);
    },

    error(...args) {
      console.error("[export-runtime]", ...args);
    },
  };
}
```

Enable debug logging with one of:

```text
?debug_export=1
localStorage.setItem("debug_export", "1")
payload.debug = true
```

## Add Runtime Summary Log

When debug mode is enabled, log:

- schema version
- number of pages
- number of selectors
- number of states
- number of region nodes
- number of plot nodes

## Deliverables

- `errors.js`
- `debug.js`
- typed error codes
- optional debug mode

## Acceptance Criteria

- Browser console errors are specific and searchable.
- Debug logging can be enabled without modifying code.
- Runtime errors include enough context for Python developers to diagnose payload issues.

---

# Phase 9: Strengthen Python/JavaScript Schema Contract

## Goal

Make it harder for Python payload changes to silently break JavaScript rendering.

## Option A: JSON Schema

Add:

```text
export/schema/export_payload.schema.json
```

Then:

- validate Python-generated payload fixtures
- validate committed fixture files
- optionally validate payload before writing export HTML in debug/test mode

## Option B: Pydantic Models

Longer term, replace or supplement `TypedDict` definitions with Pydantic models.

Benefits:

- runtime validation
- clearer error messages
- generated JSON Schema
- easier documentation

Tradeoffs:

- additional dependency or version considerations
- more implementation effort
- migration from current `TypedDict` style

## Recommended Path

Start with manually maintained JSON Schema or lightweight validation around fixtures. Consider Pydantic later if export payload complexity continues to grow.

## Deliverables

- schema validation strategy
- schema contract tests
- fixture validation tests

## Acceptance Criteria

- Python payload changes require test updates.
- Fixture payloads validate against the expected schema.
- JS runtime validation matches the schema closely enough to catch common drift.

---

# Phase 10: Harden Python-Side Region Serialization

## Goal

Make selector-driven region serialization safer and easier to reason about.

## Risk

The Python export logic may temporarily mutate widget values to serialize all region variants. This is inherently risky because a failure midway can leave widgets in an unexpected state.

## Add Context Manager for Temporary Widget Values

```python
from contextlib import contextmanager

@contextmanager
def temporary_widget_values(selector_widgets, values_by_selector_id):
    original_values = {
        selector_id: widget.value
        for selector_id, widget in selector_widgets.items()
        if widget is not None
    }

    try:
        for selector_id, value in values_by_selector_id.items():
            widget = selector_widgets.get(selector_id)
            if widget is not None:
                widget.value = value
        yield
    finally:
        for selector_id, original_value in original_values.items():
            selector_widgets[selector_id].value = original_value
```

## Add Tests

Test that:

- original values are restored after successful serialization
- original values are restored after an exception
- missing selector widgets are handled gracefully
- unsupported selector values produce clear errors
- overlapping or nested regions produce clear validation errors

## Deliverables

- context manager for temporary widget mutation
- tests around success and failure cases
- clearer region serialization helpers

## Acceptance Criteria

- Widget state is always restored.
- Region serialization failures are easier to debug.
- Risky mutation logic is isolated and documented.

---

# Phase 11: Move Inline Styles Into CSS Where Practical

## Goal

Reduce styling logic in JavaScript and keep rendering code focused on structure.

## Example

Before:

```js
item.style.padding = "8px 10px";
item.style.borderLeft = "4px solid " + (run.color || "#94a3b8");
item.style.margin = "6px 0";
item.style.borderRadius = "6px";
item.style.background = "rgba(127,127,127,0.06)";
```

After:

```js
item.className = "run-legend-item";
item.style.setProperty("--run-color", run.color || "#94a3b8");
```

CSS:

```css
.run-legend-item {
  padding: 8px 10px;
  border-left: 4px solid var(--run-color, #94a3b8);
  margin: 6px 0;
  border-radius: 6px;
  background: rgba(127,127,127,0.06);
}
```

## Tasks

- Identify repeated inline styles.
- Move static styles to `export.css`.
- Use CSS custom properties only for truly dynamic values.
- Avoid moving behavior-specific layout into JavaScript.

## Deliverables

- cleaner runtime rendering code
- expanded CSS classes
- fewer inline style mutations

## Acceptance Criteria

- Visual output remains unchanged.
- JavaScript renderers are easier to read.
- Dynamic styles are clearly intentional.

---

# Phase 12: Address Trusted HTML Explicitly

## Goal

Make it clear that HTML nodes are trusted content generated by the Python export system.

## Current Concern

The runtime may render serialized HTML using:

```js
div.innerHTML = node.html || "";
```

This may be acceptable if the content is generated by trusted Python serializers, but it should be documented explicitly.

## Refactor

Rename the renderer function:

```js
function renderTrustedHtml(node, context) {
  const div = el("div", { className: "export-html-node" });
  div.innerHTML = node.html || "";
  return div;
}
```

Add a comment:

```js
// node.html is generated by the Python serializer from dashboard-owned content.
// Do not use this renderer for arbitrary untrusted user input.
```

## Optional Future Schema Change

In a future schema version, consider renaming the node kind:

```text
html -> trusted_html
```

Do not do this in the first pass unless a schema migration is already planned.

## Deliverables

- explicit trusted HTML renderer
- comments explaining trust boundary
- optional future schema migration note

## Acceptance Criteria

- Developers understand why `innerHTML` is used.
- The trust boundary is documented.
- No accidental implication that arbitrary user HTML is safe.

---

# Suggested Implementation Sequence

## 1: Add Safety Net and Documentation

Includes:

- fixture payloads
- Python unit tests for current behavior
- generated HTML smoke test
- initial `export/README.md`

This step should avoid major runtime changes.

## 2: Split Runtime Source Files

Includes:

- `js_runtime/` source directory
- build script for generated `assets/export_runtime.js`
- no intentional behavior changes

## 3: Extract State and Schema Helpers

Includes:

- `state.js`
- `schema.js`
- pure tests for state helpers
- clearer schema validation errors

## 4: Introduce DOM Helpers and Renderer Registry

Includes:

- `dom.js`
- `renderers/nodes.js`
- renderer registry
- unknown node kind errors

## 5: Isolate Plotly Lifecycle

Includes:

- `plotly_lifecycle.js`
- plot manager
- `WeakMap` for plot figure association
- documented resize retry behavior

## 6: Improve Debuggability

Includes:

- typed `ExportRuntimeError`
- debug logger
- runtime summary logging
- clearer console diagnostics

## 7: Harden Python Region Serialization

Includes:

- context manager for temporary widget values
- region serialization tests
- clearer validation errors

## 8: CSS Cleanup and Trusted HTML Documentation

Includes:

- move repeated inline styles to CSS
- document trusted HTML rendering
- optional notes for future schema rename

---

# Testing Strategy

## Python Tests

Focus on payload generation and serialization.

Recommended areas:

```text
payload construction
selector resolution
region variant generation
diagnostics
payload sanitization
HTML shell construction
runtime asset loading
schema version handling
```

## JavaScript Tests

Focus on pure functions first.

Recommended areas:

```text
state key generation
active page resolution
selector state updates
schema validation
node renderer dispatch
unknown node kind errors
region variant lookup
debug logger behavior
```

## Browser Smoke Tests

If feasible, add one lightweight browser smoke test using Playwright or a similar tool.

Test flow:

1. Generate minimal export HTML.
2. Open it in a headless browser.
3. Assert that no console errors occur.
4. Assert that expected page title/content is visible.
5. Change selector value.
6. Assert region content changes.
7. Assert Plotly node renders if included.

If browser automation is too much for the first pass, defer this until after pure tests are in place.

---

# Acceptance Criteria for Overall Refactor

The refactor should be considered successful when:

- A Python developer can understand the runtime structure from the README.
- JavaScript runtime source is split into small named modules.
- Core runtime logic is testable without a browser.
- Python-generated payloads are covered by fixtures and contract tests.
- Plotly-specific behavior is isolated.
- Runtime errors include clear codes and context.
- Region serialization restores widget state even after errors.
- Visual export output remains unchanged unless intentionally updated.
- Adding a new export node type has a documented path.

---

# Risks and Mitigations

## Risk: Refactor Changes Export Behavior

Mitigation:

- Add fixtures and smoke tests first.
- Keep behavior-preserving PRs separate from behavior-changing PRs.
- Compare generated HTML before and after major changes.

## Risk: JavaScript Tooling Becomes Too Heavy

Mitigation:

- Start with plain JavaScript.
- Use a simple Python build script if possible.
- Avoid framework adoption.
- Add Node tooling only if it clearly pays for itself.

## Risk: Payload Schema and Runtime Drift

Mitigation:

- Add fixture contract tests.
- Require schema updates when payload structure changes.
- Keep schema version bump checklist in README.

## Risk: Plotly Resizing Regressions

Mitigation:

- Isolate resize logic without changing timing at first.
- Add explicit retry constants.
- Add browser smoke test later.

## Risk: Widget Mutation During Export Leaves Bad State

Mitigation:

- Use a context manager.
- Add success and exception-path tests.
- Keep mutation code isolated.

