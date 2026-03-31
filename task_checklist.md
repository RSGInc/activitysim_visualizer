# Panel Visualizer Task Checklist

This checklist breaks the `Implementation Strategy` phases from [polishing_plan.md](c:/Users/wesley.darling/projects/activitysim_visualizer/polishing_plan.md) into concrete tasks for the Panel visualizer only.

## Phase 1: Move global state ownership to a single long-lived app controller

- [x] Create a new `dashboard/state.py` module for shared live-session state.
- [x] Define a controller class to hold `weight_mode`, `value_mode`, and `active_tab`.
- [x] Add controller storage for per-page local state keyed by page name.
- [x] Add controller storage for shared caches keyed by stable tuples.
- [x] Add a helper for retrieving weighted runs from the original run list.
- [x] Add a helper for retrieving unweighted runs from a cached unweighted run list.
- [x] Add helper methods for getting and updating page state without pages reaching into each other directly.
- [x] Decide whether the controller should use `param.Parameterized` and wire it accordingly.
- [x] Keep the controller API small and explicit so page modules can depend on it predictably.

## Phase 2: Stop replacing `pn.Tabs` on global mode changes

- [x] Refactor `dashboard/app.py` so the live app creates one `pn.Tabs` instance per session.
- [x] Remove the live `tabs_cache[(use_weights, as_percent)] -> pn.Tabs` pattern.
- [x] Replace the `pn.bind(_get_tabs, weight_mode, value_mode)` approach with controller-driven updates.
- [x] Keep the existing sidebar widgets for weighting and value mode, but bind them to controller state.
- [x] Add explicit handling to preserve the active tab index whenever global controls change.
- [x] Ensure the `Overview` tab is not reselected automatically during a global mode update.
- [x] Ensure tab order and tab names remain unchanged after the refactor.
- [x] Keep `static_export` on a separate path so the live-state refactor does not complicate export behavior.
- [x] Smoke test the app shell after this refactor before converting page internals.

## Phase 3: Convert each tab into a persistent page object

- [x] Create a persistent page pattern, either a `Page` class or a `build_page(controller, runs, config)` factory contract.
- [x] Update one representative interactive tab first, preferably `dashboard/pages/trip_mode.py` or `dashboard/pages/tour_summary.py`.
- [x] Move widget creation out of transient inner logic and onto the page object.
- [x] Keep each page's widget instances alive for the lifetime of the session.
- [x] Move one-time summary preparation onto the page object so it is not rebuilt on every global toggle.
- [x] Add a page-level render method that reads both local selector values and global controller state.
- [x] Convert `tour_summary` to the new page pattern.
- [x] Convert `long_term` to the new page pattern.
- [x] Convert `joint_tours` to the new page pattern.
- [x] Convert `destination` to the new page pattern.
- [x] Convert `tour_tod` to the new page pattern.
- [x] Convert `tour_mode` to the new page pattern.
- [x] Convert `stop_freq` to the new page pattern.
- [x] Convert `stop_timing` to the new page pattern.
- [x] Convert `trip_mode` to the new page pattern.
- [x] Wrap simpler tabs like `overview` and `stop_location` in the same interface for consistency.

## Phase 4: Separate raw summaries from display transforms

- [x] Audit page modules to identify where raw grouped results and display formatting are currently mixed together.
- [x] Keep `summarize/` functions responsible only for raw weighted/unweighted aggregates.
- [x] Move percent conversion logic out of summary-generation paths and into page/chart display logic.
- [x] Ensure the `Count` and `Percent` modes can share the same cached grouped data whenever possible.
- [x] Review `dashboard/components.py` helpers and identify which ones currently depend on implicit global percent mode.
- [x] Refactor chart calls so display mode is passed explicitly or cleanly derived from controller state.
- [x] Verify that switching `Count` to `Percent` does not force recomputation of raw grouped summaries.

## Phase 5: Add explicit caching layers

### Run-level cache

- [x] Cache the original weighted runs once for the session.
- [x] Cache the unweighted run variants once for the session using `_strip_weights(...)` or its replacement.
- [x] Make sure weighted and unweighted run caches cannot be mixed accidentally.

