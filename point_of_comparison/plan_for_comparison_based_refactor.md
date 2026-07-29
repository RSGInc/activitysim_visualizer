# Plan For Comparison-Based Refactor

## Goal

Bring `processor/summarize/summaries/` closer to the business logic in `point_of_comparison/SummarizeABM.R`, with emphasis on:

- missing summaries that have no Python analog today
- partial summaries where the Python function answers a similar question but uses different filters, recodes, joins, purpose regroupings, or individual/joint combination logic

This plan intentionally treats weighting and output-shape differences as secondary unless they change the substantive logic.

## Recommended Strategy

Do this in two tracks rather than trying to force everything into the current normalized summaries immediately:

1. Preserve and improve the existing normalized summary layer where it is already conceptually correct.
2. Add a small "legacy parity" layer for summaries that are genuinely legacy-specific:
   - wide matrices
   - special purpose regroupings like `imain`, `idisc`, `jmain`, `jdisc`
   - one-off CTRAMP/visualizer exports
   - summaries that explicitly combine individual and joint records in legacy-specific ways

## Architectural Recommendation

### 1. Keep the existing normalized modules

These should remain the home for summaries that are already close in spirit:

- `daily_travel_activity.py`
- `joint_travel.py`
- `tour_profiles.py`
- `trip.py`
- `trip_distributions.py`
- `long_term_distance.py`
- `long_term_geography.py`
- `tour_geography.py`
- `validation.py`

### 2. Add a dedicated legacy-parity module or modules

Recommended new files:

- `processor/summarize/summaries/legacy_long_term.py`
- `processor/summarize/summaries/legacy_daily_travel.py`
- `processor/summarize/summaries/legacy_tour_trip_profiles.py`
- `processor/summarize/summaries/legacy_escort.py`
- `processor/summarize/summaries/legacy_validation.py`

Reason:

- The R script contains many wide-table and visualizer-oriented outputs that do not fit naturally into the cleaner normalized Python summaries.
- Keeping parity code isolated will reduce clutter in the main summaries and make it obvious which functions are "legacy-compatible" versus "modernized."

### 3. Add shared helper functions before adding many new summaries

This is the highest-leverage refactor step. Several current mismatches come from missing common logic rather than missing raw aggregation code.

Recommended helper areas:

- purpose recoding and grouping
- joint-tour and joint-trip harmonization
- stop-table harmonization
- legacy binning helpers
- legacy matrix/pivot helpers
- legacy VMT helpers

## Shared Helper Refactors

### A. Purpose recoding / grouping helpers

Recommended new helper module:

- `processor/summarize/summaries/legacy_purpose_helpers.py`

Add helpers for:

- mapping legacy numeric `TOURPURP` / `JOINT_PURP` concepts onto shared Python purpose buckets
- grouping purposes into:
  - `work`
  - `univ`
  - `sch`
  - `esco`
  - `imain` = individual purposes 5-6
  - `idisc` = individual purposes 7-9
  - `jmain` = joint purposes 5-6
  - `jdisc` = joint purposes 7-9
  - `atwork`
  - `total`
- optionally grouping non-mandatory distance summaries into:
  - `esco`
  - `imain`
  - `idisc`
  - `jmain`
  - `jdisc`
  - `atwork`
  - `total`

This helper should be used by:

- `tour_profiles.tour_tod()`
- `tour_profiles.tour_mode()`
- `legacy.average_distance()`
- `trip_distributions.trip_stop_tod()`
- any new legacy profile summaries

### B. Joint record harmonization helpers

Recommended helper responsibilities:

- build a common "joint tour prepared frame"
- build a common "joint trip prepared frame"
- apply legacy participant scaling when the R logic uses person-equivalent counts
- keep separate cases where the R logic explicitly does not scale by participants

Important distinction from R:

- some legacy summaries use `NUMBER_HH`
- some use `num_participants`
- some leave joint trips at one record per household trip
- some explicitly combine individual and joint data only after transforming them to a common meaning

The helper layer should expose that explicitly rather than hiding it inside many summary functions.

### C. Stop-table helpers

The R script constructs explicit `stops` and `jstops` tables and then uses them repeatedly.

Recommended helper:

- `build_legacy_stop_tables(rd, config) -> {"stops": ..., "jstops": ...}`

This helper should:

