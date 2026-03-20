# Panel Behavior Spec

## Global inputs

The dashboard depends on:

- `config.yaml` for file names, column names, person type labels, zone handling, geography settings, skim matrix name, mode ordering/grouping, run definitions, and run colors.
- Raw ActivitySim outputs per run:
  - `final_households`
  - `final_persons`
  - `final_tours`
  - `final_trips`
  - `final_joint_tour_participants`
  - `final_land_use`
- Optional OMX skim file per run or globally.

## Shared transformations

Before any page renders, all runs go through the same shared pipeline:

- File resolution: parquet first, then csv, unless the config forces an extension.
- Weight derivation:
  - household: explicit HH weight column, else `1 / sample_rate`, else `1.0`
  - person: explicit person weight, else inherit household weight
  - trip: explicit trip weight, else inherit person weight
  - tour: average trip weight when explicit trip weights exist, else inherit person weight
- Zone enrichment:
  - optional MAZ to TAZ conversion
  - optional geography labels from land use
- Distance enrichment:
  - person home-work and home-school skim distance
  - tour origin-destination skim distance
  - trip origin-destination distance
  - trip out-of-direction distance
- ActivitySim-specific derived fields:
  - `HHVEH`, `HHSIZE`, `WORKERS`, `ADULTS`
  - `AUTOSUFF`
  - parsed stop counts from `stop_frequency`
  - `NUMBER_HH` from joint participants
  - `start_hour`, `end_hour`, `tourdur`, `depart_hour`
  - trip-level `stops`

## Global controls

### Weighting

- Control: sidebar `RadioButtonGroup`
- Options: `Weighted`, `Unweighted`
- Effect:
  - swaps the entire tab set between prepared weighted runs and cloned unweighted runs
  - affects KPIs, tables, and all charts that use `finalweight`
  - does not re-run `prepare_data()`, only changes the weights already attached to the data

### Values

- Control: sidebar `RadioButtonGroup`
- Options: `Percent`, `Count`
- Intended effect:
  - bar charts switch between raw values and per-trace normalization to 100%
- Actual implementation detail:
  - chart helpers read a global `_DISPLAY_PERCENT_MODE` flag
  - many density charts always normalize to percent regardless of this toggle because `density_chart(..., normalize=True)` is used almost everywhere

## Page-by-page behavior

### Overview

- Inputs:
  - `totals.system_totals()`
  - `demographics.person_type()`
  - `demographics.hh_size()`
- Transformations:
  - single-row KPI summaries per run
  - percent-difference table versus the first run
  - grouped bars for person type and household size
- Outputs:
  - six KPI cards currently shown: Population, Households, VMT, Tours, Trips, Stops
  - Tabulator table of percent differences vs base run
  - Plotly grouped bar charts for person type and household size
- Controls:
  - no page-local controls
  - global Weighting affects everything
  - global Values affects the bar charts but not the KPI cards or percent-difference table

### Long-Term

- Inputs:
  - `demographics.auto_ownership()`
  - `mandatory.tlfd()`
  - `mandatory.wfh()`
  - `mandatory.telecommute()`
  - `mandatory.mand_tour_lengths()`
  - `mandatory.geo_flows()`
- Transformations:
  - auto ownership counts by `HHVEH`
  - TLFD distributions for work, university, and school
  - worker counts by telecommute frequency
  - WFH counts by geography
  - geography flow matrix when geography is enabled
  - average mandatory tour length table
- Outputs:
  - auto ownership bar chart
  - three TLFD density charts
  - telecommute bar chart
  - WFH bar chart
  - geography flow table or a disabled note
  - mandatory tour length table
- Controls:
  - local `Geography` select only when `config.geography_enabled` is true
  - selecting geography swaps the TLFD column used for all three TLFD charts
  - global Values affects the bar charts; the TLFD charts remain normalized percentages

### Tour Summary

- Inputs:
  - `tours.dap_summary()`
  - `tours.mandatory_tour_freq()`
  - `tours.indiv_nm_summary()`
- Transformations:
  - reorder DAP to `M`, `N`, `H`
  - remap MTF codes `1..5` to text labels
  - force NM tour count buckets `0`, `1`, `2`, `3pl`
  - append a synthetic `Total` person type
- Outputs:
  - Daily Activity Pattern bar chart
  - Mandatory Tour Frequency bar chart
  - Individual Non-Mandatory Tours bar chart
- Controls:
  - local `Person Type` select
  - changing person type filters all three charts together
  - display labels come from `config.person_type_labels`

### Joint Tours

- Inputs:
  - `tours.joint_tour_freq()`
  - `tours.joint_composition()`
  - `tours.joint_party_size()`
  - `tours.joint_tours_hhsize()`