### Page-summary cache

- [x] Add a page-summary cache API to the controller or shared base page class.
- [x] Define a stable cache-key format such as `(page_name, weighting_mode, run_label, summary_name)`.
- [x] Cache `tour_summary` summaries per weighting mode.
- [x] Cache `tour_tod` summaries per weighting mode.
- [x] Cache `trip_mode` summaries per weighting mode.
- [x] Cache `stop_freq` summaries per weighting mode.
- [x] Cache the other page-level heavy summaries using the same pattern.

### Filtered-view cache

- [x] Add a filtered-view cache API for chart-ready data derived from page summaries.
- [x] Define a stable cache-key format such as `(page_name, weighting_mode, local_filters...)`.
- [x] Cache filtered `trip_mode` chart inputs by purpose and tour mode.
- [x] Cache filtered `tour_summary` chart inputs by person type.
- [x] Cache filtered `long_term` chart inputs by geography selection.
- [x] Cache filtered `destination`, `tour_tod`, `stop_freq`, and `stop_timing` views by their local selectors.
- [x] Add lightweight instrumentation so it is obvious when a result came from cache versus recomputation.

## Phase 6: Make global updates lazy by only refreshing the active tab immediately

- [ ] Add page-level tracking for the last rendered global state.
- [ ] Mark inactive pages as stale when `weight_mode` changes.
- [ ] Mark inactive pages as stale when `value_mode` changes.
- [ ] Refresh only the active page immediately after a global mode change.
- [ ] Add a tab-activation hook so a stale page refreshes the next time the user opens it.
- [ ] Ensure a page refreshed because of a stale global state only updates once per new state combination.
- [ ] Verify that inactive tabs do not eagerly recompute during repeated global toggles.
- [ ] Add temporary debug logging or counters to confirm which tab refreshed and when.

## Phase 7: Persist local selectors independently of global modes

- [ ] Make each page own its selector widgets and selector values.
- [ ] Ensure page selectors are not recreated during global mode changes.
- [ ] Ensure page selectors are not recreated during tab switches.
- [ ] Mirror selector values into controller page state if that helps debugging or recovery.
- [ ] Add restoration logic only if necessary; prefer retaining the original widget instances instead.
- [ ] Test `Trip Mode` selector persistence across tab switches.
- [ ] Test `Tour Summary` selector persistence across tab switches.
- [ ] Test `Long-Term` selector persistence across tab switches.
- [ ] Test `Destination` selector persistence across tab switches.
- [ ] Test `Stop Frequency` selector persistence across tab switches.
- [ ] Verify that local selector values survive both `Weighted/Unweighted` and `Count/Percent` toggles.

## Phase 8: Normalize page interfaces

- [ ] Create a shared base page abstraction in a file such as `dashboard/page_base.py`.
- [ ] Standardize page properties like `name` and `view`.
- [ ] Standardize a refresh hook such as `refresh_if_needed(global_state)`.
- [ ] Standardize summary cache access through a method like `get_summary(...)`.
- [ ] Standardize filtered-view cache access through a method like `get_filtered_view(...)`.
- [ ] Move common cache-key helpers into the shared base page abstraction.
- [ ] Move common stale/dirty tracking into the shared base page abstraction.
- [ ] Update all page modules to use the normalized interface.
- [ ] Remove one-off reactive patterns that are no longer needed after the shared page contract is in place.
- [ ] Do a final cleanup pass in `dashboard/app.py` and `dashboard/components.py` so the architecture is consistent end to end.

## Final Validation

- [ ] Confirm tab changes no longer jump the user back to `Overview`.
- [ ] Confirm global mode changes no longer send the user to a random tab.
- [ ] Confirm local selectors persist after moving away from and back to a tab.
- [ ] Confirm repeated filter combinations hit caches instead of recomputing.
- [ ] Confirm only the active tab refreshes immediately on global mode changes.
- [ ] Confirm a stale inactive tab refreshes correctly when first revisited.
- [ ] Confirm static export still works after the live-app refactor.