- identify stop records for individual trips
- identify stop records for joint trips
- preserve the fields needed by the R parity summaries:
  - tour purpose
  - stop purpose
  - stop period
  - out-of-direction distance
  - any escort fields needed downstream

This is especially important for:

- `stop_ood_distance`
- `trip_stop_tod`
- stop-purpose summaries
- average out-of-direction summaries

### D. Legacy binning helpers

Recommended helpers:

- `legacy_distance_bin_0_40_plus()`
- `legacy_distance_bin_1_41()`
- `legacy_stop_freq_alt(num_ob_stops, num_ib_stops)`
- `legacy_tod_five_period(start_or_end_period)`

Use these to eliminate repeated hand-coded logic and to ensure R-equivalent binning.

### E. Wide matrix helpers

Recommended helper patterns:

- pivot long-form to wide matrix with totals row/column
- percent-normalize by row or column
- cap bins after percent conversion when needed

Useful for:

- county/district flows
- joint composition x party size
- JTF by household size
- escort cross-tabs

### F. Legacy VMT helpers

Recommended helper module or section in `validation.py`:

- compute occupancy by trip mode following the R logic
- adjust school escort chauffeur vs escortee treatment
- incorporate drive-access and drive-egress VMT for transit
- handle joint trips per legacy household-record semantics

This logic is too specific to leave scattered across summary functions.

## Phase Plan

## Phase 1: Fix substantive mismatches in existing functions

These are the safest, highest-value changes because they improve current summaries without introducing a lot of new surface area.

### 1. `daily_travel_activity.dap_summary()`

Business logic difference:

- R recodes `activity_pattern == "M"` to:
  - `N` when `imf_choice == 0` and `inmf_choice > 0`
  - `H` when `imf_choice == 0` and `inmf_choice == 0`
- Python currently summarizes `cdap_activity` directly without that recode.

Implementation plan:

- add a helper such as `recode_legacy_dap_activity(per_df)`
- apply it before grouping in `dap_summary()`
- keep the current normalized output shape

Tests:

- add unit tests with rows that should recode `M -> N`
- add unit tests with rows that should recode `M -> H`
- verify ordinary `M` rows remain `M` when they still have mandatory tours

### 2. `joint_travel.joint_tour_freq()`

Business logic difference:

- R uses a specific 21-alternative JTF coding and label order.
- Python currently uses a simplified coding path and already has a `TODO`.

Implementation plan:

- port the exact alternative logic from the R script into an explicit helper
- do not rely on dynamically sorted purpose labels
- reproduce the exact `jtf_code` meaning used by the R `jtf.csv`
- make the code table explicit and stable

Suggested helper:

- `compute_legacy_jtf_codes(joint_tours_df) -> household_id, jtf_code`

Tests:

- one test per major alternative family:
  - no joint tours
  - one shopping
  - two same-purpose tours
  - one tour in each of two purposes
- verify ordering and labels match legacy definitions

### 3. `tour_geography.avg_non_mand_tour_distance()`

Business logic difference:

- likely filters on `"non_mandatory"` instead of `"non-mandatory"`
- also does not answer the same question as the R `nonMandTripLengths.csv`, which is grouped into `esco/imain/idisc/jmain/jdisc/atwork/total`

Implementation plan:

- first fix the category filter bug
- then decide whether to:
  - keep this function as a normalized non-mandatory geography summary
  - add a separate legacy-parity function for the grouped-purpose summary

Recommendation:

- keep `avg_non_mand_tour_distance()` normalized
- add a separate legacy grouped summary rather than overloading this function

### 4. `tour_geography.int_vs_ext_non_mand_tour_freq()` and `ext_non_mand_tour_loc()`

Business logic difference:

- same likely category-name bug
- also these are not substitutes for the missing R district-to-district OD flow summaries

Implementation plan:

- fix the category-name bug
- keep these functions
- separately add true OD matrix summaries for `districtFlows_iNonMand.csv` and `districtFlows_jNonMand.csv`

### 5. `trip_distributions.stop_ood_distance()`

Business logic difference:

- R explicitly combines individual stop table `stops` and joint stop table `jstops`
- Python currently appears to summarize only `rd.trips`

Implementation plan:

- use a legacy stop-table helper that prepares both individual-stop and joint-stop records
- aggregate both together using the same purpose regrouping used in the R summary
- preserve the current normalized version if still useful, but add a legacy-parity function if necessary