- Transformations:
  - fixed ordering for composition: adults, mixed, children
  - cap party size at `5`
  - map household joint-tour presence to `0`, `1`, `2+`
- Outputs:
  - joint tour frequency bar chart with 21 alternatives
  - composition bar chart
  - party size bar chart
  - household-size joint-tour presence bar chart
- Controls:
  - local `HH Size` select with `Total`, `2`, `3`, `4`, `5`
  - selecting a specific HH size filters the final chart to that household size
  - selecting `Total` uses a manually normalized percent distribution across all eligible household sizes

### Destination

- Inputs:
  - raw `rd.tours` via local helper `_nm_dist_by_purpose()`
- Transformations:
  - filter to non-mandatory, atwork, and joint tours
  - weight joint tours by `finalweight * NUMBER_HH`
  - use or derive `SKIMDIST`
  - clip integer distance bins to `0..40`
  - build an average-distance table by purpose
- Outputs:
  - one density chart for NM tour distance distribution by selected purpose
  - Tabulator table of average tour distance by purpose and run
- Controls:
  - local `Purpose` select with `All NM` plus discovered purposes
  - selecting a purpose filters the density chart only
  - the average-distance table is static once the page is built

### Tour TOD

- Inputs:
  - `tour_tod.tod_profiles()`
- Transformations:
  - create separate weighted histograms for departure, arrival, and duration
  - support either 24 one-hour bins or 48 half-hour bins
  - convert time bins to clock labels starting at `03:00`
  - convert duration bins to hours for the duration chart
  - append a synthetic `Total` purpose
- Outputs:
  - departure density chart
  - arrival density chart
  - duration density chart
- Controls:
  - local `Purpose` select
  - changing purpose filters all three charts together
  - global Values currently does not change these charts materially because they stay normalized

### Tour Mode

- Inputs:
  - `tour_mode.tour_mode_profile()`
  - optional `tour_mode.grouped_tour_mode_profile()` when mode groups are configured
- Transformations:
  - separate traces by auto sufficiency bucket `0`, `1`, `2`
  - derive purpose groups from raw purpose strings, including prefixed joint purposes
  - optionally roll detailed modes into configured mode groups
- Outputs:
  - four detailed tour-mode bar charts:
    - all households
    - zero autos
    - autos less than workers
    - autos greater than or equal to workers
  - optional grouped-mode summary chart
- Controls:
  - local `Purpose` select
  - changing purpose filters the four detailed charts
  - the grouped-mode summary chart is not wired to the purpose selector

### Stop Frequency

- Inputs:
  - `stops.stop_freq()`
  - `stops.stop_purpose_by_tour_purpose()`
- Transformations:
  - aggregate outbound, inbound, and total stop counts
  - aggregate stop purposes either across all tour purposes or for one selected tour purpose
- Outputs:
  - outbound stops bar chart
  - inbound stops bar chart
  - total stops bar chart
  - stop-purpose-by-tour-purpose bar chart
- Controls:
  - local `Tour Purpose` select with `Total` plus discovered purposes
  - changing purpose filters all four charts

### Stop Location

- Inputs:
  - `stops.stop_location()`
- Transformations:
  - aggregate out-of-direction distance into bins `0..40`
  - build one overall chart plus one chart per discovered purpose
- Outputs:
  - a column of density charts:
    - all purposes
    - one chart per tour purpose
- Controls:
  - no page-local controls
  - all purposes render eagerly on the page
  - global Values currently does not change these charts materially because they stay normalized

### Stop Timing

- Inputs:
  - `stops.stop_timing()`
- Transformations:
  - weighted histograms of trip departures and stop departures
  - support 24-bin or 48-bin timing
  - convert time bins to clock labels starting at `03:00`
- Outputs:
  - trip departure density chart
  - stop departure density chart
- Controls:
  - local `Purpose` select
  - changing purpose filters both timing charts
  - there is no `Total` option in the selector even though the summary function computes a `Total` row

### Trip Mode

- Inputs:
  - `trips.trip_mode_profile()`
- Transformations:
  - aggregate by `primary_purpose`, `tour_mode`, and `trip_mode`
  - page callback re-groups by `trip_mode` after applying selected filters
- Outputs:
  - one trip-mode bar chart
- Controls:
  - local `Tour Purpose` select
  - local `Tour Mode` select
  - changing either control re-filters the chart

## Output types

- KPI cards built from HTML in `pn.Card`
- Plotly bar charts
- Plotly density/profile charts rendered as filled line charts
- Tabulator tables
- Markdown explanatory text for headings and disabled states
