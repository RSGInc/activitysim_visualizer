# Summary Comparison Notes

## Scope and Method

This review compares every table written by `point_of_comparison/SummarizeABM.R` against the Python summary functions in `processor/summarize/summaries/`.

This is a second-pass review focused on the "spirit" of each summary. Weighting differences and minor labeling/schema differences are intentionally de-emphasized unless they change the substantive logic of the summary.

Status meanings:

- `Implemented`: clear Python analog exists and is conceptually close.
- `Partial`: a Python analog exists, but the implementation does not match the R logic exactly.
- `Missing`: no clear Python summary function exists for that R output.

## Cross-Cutting Findings

1. Many Python summaries are clearly intended to cover the same business question as the R outputs, even when the output schema is modernized or normalized.
2. The most important mismatches are not weights or labels, but differences in:
   - universe/filter definitions
   - purpose bucketing and recodes
   - whether individual and joint travel are combined the same way
   - whether a summary is an OD matrix versus a 1-D distribution
   - whether a legacy "visualizer" export is represented by one normalized Python table or is missing entirely
3. Geography handling still matters substantively when the R summary is specifically an OD matrix or district/county table and Python instead emits only marginal geography summaries.
4. Several Python summaries combine multiple R visualizer files into one normalized summary. Those are treated as `Implemented` here when the underlying logic is the same.
5. The clearest substantive mismatches I found are:
   - `daily_travel_activity.dap_summary()` does not apply the R recode of `activity_pattern == "M"` to `N` or `H` before summarizing.
   - `joint_travel.joint_tour_freq()` explicitly has a `TODO` and its alternative ordering does not match the R `jtf.csv` coding.
   - `tour_geography.avg_non_mand_tour_distance()`, `int_vs_ext_non_mand_tour_freq()`, and `ext_non_mand_tour_loc()` filter on `"non_mandatory"` with an underscore, while other code uses `"non-mandatory"` with a hyphen.
   - `trip_distributions.stop_ood_distance()` does not appear to combine individual-stop and joint-stop records the way the R script does.
   - Python does not reproduce several legacy matrix-style summaries at all: external/CVM, stop-frequency-model alternatives, non-mandatory district-to-district flows, and the three school-escort cross-tabs.

## Comparison Matrix

