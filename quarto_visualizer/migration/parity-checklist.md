# Parity Checklist and Risk Log

## Phase 6 Status

- Automated parity validation passed on 2026-03-23 via `activitysim-viz-validate-parity --report-markdown quarto_visualizer/migration/phase-6-validation.md`.
- See `phase-6-validation.md` for the current report summary and remaining manual follow-up items.
- Checked boxes below are covered by the current validator or direct dashboard structure checks.
- Unchecked boxes still need manual UI smoke testing, broader config/data coverage, or an explicit post-parity product decision.

## Core behaviors to preserve

- [ ] The app compares multiple runs side by side in every relevant chart and table.
- [ ] Run colors are stable and tied to run order.
- [ ] The sidebar shows the loaded run list and the two global display controls.
- [x] `Weighted` and `Unweighted` switch the whole dashboard, not just a few charts.
- [ ] The first run acts as the base run for the overview percent-difference table.
- [x] Page names and page order stay the same unless intentionally changed.
- [ ] Existing category orderings are preserved where the Panel code forces them.

## Reactive/state risks

- [ ] The Panel app caches whole tab sets by `(weighted, percent)`. The Shiny app should avoid recomputing everything on every input change.
- [ ] The current percent/count behavior is partly global state in `dashboard/components.py`. The port should preserve behavior without relying on mutable globals.
- [ ] Most controls are page-local only. There is no cross-page shared state besides the two sidebar toggles.

## Ambiguous or easy-to-miss behaviors

- [x] Many control option lists are discovered from the first run or first non-empty run, not from the union of all runs. This can hide categories that only exist in later runs.
- [ ] `density_chart()` normalizes to percent by default, so many plots effectively ignore the global `Count` mode.
- [ ] The Overview page mixes outputs that react to `Values` and outputs that do not.
- [ ] Joint-tour and non-mandatory-tour charts often multiply joint tours by `NUMBER_HH`, so some charts are person-equivalent or participant-equivalent rather than raw tour counts.
- [x] `Unweighted` mode sets `finalweight = 1.0` only on households, persons, tours, and trips. Other derived columns remain as prepared earlier.
- [ ] Static export is a frozen `Weighted + Percent` snapshot with controls disabled.

## Page-specific risks

- [x] Long-Term: TLFD geography options come from the first run's `work` TLFD table.
- [x] Long-Term: the WFH chart shows counts of WFH workers, not a share of workers.
- [ ] Tour Summary: person type display labels come from config mappings, but the filter values are raw `ptype` values.
- [ ] Joint Tours: the `HH Size = Total` chart is manually normalized before plotting, so it behaves like a percent plot even in `Count` mode.
- [ ] Joint Tours: `joint_tour_freq()` comments say "most common" purposes, but the code actually takes sorted unique purposes and only the first five.
- [ ] Destination: the distance chart filters to non-mandatory, atwork, and joint tours and weights joint tours by participants.
- [ ] Destination: the average-distance table is built separately and may not align exactly with the plotted chart logic.
- [x] Tour TOD: purpose options include `Total`, and may also include prefixed joint-purpose labels such as `joint_x`.
- [x] Tour Mode: purpose options are collected across all runs, unlike several other pages.
- [ ] Tour Mode: the grouped-mode summary chart is not connected to the purpose selector.
- [x] Stop Frequency: `Total` aggregates across tour purposes before plotting stop counts and stop purposes.
- [x] Stop Location: there is no selector; the page renders one chart for all purposes plus one chart for every discovered purpose.
- [x] Stop Timing: the summary function creates a `Total` row, but the page selector does not expose `Total`.
- [x] Trip Mode: both purpose and tour mode controls are discovered from the first non-empty run only.

## Recommended parity test cases

- [ ] Compare two runs where one has categories or purposes missing from the other.
- [ ] Toggle `Weighted` vs `Unweighted` on every page and verify that all tables and charts respond as expected.
- [ ] Toggle `Percent` vs `Count` and note which charts actually change.
- [ ] Run with geography enabled and geography disabled.
- [ ] Run with and without mode groups configured.
- [ ] Run with 24-bin timing and 48-bin timing data if both cases exist in real deployments.
