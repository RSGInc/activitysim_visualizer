# Migration Plan: Panel to Quarto + Shiny for Python

## Goal

Port the current comparison dashboard to a Quarto + Shiny for Python app while preserving observable behavior first and improving internals second.

The initial milestone should be a close facsimile of the current Panel dashboard. Quarto/Shiny-specific enhancements should be added intentionally after parity, not mixed into the first port unless they reduce risk without changing behavior.

## Recommended strategy

Keep the current summary layer intact during the first port. The least risky path is:

1. keep `summarize/reader.py` and `summarize/*.py` as the canonical data pipeline
2. replace the Panel shell and widget callbacks with Shiny inputs/outputs
3. preserve Plotly as the charting library for visual continuity
4. remove Panel-specific global state only after parity is established

## Phase 1: Freeze current behavior

- Treat the Panel app as the behavioral reference.
- Use the notes in this directory as the initial spec.
- Optionally generate `summary_outputs/` CSVs for one or two reference runs so the Quarto app can be checked against stable intermediate data.
- Use `activitysim-viz-freeze-panel --config config.yaml --output-dir artifacts/panel_reference` to write a weighted/unweighted reference bundle plus a manifest for later parity checks.

## Phase 2: Extract a UI-neutral summary bundle

- Add a new Python layer that takes `list[tuple[str, RunData]]` and returns a dict of precomputed summaries for one weighting mode.
- Recommended shape:
  - `SummaryBundle.overview`
  - `SummaryBundle.long_term`
  - `SummaryBundle.tour_summary`
  - `SummaryBundle.joint_tours`
  - `SummaryBundle.destination`
  - `SummaryBundle.tour_tod`
  - `SummaryBundle.tour_mode`
  - `SummaryBundle.stop_freq`
  - `SummaryBundle.stop_location`
  - `SummaryBundle.stop_timing`
  - `SummaryBundle.trip_mode`
- Precompute two bundles at startup:
  - weighted
  - unweighted
- This mirrors Panel's cached tab sets without carrying Panel code into the new app.

## Phase 3: Build the Quarto + Shiny shell

- Create a Quarto document with `server: shiny`.
- Recreate the current shell structure:
  - sidebar for run list and global controls
  - main area with one tab per page
- Use Shiny inputs for:
  - `weight_mode`
  - `value_mode`
  - page-local selects such as purpose, geography, household size, and tour mode

## Phase 4: Rebuild shared rendering helpers

- Replace `dashboard/components.py` with UI-neutral helpers that return Plotly figures and table-ready frames.
- Make percent/count explicit:
  - `make_bar_chart(..., value_mode="count" | "percent")`
  - `make_density_chart(..., normalize=True | False, value_mode=...)`
- Do not use a module-level mutable flag like `_DISPLAY_PERCENT_MODE`.
- Keep run colors centralized and deterministic.

## Phase 5: Port pages in dependency order

Suggested order:

1. Overview
2. Long-Term
3. Tour Summary
4. Joint Tours
5. Destination
6. Tour TOD
7. Tour Mode
8. Stop Frequency
9. Stop Location
10. Stop Timing
11. Trip Mode

This order starts with the simplest pages and establishes the common chart/table primitives before the more conditional pages.

## Phase 6: Parity validation

For each page, verify:

- same controls exist
- same default selections are used
- same run traces appear
- same category ordering is preserved
- same weighting behavior is preserved
- same percent/count behavior is preserved, even when it looks odd
- same tables and headings are present

Use the parity checklist in [`parity-checklist.md`](/c:/Users/wesley.darling/projects/activitysim_visualizer/quarto_visualizer/migration/parity-checklist.md) to decide what is intentional behavior versus a bug worth fixing after parity.

Current validation command:

- `activitysim-viz-validate-parity --report-markdown quarto_visualizer/migration/phase-6-validation.md`
- The current Phase 6 pass validates the frozen Panel reference bundle, the current `SummaryBundle` projection, selector/default behavior, and the Quarto page/control structure.
- The latest report is tracked in [`phase-6-validation.md`](/c:/Users/wesley.darling/projects/activitysim_visualizer/quarto_visualizer/migration/phase-6-validation.md).

## Phase 7: Post-parity cleanup

After the Quarto app matches the Panel app closely:

- decide whether density charts should continue ignoring `Count` mode
- decide whether control options should still come from only the first run on some pages
- decide whether the grouped tour-mode summary should become purpose-aware
- decide whether the destination average-distance table should align exactly with the plotted NM-tour logic
- factor repeated per-page control logic into reusable Shiny modules if the code is getting repetitive

## Phase 8: Targeted Quarto/Shiny enhancements

Once the app is behaviorally stable, add the features that materially improve usability or maintainability in Quarto/Shiny:

- URL bookmarking
  - preserve active tab, global controls, and page-local filters in the URL
  - makes it possible to share an exact dashboard state with another user
- Shiny data-frame rendering for tables
  - upgrade comparison tables to `render.data_frame`
  - use built-in sorting, filtering, and virtualization instead of static table snapshots
- Card-local controls
  - move local selectors such as purpose, geography, household size, and tour mode closer to the plots they affect
  - keep only truly global controls in the persistent sidebar
- Quarto/Shiny startup and reactive caching
  - use Quarto setup context for startup loading
  - use `reactive.calc` for weighted/unweighted summary bundles and other derived state
  - replace the current global percent flag with explicit reactive inputs
- Shiny modules for page encapsulation
  - convert each page into an isolated module with namespaced inputs and outputs
  - reduce the chance of ID collisions and simplify maintenance
- Download actions
  - allow users to download the currently filtered table or summary CSV for a page
  - optionally support exporting the active Plotly figure
- Full-screen chart cards
  - enable full-screen mode on dense pages such as Joint Tours, Stop Location, Tour TOD, and Long-Term
  - improve readability without changing page structure

## Enhancement priorities

Recommended order after parity:

1. URL bookmarking
2. `render.data_frame` tables
3. Card-local controls
4. Quarto setup context plus `reactive.calc`
5. Shiny modules
6. Downloads
7. Full-screen chart cards

The first four improve sharing, usability, and performance while keeping the dashboard analytically equivalent to the Panel version.

## Success criteria

- The Quarto + Shiny app can load the same runs and config file.
- All current tabs exist.
- Global weighting works the same way.
- Global value mode is either behaviorally identical or any intentional differences are documented.
- The app preserves multi-run comparison as side-by-side traces rather than collapsing to single-run interaction.
- Post-parity enhancements are tracked separately so feature upgrades do not blur parity decisions.
