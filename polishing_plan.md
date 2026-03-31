# Panel Visualizer Polishing Plan

## Scope

This plan applies only to the Panel visualizer code in `dashboard/` and the supporting summary code in `summarize/`.

Out of scope:
- `marimo_visualizer/`
- `quarto/`
- `quarto_visualizer/`

## Desired Behavior

The Panel app should behave as follows:

- `Weighted` / `Unweighted` is a global display mode.
- `Count` / `Percent` is a global display mode.
- Global display mode changes should not force the user back to `Overview` or to a random tab.
- Global display mode changes should apply lazily, meaning only the currently viewed tab should refresh immediately.
- Tab-specific selectors should persist when the user switches tabs and returns later.
- Reapplying the same tab filters and global display modes should reuse cached results instead of recomputing the same summaries repeatedly.

## Current Problems Observed In The Code

### 1. Global mode changes replace the entire tabs object

In `dashboard/app.py`, the live app currently binds `weight_mode` and `value_mode` to `_get_tabs(...)`, which returns a different cached `pn.Tabs` object for each `(weighted/unweighted, percent/count)` combination.

That design likely causes the tab-jump behavior because:
- the active tab index belongs to the `pn.Tabs` instance being replaced
- each cached tab set contains a different tree of page objects and widget instances
- returning to a previous tabs object can also restore an older tab index, which can feel random

### 2. Tab-local selectors are recreated when page objects are recreated

Most page modules create `pn.widgets.Select` instances inside `build(...)`:
- `dashboard/pages/tour_summary.py`
- `dashboard/pages/joint_tours.py`
- `dashboard/pages/long_term.py`
- `dashboard/pages/destination.py`
- `dashboard/pages/tour_tod.py`
- `dashboard/pages/tour_mode.py`
- `dashboard/pages/stop_freq.py`
- `dashboard/pages/stop_timing.py`
- `dashboard/pages/trip_mode.py`

Those selectors can only persist if the page object itself persists. Rebuilding the page tree for global mode changes resets the widget state.

### 3. Page computations are only partially cached

Several pages already precompute summary tables once per `build(...)` call, which is a good start. But because the app currently swaps whole tab sets, those computations can still be repeated across mode combinations. There is also no shared cache contract for:
- weighted vs unweighted run variants
- page summary tables
- filtered views derived from the same summary table

## Implementation Strategy

## Phase 1: Move global state ownership to a single long-lived app controller

Create a small Panel-specific state/controller layer that owns:
- the two global display modes
- the active tab index
- the per-tab local filter state
- shared caches

Suggested file:
- `dashboard/state.py`

Suggested responsibilities:
- store `weight_mode` and `value_mode` as the single source of truth
- store `active_tab` so it survives any reactive updates
- expose cache dictionaries keyed by stable tuples
- expose helper methods like `get_runs(weighted: bool)` and `get_page_state(page_name: str)`

This controller does not need to be complex. A lightweight `param.Parameterized` class would fit well because Panel reacts cleanly to Param state.

## Phase 2: Stop replacing `pn.Tabs` on global mode changes

Refactor `dashboard/app.py` so the app builds one long-lived `pn.Tabs` instance for the live session instead of four alternate tab trees.

Target behavior:
- build the tab shell once
- keep one stable `pn.Tabs`
- keep one stable page object per tab
- bind global controls to shared state, not to a function that returns a new tabs widget

Implementation direction:
- remove the current `tabs_cache[(use_weights, as_percent)] -> pn.Tabs` pattern for the live app
- keep `weight_mode` and `value_mode` widgets in the sidebar, but wire them to the shared controller
- preserve the current active tab index when global modes change
- continue to support `static_export`, but keep that path separate from the live-state path

This change should address the "sent back to Overview" and "random tab" behavior first, before tackling finer-grained caching.

## Phase 3: Convert each tab into a persistent page object

Instead of page modules returning a fully self-contained reactive layout built from local variables only, introduce persistent page objects with:
- one-time widget creation
- one-time summary cache creation
- reactive render methods that read shared global state