### 6. `tour_profiles.tour_tod()`, `tour_profiles.tour_mode()`, `legacy.average_distance()`, `trip_distributions.trip_stop_tod()`

Business logic difference:

- current Python functions mostly summarize prepared purposes directly
- R uses custom regroupings:
  - mandatory purposes split individually
  - individual non-mandatory collapsed into `imain` and `idisc`
  - joint non-mandatory collapsed into `jmain` and `jdisc`
  - at-work separated

Implementation plan:

- do not mutate the existing normalized summaries to only support legacy buckets
- instead add a shared legacy regrouping helper
- either:
  - add optional `grouping="legacy_ctramp"` parameter, or
  - add separate parity functions in a legacy module

Recommendation:

- use separate legacy functions to avoid contaminating the cleaner normalized summaries

## Phase 2: Add missing long-term and geography summaries

### 1. `zeroAutoByTaz.csv`

New summary:

- suggested function: `legacy_long_term.zero_auto_households_by_home_taz()`

R logic:

- map household home MAZ to TAZ via xwalk
- flag households with `HHVEH == 0`
- aggregate flagged households by TAZ

Python plan:

- use prepared household/home geography fields if available
- if only MAZ exists, map to TAZ via land use or configured geography mapping
- emit long-form rows:
  - `home_taz`
  - `zero_auto_household_count`

### 2. `countyFlows.csv` / `countyFlows_JoJa.csv`

New summary or enhancement:

- either enhance `commuting_flows()` with a matrix export mode
- or add `legacy_long_term.commuting_flow_matrix()`

R logic:

- build home-work OD matrix by district and county
- add totals row/column

Python plan:

- derive the same OD pairs from worker records
- support:
  - district matrix
  - county matrix
- emit normalized long form first, then optionally a wide-export helper if the dashboard/export layer needs exact legacy shape

## Phase 3: Add missing daily travel activity summaries

### 1. `toursPertypeDistbn.csv`

New summary:

- `legacy_daily_travel.tours_by_person_type()`

R logic:

- count tours by person type
- exclude `TOURPURP == 10`

Python plan:

- use prepared tours with person type attached
- exclude at-work if the intent is exact R parity

### 2. `total_tours_by_pertype_vis.csv`

New summary:

- `legacy_daily_travel.total_tours_by_person_type_including_joint()`

R logic:

- start with individual tours by person type
- explode joint tours by participant person types
- add joint counts to the individual counts

Python plan:

- use joint participant table rather than household-level joint tour rows
- aggregate participant person types and add them to individual totals

### 3. `tours_pertype_purpose.csv`

New summary:

- `legacy_daily_travel.non_mandatory_tours_by_person_type_and_purpose()`

R logic:

- count individual non-mandatory tours by `PERTYPE x TOURPURP`

Python plan:

- use individual tours only
- keep purpose at the legacy purpose-code grain

### 4. `inmtours_pertype_purpose.csv`

New summary:

- `legacy_daily_travel.capped_non_mandatory_tour_frequency_by_person_type_and_purpose()`

R logic:

- derive per-person counts by each purpose
- cap some purpose counts at 1 and others at 2
- then summarize persons by `PERTYPE x capped_count x purpose`

Python plan:

- reproduce the capping rules exactly
- encode them in one helper rather than six bespoke blocks

### 5. `tours_purpose_type.csv`

New summary:

- `legacy_daily_travel.tours_by_purpose_and_tour_type()`

R logic:

- compare individual tour counts and joint tour counts by purpose

Python plan:

- aggregate individual tours by purpose
- aggregate joint tours by joint purpose
- combine into one side-by-side normalized output

### 6. `hhsizeJoint.csv`

Current analog is partial.

Implementation plan:

- add a dedicated function:
  - `legacy_daily_travel.household_size_by_joint_flag()`
- R logic is specifically `HHSIZE x JOINT`
- keep `joint_tours_hhsize()` as the normalized current summary

### 7. `activePertypeDistbn.csv`

New summary:

- `legacy_daily_travel.active_person_type_distribution()`

R logic:

- persons by type where `activity_pattern != "H"`

Python plan:

- use the same post-recode activity field used by `dap_summary()`

### 8. `indivNMTourFreq.csv`

New summary if parity is desired:

- `legacy_daily_travel.nm_tours_for_mandatory_vs_nonmandatory_people()`

R logic:

- write two separate blocks:
  - persons with at least one mandatory tour
  - active persons with zero mandatory tours

