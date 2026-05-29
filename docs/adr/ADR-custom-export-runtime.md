# ADR: Custom Offline Export Runtime

- Status: Accepted
- Date: 2026-04-23

## Context

`activitysim_visualizer` uses Panel for the live dashboard, but it also supports a standalone offline HTML export used for review and sharing.

The project had to choose between two broad export strategies:

1. Keep a generic all-Panel export path.
2. Build a custom client-side export runtime that serializes only the dashboard state we want to ship offline.

## Decision

The project keeps the custom client-side export runtime.

The current implementation lives under `dashboard/export/` and produces:

- one self-contained HTML file
- one embedded JSON payload describing dashboard/page state
- one embedded browser runtime that validates and renders that payload

## Why Panel Is Still the Live Runtime

Panel remains a good fit for the live dashboard because it gives the project:

- fast composition of plots, tables, and controls
- server-backed interactivity for exploratory work
- straightforward integration with Python-side summary tables and cached state
- a productive page-controller model for contributors

The decision here is not "Panel was a mistake." The decision is specifically about offline export behavior.

## Why We Did Not Keep the Original All-Panel Export Path

The generic all-Panel export path was not the right long-term fit for this project’s offline needs.

Main reasons:

- The exported artifact was larger than necessary because it carried more live-app machinery than the offline use case needed.
- The project wanted tighter control over what state combinations were materialized offline.
- The offline use case only needs a bounded set of precomputed views, not a fully general live dashboard runtime.
- Debugging and reasoning about offline behavior is easier when the payload and renderer contract are explicit.

## Why the Custom Export Runtime Exists

The custom export path exists to optimize for the actual offline review workflow:

- one HTML file that can be handed around easily
- no server requirement
- bounded, explicit state growth driven by export config
- control over which selectors are interactive offline
- smaller artifacts than shipping the full live runtime
- clearer failure modes when export payload/runtime contracts drift

## Accepted Tradeoffs

This decision intentionally accepts some tradeoffs.

Costs:

- there is a Python-to-JavaScript schema contract to maintain
- new supported node kinds require work in both serializer and runtime
- export cannot automatically support every Panel component the live app might use
- contributors need docs and tests to keep the subsystem safe

Benefits:

- offline exports stay self-contained
- artifact size is more controllable
- page/selector support is explicit instead of accidental
- runtime failures can be made visible and diagnosable
- the export path is easier to harden with focused tests

## Guardrails We Rely On

To keep this decision healthy over time, the project relies on:

- typed payload definitions in `dashboard/export/types.py`
- explicit schema versioning
- a runtime compatibility check in `dashboard/export/assets/export_runtime.js`
- page-owned selector and section registration via the public `DashboardPage` API
- export contract tests for payload shape, serializer coverage, smoke behavior, warnings, and artifact size
- contributor docs that explain how to extend the subsystem safely

## Consequences for Future Work

Future contributors should assume:

- the custom export runtime is the supported direction
- replacing it with generic live-app export would need a new ADR
- page and selector export support should be added through the shared page registry and docs, not through ad hoc export-only configuration

If the team later decides the maintenance cost is too high, that should be revisited explicitly with fresh evidence about artifact size, complexity, and offline user needs.