Suggested pattern:
- each page module exposes a `Page` class or `build_page(controller, runs, config)` factory
- widget instances live on the page object
- render methods consume:
  - local selector state from that page
  - global `weighted/unweighted`
  - global `count/percent`

This preserves selectors when users move across tabs because the widgets themselves are no longer recreated.

Good candidates for immediate conversion:
- `tour_summary`
- `long_term`
- `joint_tours`
- `destination`
- `tour_tod`
- `tour_mode`
- `stop_freq`
- `stop_timing`
- `trip_mode`

Tabs like `overview` and `stop_location` are simpler, but they should still be wrapped in the same persistent-page interface so the app architecture is consistent.

## Phase 4: Separate raw summaries from display transforms

The current code already uses `finalweight`, which is helpful. The next step is to make summary generation and display transformation clearly separate.

Recommended rule:
- summary functions in `summarize/` produce count-like weighted aggregates using the current `RunData`
- percent conversion happens in the display layer for the active page/chart only
- weighted vs unweighted changes switch the underlying run source, but percent/count never requires recomputing a raw summary if the raw grouped counts are already cached

Why this matters:
- `Count` and `Percent` should usually share the same grouped result
- only the plotted values differ
- this makes the `Percent` toggle cheap and naturally lazy

## Phase 5: Add explicit caching layers

Use caching at three levels.

### A. Run-level cache

In `dashboard/app.py` or the new controller:
- cache weighted runs
- cache unweighted runs

The current `_strip_weights(...)` logic can stay, but the result should be created once and then reused.

Cache key:
- `("weighted")`
- `("unweighted")`

### B. Page-summary cache

Each page should cache the heavy summary tables it derives from each run.

Examples:
- `tour_summary`: cache `dap_summary`, `mandatory_tour_freq`, `indiv_nm_summary`
- `tour_tod`: cache `tod_profiles`
- `trip_mode`: cache `trip_mode_profile`
- `stop_freq`: cache `stop_freq` and `stop_purpose_by_tour_purpose`

Cache key shape:
- `(page_name, weighting_mode, run_label, summary_name)`

This avoids recomputing the same grouped tables every time the user revisits a tab.

### C. Filtered-view cache

Each page can also cache filtered subsets or reshaped chart inputs derived from its summary tables.

Examples:
- `(tour_summary, weighted, ptype="Worker")`
- `(trip_mode, weighted, purpose="work", tour_mode="Drive Alone")`
- `(long_term, weighted, geography="Total")`

Cache key shape:
- `(page_name, weighting_mode, local_filter_1, local_filter_2, ...)`

This second-stage cache should only store inexpensive derived tables or chart-ready data, not giant duplicate raw inputs.

## Phase 6: Make global updates lazy by only refreshing the active tab immediately

The goal is not to rebuild every tab whenever the user changes `Weighted` or `Percent`.

Recommended behavior:
- all tabs retain their own selector state at all times
- when the global mode changes, only the active tab is re-rendered immediately
- inactive tabs are marked stale for the new global mode
- when the user opens an inactive tab later, that tab renders once using the new global mode and then caches the result

Implementation options:

Option A:
- keep one page object per tab
- track a small "last rendered global state" tuple per page
- on tab activation, compare that tuple to the controller state and refresh only if needed

Option B:
- use Panel reactive bindings inside each page, but gate expensive work behind page-level cached getters and an "is active tab" check

Option A is likely easier to reason about and easier to debug.

## Phase 7: Persist local selectors independently of global modes

Each page object should own its own selector values, and those values should not be reset when:
- the active tab changes
- the global weighting mode changes
- the global count/percent mode changes

Suggested approach:
- keep the actual widget instances alive for the duration of the session
- optionally mirror widget values into a page-state dict in the controller for extra safety and easier debugging
- never rebuild widgets just to apply global mode changes

Expected result:
- a user can choose filters on `Trip Mode`
- move to `Tour TOD`
- return to `Trip Mode`
- see the same purpose and tour-mode selections still in place

## Phase 8: Normalize page interfaces

To keep the code maintainable, every page should follow the same interface.

Suggested contract:
- `page.name`
- `page.view`
- `page.refresh_if_needed(global_state)`
- `page.get_summary(...)`
- `page.get_filtered_view(...)`