Python plan:

- create one normalized summary with a segment field rather than reproducing the append-style text file

## Phase 4: Add missing joint travel summaries

### 1. `jtfSummary.csv`

R behavior:

- appends multiple conceptually distinct summaries into one CSV

Python plan:

- do not reproduce the append-style file directly
- instead add explicit parity functions for each table that R combines:
  - JTF distribution
  - joint composition
  - joint party size
  - composition x party size
  - joint-tour category by household size

### 2. `jointCompPartySize.csv`

Current analog is partial.

Implementation plan:

- keep `joint_composition_by_party_size()` as the base count summary
- add a second parity function:
  - `legacy_daily_travel.joint_composition_by_party_size_percent()`
- reproduce:
  - row normalization by composition
  - capping at party size 5

## Phase 5: Add missing tour/trip legacy profile summaries

### 1. `stopFreqModel_summary.csv`

New summary:

- `legacy_tour_trip_profiles.stop_frequency_model_alternative_by_purpose()`

R logic:

- combine individual and joint tours into one temp table
- derive a 16-category stop-frequency alternative from `num_ob_stops` and `num_ib_stops`
- tabulate by tour purpose

Python plan:

- add helper `legacy_stop_freq_alt()`
- prepare a combined individual/joint tour frame with a harmonized purpose field
- aggregate `STOP_FREQ_ALT x purpose`

### 2. `todStopsIB.csv`, `todStopsOB.csv`, `todStopsIB_joint.csv`, `todStopsOB_joint.csv`

New summaries:

- `legacy_tour_trip_profiles.stop_counts_by_start_end_tod_and_purpose()`

R logic:

- derive 5-period TOD buckets from start and end period
- sum inbound/outbound stop counts by `tour_purpose x start_tod x end_tod`
- do this separately for individual and joint tours

Python plan:

- shared helper for 5-period TOD recode
- separate outputs for individual and joint to preserve legacy meaning

### 3. `todProfile_vis.csv`

Current analog is partial.

Implementation plan:

- add parity function that uses legacy purpose regrouping
- likely easiest to build from three internal helper summaries:
  - departure counts
  - arrival counts
  - duration counts

### 4. `tmodeProfile_vis.csv`

Current analog is partial.

Implementation plan:

- add parity function with:
  - legacy purpose regrouping
  - auto sufficiency split
  - explicit joint-tour handling aligned with R

### 5. `nonMandTripLengths.csv`

Current analog is partial.

Implementation plan:

- add parity function for grouped-purpose averages:
  - `esco`
  - `imain`
  - `idisc`
  - `jmain`
  - `jdisc`
  - `atwork`
  - `total`

### 6. `avgStopOutofDirectionDist_vis.csv`

New summary:

- `legacy_tour_trip_profiles.average_stop_ood_distance_by_grouped_purpose()`

R logic:

- average out-of-direction distance over the legacy grouped purposes
- combine individual and joint stop tables

### 7. `stopTripDep_vis.csv`

Current analog is partial.

Implementation plan:

- build one legacy parity function from common stop/trip departure timing helpers
- ensure joint records are included where the R summary includes them

### 8. `tripModeProfile_vis.csv`

Current analog is implemented in spirit, but parity mode is still useful.

Implementation plan:

- add an optional parity builder that reproduces:
  - the grouped purpose buckets
  - the explicit separate purpose slices
  - joint-trip participant weighting behavior

## Phase 6: Add missing non-mandatory OD flow summaries

### 1. `districtFlows_iNonMand.csv`

New summary:

- `legacy_tour_trip_profiles.individual_nonmandatory_district_flows()`

R logic:

- OD district matrix for individual non-mandatory tours including at-work

Python plan:

- select individual tours with purposes 4-10
- aggregate `origin_district x destination_district`
- add totals

### 2. `districtFlows_jNonMand.csv`

New summary:

- `legacy_tour_trip_profiles.joint_nonmandatory_district_flows()`

R logic:

- OD district matrix for joint tours weighted by `NUMBER_HH`

Python plan:

- use joint tours only
- aggregate by origin/destination district
- apply the same joint weighting semantics as the R summary

## Phase 7: Add missing escort summaries

These are clearly missing rather than just partial.

### 1. `esctype_by_childtype.csv`

New summary:

- `legacy_escort.escort_type_by_child_type()`

R logic:

- school tours only
- child person types only
- outbound and inbound escort type tabulations
- recode no escort to `3`
- add totals across child type

Python plan:

- use school-tour subset of student tours
- build one normalized output with columns:
  - `escort_type`
  - `child_type`
  - `freq_out`
  - `freq_inb`

### 2. `esctype_by_chauffeurtype.csv`

New summary:

- `legacy_escort.escort_type_by_chauffeur_type()`

R logic:

- school tours only
- join driver person type for outbound and inbound driver
- tabulate escort type by chauffeur person type

Python plan:

- add helper that maps `driver_num_out` / `driver_num_in` to person type within household

### 3. `worker_school_escorting.csv`

New summary:

- `legacy_escort.worker_school_escort_status_matrix()`

R logic:

- identify active workers with work/work-based tours
- identify active student households
- identify workers who chauffeur school tours
- classify worker outbound and inbound escort status
- build a 3x3 matrix with totals

Python plan:

- this should be implemented exactly as a dedicated helper-driven summary
- do not try to stretch the current escort summaries to cover it

## Phase 8: Add missing validation / totals parity summaries

### 1. CVM and external summaries

New summaries:

- `legacy_validation.cvm_trips_by_tod_and_mode()`
- `legacy_validation.cvm_vmt_by_tod_and_mode()`
- `legacy_validation.external_trips_by_tod_and_purpose()`
- `legacy_validation.external_vmt_by_tod_and_purpose()`

Implementation note:

- these likely depend on OMX or other non-standard inputs, so they should be clearly marked optional
- they belong in a parity/validation module, not in the core daily travel modules

### 2. `totals.csv`

Current analog is partial.

Implementation plan:

- add a dedicated `legacy_validation.legacy_system_totals()` summary
- port the R VMT business logic exactly:
  - occupancy rules by trip mode
  - escort chauffeur vs escortee treatment
  - joint-trip handling
  - drive-access and drive-egress transit VMT
  - workers/jobs fields

## Testing Plan

### 1. Unit tests for shared helpers

Add focused tests for:

- DAP recode helper
- legacy purpose regrouping
- stop frequency alternative coding
- legacy five-period TOD recode
- joint JTF coding
- escort-type recodes
- legacy VMT occupancy rules

### 2. Golden tests against small fixture data

For the highest-risk summaries, create tiny hand-checkable fixtures and assert exact outputs:

- `dapSummary`
- `jtf`
- `stopFreqModel_summary`
- `nonMandTripLengths`
- `stopOutOfDirectionDC`
- `tripModeProfile_vis`
- escort cross-tabs
- `totals`

### 3. Regression tests for normalized summaries

Where existing summaries are already consumed by dashboards, preserve current behavior unless we intentionally change it.

This is especially important for:

- `tour_profiles.*`
- `trip.*`
- `daily_travel_activity.*`
- `joint_travel.*`

## Suggested Delivery Order

1. Fix current substantive bugs:
   - `dap_summary`
   - `joint_tour_freq`
   - `non_mandatory` category-name mismatches
   - `stop_ood_distance` individual/joint combination
2. Add shared helper layer:
   - purpose regrouping
   - legacy stop tables
   - TOD bins
   - stop-frequency alternative coding
3. Add high-value missing parity summaries:
   - `stopFreqModel_summary`
   - non-mandatory OD district flows
   - escort cross-tabs
   - grouped-purpose average distance summaries
4. Add long-tail legacy exports:
   - HH/person-type specialty summaries
   - joint append-style components
   - CVM/external optional summaries
   - legacy totals/VMT parity

## Implementation Principles

1. Prefer adding small, explicit parity functions over making normalized summaries overly configurable.
2. Put legacy-specific mappings and regroupings into shared helpers instead of re-encoding them inline in many functions.
3. Be explicit about when joint travel is:
   - left as household-level
   - exploded to participants
   - weighted by `NUMBER_HH`
   - weighted by `num_participants`
4. Keep normalized summaries intact unless there is a clear correctness bug.
5. Where a legacy summary is just a wide rendering of a normalized summary, prefer:
   - normalized computation helper
   - thin export/pivot helper

## Expected Outcome

If we follow this plan, the codebase should end up with:

- cleaner separation between normalized summaries and legacy parity summaries
- fewer hidden business rules scattered across individual functions
- better testability for the trickiest legacy logic
- much stronger parity with `SummarizeABM.R` in the areas that currently matter most