| R output(s) | Python analog(s) | Status | Notes |
| --- | --- | --- | --- |
| `cvm_summary.csv` | none; nearest is `validation.commercial_vehicle_vmt()` | Missing | Python has no commercial vehicle trip summary by TOD and mode. The nearest Python function is VMT-only and expects a different input shape. |
| `cvm_vmt_summary.csv` | `validation.commercial_vehicle_vmt()` | Partial | Python only returns long-form commercial VMT by vehicle type/internal-external split, not the R TOD x mode matrix with daily totals. |
| `ext_summary.csv` | none | Missing | No Python summary for external trip matrices by TOD and purpose. |
| `ext_vmt_summary.csv` | none | Missing | No Python summary for external VMT matrices by TOD and purpose. |
| `autoOwnership_Pre.csv` | none | Missing | Python has no pre/post auto ownership comparison summary. |
| `autoOwnership.csv` | `long_term_vehicle.auto_ownership()` | Implemented | Same underlying summary: households by auto ownership level. Python is a normalized version of the same concept. |
| `zeroAutoByTaz.csv` | none | Missing | No Python summary for zero-auto households by TAZ. |
| `pertypeDistbn.csv` | `demographics.person_type()` | Implemented | Same summary in spirit: population by person type. |
| `workTLFD.csv`, `univTLFD.csv`, `schlTLFD.csv` | `long_term_distance.work_tlfd()`, `univ_tlfd()`, `schl_tlfd()` | Implemented | Same business logic in spirit: mandatory destination length frequency by worker/university/school segments and home geography. Python uses a normalized geography format and slightly different bins. |
| `mandTripLengths.csv` | `tour_geography.avg_mand_tour_distance()` | Implemented | Same underlying question: average mandatory destination distance by segment and home geography. Python expresses it in long form rather than the R district table. |
| `wfh_summary.csv`, `wfh_summary_region.csv` | `long_term_geography.wfh()` | Implemented | Same business question: workers and WFH workers by home geography plus total. Python uses a prepared WFH field instead of the R sentinel code check. |
| `countyFlows.csv`, `countyFlows_JoJa.csv` | `long_term_geography.commuting_flows()`, `legacy.geo_flows()` | Partial | Python has commuting-flow summaries, but not the same wide district/county matrices with margin totals. Python also weights. |
| `stopFreqModel_summary.csv` | none | Missing | No Python summary for the 16-alternative stop frequency model table (`STOP_FREQ_ALT x TOURPURP`). |
| `tour_rate_debug.csv`, `temp2.csv` | none | Missing | Debug outputs only; no Python analog. |
| `indivNMTourFreq.csv` | none | Missing | No Python summary reproduces the exact legacy text-plus-table export split by persons with/without mandatory tours. |
| `toursPertypeDistbn.csv`, `total_tours_by_pertype_vis.csv` | nearest: `daily_travel_activity.tour_rate_per_person()` | Missing | Python has tour rates, not the exact total-tour count tables by person type, and no exact equivalent of the joint-tour add-on logic used for `total_tours_by_pertype_vis.csv`. |
| `tours_pertype_purpose.csv` | nearest: `legacy.nm_tour_rates()` | Missing | Python does not emit the raw non-mandatory tour counts by person type and purpose. |
| `inmtours_pertype_purpose.csv` | none | Missing | No Python summary for the capped per-person category counts (`i4numTours` ... `i9numTours`) by purpose and person type. |
| `nm_tour_rates.csv` | `legacy.nm_tour_rates()` | Implemented | Same summary in spirit: non-mandatory tour rates by person type and non-mandatory purpose. |
| `tours_purpose_type.csv` | none | Missing | No Python summary for the side-by-side individual vs joint tour count table by purpose. |
| `dapSummary.csv`, `dapSummary_vis.csv` | `daily_travel_activity.dap_summary()` | Partial | Same target summary, but Python misses the substantive R recode that converts some `M` patterns to `N` or `H` before aggregation. |
| `hhsizeJoint.csv` | `joint_travel.joint_tours_hhsize()` | Partial | Related but not the same. R summarizes `HHSIZE x JOINT` directly, while Python summarizes households by size with a `has_joint_tour` split. |
| `mtfSummary.csv`, `mtfSummary_vis.csv` | `daily_travel_activity.mandatory_tour_freq()` | Implemented | Same summary in spirit: mandatory tour frequency by person type. |
| `innmSummary.csv`, `inmSummary_vis.csv` | `daily_travel_activity.indiv_nm_summary()` | Implemented | Same business logic in spirit: people bucketed by number of non-mandatory tours, with joint participation folded in. |
| `jtfSummary.csv` | nearest: multiple `joint_travel.*` functions | Missing | The R file appends several distinct tables into one CSV. Python exposes separate functions instead of one combined export. |
| `jtf.csv` | `joint_travel.joint_tour_freq()` | Partial | Same intended summary, but the actual JTF mapping logic does not yet match the R coding. |
| `jointComp.csv` | `joint_travel.joint_composition()` | Implemented | Same summary in spirit: joint tour composition distribution. |
| `jointPartySize.csv` | `joint_travel.joint_party_size()` | Implemented | Same summary in spirit: joint party size distribution with `5+` cap behavior. |
| `jointCompPartySize.csv` | `joint_travel.joint_composition_by_party_size()` | Partial | Same dimensions, but the R output is already converted to composition-specific percentages with capping, while Python emits the underlying counts. |
| `jointToursHHSize.csv` | `joint_travel.jtf_by_hhsize()` | Implemented | Same business question in spirit: how joint-tour frequency categories vary by household size. |
| `todDepProfile.csv`, `todArrProfile.csv`, `todDurProfile.csv`, `todProfile_vis.csv` | `tour_profiles.tour_tod()` | Partial | Same general summary family, but the R script uses custom purpose regrouping that collapses individual and joint non-mandatory purposes into `imain/idisc/jmain/jdisc`. Python does not apply that same regrouping. |
| `todStopsIB.csv`, `todStopsOB.csv`, `todStopsIB_joint.csv`, `todStopsOB_joint.csv` | none | Missing | No Python summary for stop counts by tour purpose and start/end TOD cells. |
| `tmodeAS0Profile.csv`, `tmodeAS1Profile.csv`, `tmodeAS2Profile.csv`, `tmodeProfile_vis.csv` | `tour_profiles.tour_mode()`, nearest legacy `grouped_tour_mode_profile()` | Partial | Same general summary family, but the R script uses custom purpose regrouping and explicit individual/joint bucket construction. Python does not mirror those exact regroupings. |
| `nonMandTourDistProfile.csv`, `tourDistProfile_vis.csv` | `tour_profiles.tour_distance()`, nearest legacy `distance_distribution()` | Implemented | Same summary in spirit: non-mandatory tour distance distributions with combined individual/joint non-mandatory groupings. |
| `nonMandTripLengths.csv` | `legacy.average_distance()`, nearest `tour_geography.avg_non_mand_tour_distance()` | Partial | `legacy.average_distance()` is close in spirit, but purpose grouping still differs from the R `esco/imain/idisc/jmain/jdisc/atwork/Total` structure. `avg_non_mand_tour_distance()` also has the likely category-name bug. |
| `stopFreqOutProfile.csv`, `stopFreqInbProfile.csv`, `stopFreqTotProfile.csv`, `stopfreqDir_vis.csv`, `stopfreq_total_vis.csv` | `tour_profiles.stop_freq()` | Implemented | Same business question in spirit: stop frequencies by tour purpose across outbound, inbound, and total stop counts. |
| `stopPurposeByTourPurpose.csv`, `stoppurpose_tourpurpose_vis.csv` | `trip.stop_purpose_by_tour_purpose()` | Implemented | Same summary in spirit: stop purpose by tour purpose. |
| `stopOutOfDirectionDC.csv`, `stopDC_vis.csv` | `trip_distributions.stop_ood_distance()` | Partial | Same target summary, but R explicitly combines both individual stops and joint stops, while Python appears to summarize only the prepared trip table side. |
| `avgStopOutofDirectionDist_vis.csv` | none | Missing | No Python summary for average out-of-direction stop distance by grouped purpose. |
| `stopDeparture.csv`, `tripDeparture.csv`, `stopTripDep_vis.csv` | `trip_distributions.trip_stop_tod()` | Partial | Same summary family, but the R script again uses specific regrouped purposes and explicitly includes both individual and joint records in its legacy construction. |
| `tripModeProfile_Work.csv`, `tripModeProfile_Univ.csv`, `tripModeProfile_Schl.csv`, `tripModeProfile_iMain.csv`, `tripModeProfile_iDisc.csv`, `tripModeProfile_jMain.csv`, `tripModeProfile_jDisc.csv`, `tripModeProfile_AtWork.csv`, `tripModeProfile_Total.csv`, `tripModeProfile_vis.csv` | `trip.trip_mode()` | Implemented | Same business question in spirit: trip mode by tour purpose and tour mode, including an all-purpose total. Python represents the same content as one normalized table instead of many legacy CSVs. |
| `totals.csv` | `legacy.system_totals()`, `demographics.population_totals()`, `validation.auto_vmt_totals()` | Partial | Python covers much of the same KPI space, but the R VMT logic is substantively more specific: it adjusts escortee trips, occupancies, joint-trip handling, and transit drive access/egress. |
| `individualTripsCTRAMP.csv`, `jointTripsCTRAMP.csv` | none | Missing | These are raw trip exports, not Python summary functions. |
| `hhSizeDist.csv` | `demographics.hh_size()` | Implemented | Same summary in spirit: households by size. |
| `activePertypeDistbn.csv` | none | Missing | No Python summary for active person types only (`activity_pattern != "H"`). |
| `districtFlows_iNonMand.csv`, `districtFlows_jNonMand.csv` | none; nearest are `tour_geography.int_vs_ext_non_mand_tour_freq()` and `ext_non_mand_tour_loc()` | Missing | Python has no OD flow matrix summary for non-mandatory individual or joint tours. The nearest geography summaries are not OD matrices. |
| `esctype_by_childtype.csv` | nearest: `daily_travel_escort_counts.student_school_escort_status_by_direction()` | Missing | Python has escort summaries, but not the exact escort-type x child-type table with separate outbound/inbound columns and totals. |
| `esctype_by_chauffeurtype.csv` | none | Missing | No Python summary for escort-type x chauffeur person type. |
| `worker_school_escorting.csv` | none | Missing | No Python summary for worker escorting status cross-tab among active workers with active students in household. |

## Highest-Priority Gaps

If the goal is one-for-one parity with the R script, the biggest missing areas are:

1. External/CVM summaries.
2. Stop-frequency model alternative summary.
3. Tour/trip OD flow matrices for non-mandatory travel.
4. The three legacy escort cross-tabs.
5. Exact person-type tour count tables and active-person-only summaries.

## Highest-Priority Logic Mismatches In Existing Python Summaries

1. `daily_travel_activity.dap_summary()` is missing the R recode from `M` to `N/H`.
2. `joint_travel.joint_tour_freq()` does not yet match the legacy JTF coding.
3. `tour_profiles.tour_tod()`, `tour_profiles.tour_mode()`, `legacy.average_distance()`, and `trip_distributions.trip_stop_tod()` do not mirror the same purpose regroupings used by the R script.
4. `trip_distributions.stop_ood_distance()` does not appear to combine individual and joint stop records the same way as the R summary.
5. `tour_geography.avg_non_mand_tour_distance()`, `int_vs_ext_non_mand_tour_freq()`, and `ext_non_mand_tour_loc()` should be checked for the `non_mandatory` category filter before relying on them as analogs.