With a shared base class in something like `dashboard/page_base.py`, common behavior can live in one place:
- local cache dict
- stale/dirty handling
- page activation hook
- helpers for cache-key construction

This will reduce one-off reactive patterns across page modules and make later bug fixes much easier.

## Proposed Order Of Work

1. Refactor `dashboard/app.py` to keep one stable live `pn.Tabs` instance and one shared controller.
2. Introduce a persistent page abstraction and convert one representative tab first, preferably `trip_mode` or `tour_summary`.
3. Verify that tab switching no longer resets local selectors on the converted page.
4. Add lazy refresh behavior tied to the active tab.
5. Roll the page-object pattern across the rest of the interactive tabs.
6. Add page-summary and filtered-view caches page by page.
7. Clean up any remaining direct use of module-level display globals like `_DISPLAY_PERCENT_MODE` if they become a source of hidden state.

## Specific Refactors To Make

### `dashboard/app.py`

- Replace `pn.bind(_get_tabs, weight_mode, value_mode)` with a single persistent app layout.
- Preserve and explicitly manage active tab state.
- Create and pass a shared controller into each page.
- Keep static export logic isolated from the live app path.

### `dashboard/components.py`

- Reduce reliance on module-global `_DISPLAY_PERCENT_MODE` if possible.
- Prefer passing display mode explicitly from the controller or page render method.
- Keep chart helpers pure where possible so cached inputs produce deterministic outputs.

### `dashboard/pages/*.py`

- Convert `build(...)` modules with selectors into persistent page objects.
- Cache summary tables once per weighting mode.
- Cache filtered chart inputs by local selector values.
- Re-render only when the page becomes active and its relevant state changed.

### `summarize/*.py`

- Keep summary functions pure and deterministic.
- Do not mix UI state logic into summary functions.
- If a summary is expensive and reused on the same page, cache its result at the page layer first before considering broader memoization.

## Validation Checklist

The implementation should be considered complete when all of the following are true:

- Changing `Weighted` to `Unweighted` while on any tab keeps the user on that same tab.
- Changing `Count` to `Percent` while on any tab keeps the user on that same tab.
- Switching away from a tab and back preserves that tab's selectors.
- Global mode changes do not reset tab-local selectors.
- Returning to a previously visited selector combination reuses cached results.
- Inactive tabs do not eagerly recompute when a global mode changes.
- Visiting an inactive tab after a global mode change refreshes that tab exactly once for the new state.
- Static export behavior still works as a separate, simpler path.

## Testing Recommendations

### Manual interaction checks

- Open the app on `Trip Mode`, choose a purpose and a tour mode, switch tabs, then return.
- Repeat the same check on `Tour Summary`, `Long-Term`, `Destination`, and `Stop Frequency`.
- While on a non-Overview tab, toggle `Weighted/Unweighted` several times and confirm the active tab never changes.
- While on a non-Overview tab, toggle `Count/Percent` several times and confirm the active tab never changes.
- Change global modes, move to a tab that has not yet been visited in that mode, and confirm it updates correctly on first activation.

### Instrumentation checks

Add lightweight logging or counters during development to confirm:
- which page refreshed
- whether the refresh came from cache
- whether a summary function actually reran

This will make it much easier to verify that lazy application and caching are both working as intended.

## Risks To Watch

- Panel reactive bindings can accidentally trigger more recomputation than expected if multiple watchers observe the same widgets.
- Hidden module-level state such as `_DISPLAY_PERCENT_MODE` can make refresh behavior harder to reason about if some pages read it implicitly.
- If cache keys are not explicit enough, weighted and unweighted results can be mixed accidentally.
- If cache keys are too broad, memory usage can grow unnecessarily.

## Recommended End State

The Panel visualizer should end up with:
- one stable app shell
- one stable page instance per tab
- one shared source of truth for global display modes
- independent local selector state per page
- summary caches keyed by weighting mode
- filtered-view caches keyed by tab selectors
- lazy tab refresh based on active-tab changes instead of whole-dashboard rebuilds

That architecture should directly solve the tab-jump and filter-reset issues while also making the app faster and much easier to maintain.
