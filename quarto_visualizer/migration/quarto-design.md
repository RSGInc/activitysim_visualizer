# Quarto + Shiny for Python Design Notes

## Proposed target shape

Use Quarto as the document shell and Shiny for Python as the live runtime. The target should behave like an app, not like a notebook.

The first implementation target should be a close facsimile of the current Panel dashboard. After that, the Quarto version should adopt the parts of Shiny and Quarto that are clearly better suited to this app.

Recommended top-level structure:

| Path | Purpose |
| --- | --- |
| `quarto/dashboard.qmd` | Quarto entry point with `server: shiny` |
| `quarto_visualizer/app_state.py` | startup loading of config and runs |
| `quarto_visualizer/summary_bundle.py` | weighted/unweighted precomputed summaries |
| `quarto_visualizer/plots.py` | Plotly figure builders |
| `quarto_visualizer/pages/*.py` | one Shiny page module per current tab |
| `quarto_visualizer/tables.py` | table rendering helpers |
| `quarto_visualizer/downloads.py` | page-level CSV and export helpers |

## Why this design fits the existing app

- The current Panel app already separates data prep from rendering reasonably well.
- The page modules are mostly functional and can map cleanly to Shiny output functions.
- Plotly is already the chart engine, so the visual port can stay stable.
- Quarto provides the report/app shell without forcing notebook-style state management.

## Reactive model to use

Use explicit Shiny reactive values instead of hidden module globals.

- Global reactives:
  - `input.weight_mode`
  - `input.value_mode`
- Page-local reactives:
  - `input.long_term_geo`
  - `input.tour_summary_ptype`
  - `input.joint_tours_hhsize`
  - `input.destination_purpose`
  - `input.tour_tod_purpose`
  - `input.tour_mode_purpose`
  - `input.stop_freq_purpose`
  - `input.stop_timing_purpose`
  - `input.trip_mode_purpose`
  - `input.trip_mode_tour_mode`
- Derived reactive:
  - `current_bundle = weighted_bundle if input.weight_mode() == "Weighted" else unweighted_bundle`
  - `current_value_mode = input.value_mode()`

Chart helpers should take all state as arguments. No helper should read shared mutable display state.

Recommended reactive structure:

- startup:
  - load config and runs once in Quarto setup context
- derived:
  - compute weighted and unweighted summary bundles once
  - expose page-specific filtered views through `reactive.calc`
- rendering:
  - render charts and tables from those derived reactives

This is the clean Shiny equivalent of the current Panel approach of precomputing data and caching whole tab sets.

## Layout guidance

- Keep a persistent sidebar.
- Show loaded runs in the sidebar with color swatches, matching current Panel behavior.
- Keep global display options in the sidebar.
- Prefer page-local controls inside cards or page headers instead of stacking every selector in the global sidebar.
- Use a tabset or navset with the same page names as the Panel app:
  - Overview
  - Long-Term
  - Tour Summary
  - Joint Tours
  - Destination
  - Tour TOD
  - Tour Mode
  - Stop Frequency
  - Stop Location
  - Stop Timing
  - Trip Mode

Recommended shell:

- global layout:
  - Quarto dashboard page with a persistent sidebar
- navigation:
  - navset-based tabs with bookmarking enabled
- page layout:
  - cards for each major chart/table region
  - local selectors in card headers, toolbars, or page headers
- dense content:
  - enable full-screen cards for charts that benefit from extra width or height

## Rendering choices

- Charts:
  - prefer Plotly figures embedded through Shiny widget rendering so existing chart logic can transfer directly
- Tables:
  - use Shiny `render.data_frame` for comparison tables
  - this is a meaningful upgrade over the current table experience and should become the default table path
- KPI cards:
  - start by matching the current comparison-first layout
  - then convert Overview KPIs to Quarto/Shiny value boxes where that improves readability without hiding per-run comparison
- Downloads:
  - add per-page download actions for filtered tables and derived summaries after parity

## Shiny-first features worth adopting

These are the Quarto/Shiny features most likely to improve the dashboard beyond the Panel version:

- URL bookmarking
  - capture active tab plus filter state so users can share a specific dashboard view
- Value boxes
  - use them on the Overview page for headline metrics if the multi-run comparison remains legible
- `render.data_frame`
  - improve usability of large comparison tables with sorting, filtering, and better scrolling behavior
- Page modules
  - map each current page to a Shiny module for namespacing and maintainability
- Full-screen cards
  - improve readability on dense plot pages without restructuring the app
- Download handlers
  - expose filtered summaries directly from the dashboard instead of requiring separate CLI output

## Data contract to preserve

The Quarto app should continue to work from prepared `RunData` objects or a close equivalent. At minimum the page layer still needs access to:

- run label
- households/persons/tours/trips frames with `finalweight`
- geography fields such as `HGEO` and `WGEO`
- derived distance and timing columns
- optional skim-backed distance measures

## Explicit improvements to make during the port

- Replace `_DISPLAY_PERCENT_MODE` with function arguments.
- Centralize option discovery so "first run only" behavior is either preserved intentionally or fixed intentionally.
- Separate "raw counts" from "normalized display" in chart helpers.
- Keep static export as a secondary concern. First make the live Shiny app correct.

## Recommended rollout

1. Build the Quarto app as a close facsimile of the Panel dashboard.
2. Verify parity for controls, tables, charts, and weighting/value behavior.
3. Add bookmarking, upgraded tables, and card-local controls.
4. Add modules, downloads, and full-screen enhancements.
