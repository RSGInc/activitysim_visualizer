# Processor Output Table Reference

This reference documents the tabular products written or accepted by the
ActivitySim Visualizer Output Processor and explains how their fields support
travel analysis and information development.

Prepared output tables preserve the source ActivitySim fields documented above
them on that page. Their field dictionaries therefore focus on stable canonical
and processor-derived additions. Because regional models and configurations can
add source columns, category mappings, named geographies, and skim components,
the prepared schemas are extensible rather than fixed. Summary and sidecar
schemas are exact.

Prepared caches can use Parquet or CSV. Summary caches use CSV and may contain
weighted, unweighted, and segmented variants of the same table contract. Empty,
unavailable, and failed tables can be represented by internal cache sentinels;
the cache manifest records the state and should be consulted before analysis.

<!-- GENERATED:PROCESSOR-OUTPUT-REFERENCE START -->
_Generated from the ActivitySim Visualizer processor contracts and analytical metadata._

## 1. Prepared Output Tables

Prepared caches contain eight canonical tables in the configured Parquet or CSV format. Each file is named `<prepared_table>.<parquet|csv>`. Prepare preserves the source columns described earlier in the SimOR Model Outputs documentation; the field tables below list the stable canonical and processor-derived additions. Configuration-specific category mappings and skim outputs can add further columns.

### `households` Prepared Table

_Processor runtime name: `hh`._

**Information and analytical use.** One row per household. This core prepared table preserves the ActivitySim household record and adds stable weights, household-size and vehicle-count aliases, auto-sufficiency inputs, and home-geography fields. Use it for household controls, demographic profiles, vehicle availability, and residential geography analysis. The cache file is always present, but it contains an empty sentinel when the source table is unavailable or empty.

Retained source fields keep their source meaning and generally keep their source type.

| Field | Type | Description |
|---|---|---|
| `HHSIZE` | `Int32` | Household person count clipped to 1 through 5, where 5 represents households of five or more people. |
| `HHVEH` | `Int32` | Household vehicle count clipped to 0 through 4 for standard summary categories. |
| `av_ownership` | `Boolean-like` | Whether the household owns an autonomous vehicle. |
| `finalweight` | `Float64` | Household expansion weight from the configured weight, inverse sample rate, or 1.0 fallback. |
| `household_id` | `Int64` | Canonical household identifier used to join people, tours, trips, days, and vehicles. |
| `home_zone_id` | `source-compatible identifier` | Household home-zone identifier, normally a MAZ when MAZ processing is enabled. |
| `WORKERS` | `Int32` | Number of workers copied from the configured household worker-count field. |
| `LICENSEDDRIVERS` | `Int32` | Licensed household members derived from person records when license data are available. |
| `ADULTS` | `Int32` | Number of adults copied from the configured household adult-count field. |
| `home_taz` | `source-compatible identifier` | TAZ corresponding to home_zone_id; copied directly in TAZ models or looked up from land use in MAZ models. |
| `HGEO` | `String` | Legacy configured home-geography label used by compatible summaries. |
| `home_geo__<name>` | `String` | Home-geography identifier for each configured named geography aggregation. |

### `persons` Prepared Table

_Processor runtime name: `per`._

**Information and analytical use.** One row per person. This core table preserves ActivitySim person attributes and choices and supplies canonical identifiers, worker/student indicators, home/work/school geography, mandatory-distance measures, and analysis weights. Use it for population segmentation, long-term choice analysis, accessibility, and person-level rates. The cache file is always present, with an empty sentinel when the source is unavailable or empty.

Retained source fields keep their source meaning and generally keep their source type.

| Field | Type | Description |
|---|---|---|
| `age` | `integer` | Person age in years. |
| `bike_comfort` | `category` | Modeled bicycle-comfort alternative. |
| `distance_to_school` | `Float64` | Prepared home-to-school distance in the configured distance units. |
| `distance_to_work` | `Float64` | Prepared home-to-work distance in the configured distance units. |
| `external_workplace_zone_id` | `identifier` | Assigned external workplace zone identifier. |
| `finalweight` | `Float64` | Person expansion weight from the configured person weight, inherited household weight, or 1.0 fallback. |
| `free_parking_at_work` | `Boolean-like or category` | Free-workplace-parking eligibility or modeled alternative. |
| `has_license` | `Boolean-like` | Whether the person holds a driver's license. |
| `home_zone_id` | `identifier` | Prepared home-zone identifier. |
| `household_id` | `Int64` | Canonical household identifier for the person. |
| `is_external_worker` | `Boolean-like` | Whether the person's assigned workplace is external to the modeled area. |
| `is_student` | `Boolean-like` | Whether the person is classified as a student. |
| `is_worker` | `String` | Whether the person is classified as a worker. |
| `person_id` | `Int64` | Canonical person identifier. |
| `person_type` | `source-compatible category` | ActivitySim person-type code. |
| `school_zone_id` | `identifier` | Assigned school-zone identifier. |
| `student_type` | `String` | Prepared school or enrollment market segment. |
| `telecommute_frequency` | `category` | Modeled telecommute-frequency alternative. |
| `transit_pass_ownership` | `Boolean-like` | Whether the person owns a transit pass. |
| `transit_pass_subsidy` | `category` | Modeled transit-pass-subsidy alternative. |
| `work_from_home` | `String` | Whether the worker has a home workplace. |
| `workplace_zone_id` | `identifier` | Assigned internal workplace-zone identifier. |
| `is_university` | `Boolean-like source value` | Prepared university-student indicator selected from the configured source alias. |
| `adult` | `String` | Prepared adult-status value used when deriving household auto-sufficiency inputs. |
| `mandatory_tour_frequency` | `String` | Mandatory-tour-frequency choice used directly by summaries when available. |
| `imf_choice` | `integer` | Legacy numeric mandatory-tour-frequency code derived from named ActivitySim alternatives. |
| `num_joint_tours` | `Int32` | Number of unique joint tours linked to the person through the joint-participant table. |
| `home_taz` | `source-compatible identifier` | TAZ corresponding to the person's home zone. |
| `work_taz` | `source-compatible identifier` | TAZ corresponding to the person's internal workplace zone. |
| `school_taz` | `source-compatible identifier` | TAZ corresponding to the person's school zone. |
| `HGEO` | `String` | Legacy configured home-geography label. |
| `WGEO` | `String` | Legacy configured workplace-geography label. |
| `home_geo__<name>` | `String` | Home-geography identifier for each configured named geography aggregation. |
| `work_geo__<name>` | `String` | Workplace-geography identifier for each configured named geography aggregation. |
| `school_geo__<name>` | `String` | School-geography identifier for each configured named geography aggregation. |

### `day` Prepared Table

_Processor runtime name: `day`._

**Information and analytical use.** Optional person-day or household-day records retained from multi-day model or survey output. Use this table for daily activity-pattern and frequency analysis where a person can contribute more than one observed day. An empty sentinel is written when no day table is available.

Retained source fields keep their source meaning and generally keep their source type.

| Field | Type | Description |
|---|---|---|
| `day_id` | `Int64` | Canonical day-record identifier when supplied. |
| `household_id` | `Int64` | Household identifier for the observed day when supplied. |
| `person_id` | `Int64` | Person identifier for the observed day when supplied. |
| `person_type` | `String` | Person type retained from the source or joined from the prepared person table. |
| `travel_date` | `String` | Source travel-date label when available. |
| `day_num` | `Int32` | Sequential day number within the person's or household's observation period. |
| `travel_dow` | `Int32` | Source day-of-week code when available. |
| `daily_activity_pattern` | `String` | Daily activity-pattern alternative, such as mandatory, nonmandatory, or home. |
| `day_weight` | `source-compatible number` | Configured source day weight retained for provenance when available. |
| `finalweight` | `Float64` | Day expansion weight from day, person, or household weights, with a 1.0 fallback. |

### `tours` Prepared Table

_Processor runtime name: `tours`._

**Information and analytical use.** One row per source tour representation. This core table preserves ActivitySim tour choices and adds standardized purpose, household context, stop counts, joint-party size, distance, time-period, and geography fields. Use it for tour frequency, mode, destination, scheduling, stop-pattern, joint-travel, and vehicle-allocation analysis. Some ActivitySim outputs repeat joint tours by participant; summary descriptions state when those rows are fractionally adjusted. The cache file is always present.

Retained source fields keep their source meaning and generally keep their source type.

| Field | Type | Description |
|---|---|---|
| `AUTOSUFF` | `Int32` | Prepared household auto-sufficiency category for the tour. |
| `NUMBER_HH` | `Int32` | Joint-party size from participant rows, number_of_participants, an existing NUMBER_HH value, or a fallback of one. |
| `SKIMDIST` | `Float64` | Prepared tour distance in the configured skim distance units. |
| `atwork_subtour_frequency` | `category` | Modeled at-work subtour-frequency alternative. |
| `destination` | `identifier` | Tour destination-zone identifier. |
| `finalweight` | `Float64` | Tour expansion weight inherited from trips, persons, households, or a 1.0 fallback according to available configured weights. |
| `household_id` | `Int64` | Canonical household identifier associated with the tour. |
| `is_external_tour` | `Boolean-like` | Whether the tour destination is external to the modeled area. |
| `num_escortees` | `Int64` | Number of students escorted on the tour. |
| `num_ib_stops` | `Int32` | Number of inbound intermediate stops parsed from stop_frequency. |
| `num_ob_stops` | `Int32` | Number of outbound intermediate stops parsed from stop_frequency. |
| `num_tot_stops` | `Int32` | Total intermediate stops on the tour. |
| `person_id` | `Int64` | Canonical person identifier associated with an individual tour. |
| `school_esc_inbound` | `String` | Inbound school-escort alternative or status. |
| `school_esc_outbound` | `String` | Outbound school-escort alternative or status. |
| `tour_category` | `String` | Tour category such as mandatory, nonmandatory, joint, or at-work. |
| `tour_id` | `Int64` | Canonical tour identifier. |
| `tour_mode` | `String` | Main mode selected for the tour. |
| `tour_purpose` | `String` | Primary purpose of the tour. |
| `vehicle_occup_1` | `vehicle-type code` | Vehicle type allocated to single-occupant auto tours. |
| `vehicle_occup_2` | `vehicle-type code` | Vehicle type allocated to two-occupant auto tours. |
| `vehicle_occup_3.5` | `vehicle-type code` | Vehicle type allocated to auto tours with three or more occupants. |
| `person_type` | `source-compatible category` | Person type copied from a configured tour-table alias when present. |
| `summary_tour_purpose` | `String` | Purpose normalized to the configured summary-purpose categories. |
| `origin` | `source-compatible identifier` | Tour origin zone; home-based and at-work origins are repaired from household or parent-tour context when possible. |
| `start_hour` | `Int32` | Tour start period, using the source period system or the survey adapter's 48-period conversion. |
| `end_hour` | `Int32` | Tour end period in the same period system as start_hour. |
| `start_period` | `String` | Configured named network period corresponding to the tour start period. |
| `end_period` | `String` | Configured named network period corresponding to the tour end period. |
| `first_inbound_trip_depart` | `Int32` | Departure period of the first inbound trip on the tour when it can be derived. |
| `first_inbound_trip_period` | `String` | Named network period of the first inbound trip. |
| `tourdur` | `Int32` | Inclusive tour duration, end_hour minus start_hour plus one, clipped to 1 through 48 periods. |
| `stop_frequency` | `source-compatible category` | ActivitySim stop-frequency choice retained from the configured source field. |
| `composition` | `String` | Joint-party composition retained from the source or derived as adults, children, or mixed from participant attributes. |
| `income_segment` | `Int64` | Household income segment copied to the tour when available. |
| `o_maz` | `Int64` | Tour-origin MAZ copied from origin when MAZ processing is enabled. |
| `d_maz` | `Int64` | Tour-destination MAZ copied from destination when MAZ processing is enabled. |
| `OTAZ` | `Int32` | Origin TAZ copied or looked up from the origin MAZ. |
| `DTAZ` | `Int32` | Destination TAZ copied or looked up from the destination MAZ. |
| `pnr_zone_id` | `Int64` | Park-and-ride lot or zone selected for a drive-transit tour when supplied. |
| `pnr_taz` | `Int32` | TAZ corresponding to pnr_zone_id. |
| `origin_geo__<name>` | `String` | Origin-geography identifier for each configured named geography aggregation. |
| `destination_geo__<name>` | `String` | Destination-geography identifier for each configured named geography aggregation. |
| `tour_distance` | `Float64` | Supplied tour distance with missing values filled from SKIMDIST when both fields are available. |
| `vot_bin` | `String` | Configured value-of-time category used to select segmented skims. |
| `<configured skim output>` | `normally Float64` | Skimjoin result whose name, units, direction, and mode applicability are defined by the normalized skimjoin configuration. |

### `trips` Prepared Table

_Processor runtime name: `trips`._

**Information and analytical use.** One row per source trip representation. This core table preserves ActivitySim trip choices and adds parent-tour context, canonical endpoints, distances, periods, stop indicators, escort-event positions, geography, and weights. Use it for trip and stop rates, mode and purpose analysis, parking demand, time-of-day profiles, VMT, and travel-impedance analysis. Joint records may represent several travelers; summary descriptions state how participant expansion is applied. The cache file is always present.

Retained source fields keep their source meaning and generally keep their source type.

| Field | Type | Description |
|---|---|---|
| `escort_event_role` | `String` | Adult escort-event role assigned to the trip. |
| `escort_stops_after_event` | `Int32` | Stops occurring after the associated escort event. |
| `escort_stops_before_event` | `Int32` | Stops occurring before the associated escort event. |
| `finalweight` | `Float64` | Trip expansion weight from the configured trip weight, inherited person or household weight, or 1.0 fallback. |
| `num_participants` | `Int32` | Number of travelers represented by a joint trip record. |
| `od_dist` | `Float64` | Origin-to-destination trip distance from the configured distance skim or supported survey distance, in source units. |
| `out_dir_dist` | `Float64` | Additional distance caused by visiting the stop rather than traveling directly to the half-tour endpoint. |
| `parking_zone` | `Int64` | Zone where the auto trip parks. |
| `person_id` | `Int64` | Canonical person identifier associated with the trip. |
| `stops` | `Int32` | Intermediate-stop indicator, 1 before the last trip on a half-tour and 0 for the final leg. |
| `tour_id` | `Int64` | Canonical identifier of the parent tour. |
| `tour_mode` | `String` | Main mode of the parent tour. |
| `tour_purpose` | `String` | Primary purpose of the parent tour. |
| `trip_mode` | `String` | Mode used for the trip leg. |
| `trip_purpose` | `String` | Destination purpose of the trip leg. |
| `household_id` | `Int64` | Canonical household identifier associated with the trip. |
| `trip_id` | `Int64` | Canonical trip identifier. |
| `summary_tour_purpose` | `String` | Parent-tour purpose normalized to configured summary-purpose categories. |
| `tour_category` | `String` | Category of the parent tour, filled from the prepared tour table when necessary. |
| `origin` | `source-compatible identifier` | Trip origin zone; tour-boundary endpoints are repaired from the prepared tour origin when possible. |
| `destination` | `source-compatible identifier` | Trip destination zone; tour-boundary endpoints are repaired from the prepared tour origin when possible. |
| `outbound` | `Boolean-like source value` | Direction flag indicating the outbound half of the tour. |
| `inbound` | `Int32` | Derived inverse direction indicator, 1 for inbound records and 0 otherwise. |
| `trip_num` | `Int32` | Sequential trip number within a tour direction. |
| `max_trip_num` | `integer` | Largest trip number on the same tour half, used to identify intermediate stops. |
| `depart_hour` | `Int32` | Trip departure period; defaults to one only when no departure field is available. |
| `trip_period` | `String` | Configured named network period corresponding to the trip departure period. |
| `income_segment` | `Int64` | Household income segment copied to the trip when available. |
| `AUTOSUFF` | `Int32` | Parent-household auto-sufficiency category under the configured comparison basis. |
| `o_maz` | `Int64` | Trip-origin MAZ copied from origin when MAZ processing is enabled. |
| `d_maz` | `Int64` | Trip-destination MAZ copied from destination when MAZ processing is enabled. |
| `OTAZ` | `Int32` | Origin TAZ copied or looked up from the origin MAZ. |
| `DTAZ` | `Int32` | Destination TAZ copied or looked up from the destination MAZ. |
| `pnr_zone_id` | `Int64` | Park-and-ride zone inherited from the parent tour when supplied. |
| `pnr_taz` | `Int32` | TAZ corresponding to pnr_zone_id. |
| `origin_parking_zone` | `Int64` | Parking zone associated with the trip origin when supplied. |
| `origin_geo__<name>` | `String` | Origin-geography identifier for each configured named geography aggregation. |
| `destination_geo__<name>` | `String` | Destination-geography identifier for each configured named geography aggregation. |
| `prepared_non_motorized_distance` | `Float64` | Optional walk/bicycle/e-bike distance from the configured non-motorized skim source. |
| `escort_event_trip_num` | `Int32` | Trip number at which the matched escort event occurs. |
| `escort_event_match_status` | `String` | Whether escort-event matching was matched, ambiguous, or unmatched. |
| `vot_bin` | `String` | Configured value-of-time category used to select segmented skims. |
| `<configured skim output>` | `normally Float64` | Skimjoin result whose name, units, lookup direction, and mode applicability are defined by the normalized skimjoin configuration. |

### `vehicles` Prepared Table

_Processor runtime name: `vehicles`._

**Information and analytical use.** Optional one-row-per-household-vehicle table. It preserves ActivitySim vehicle records and decodes the standard compound vehicle type into body, age, and fuel attributes. Use it for fleet composition, vehicle technology, energy, emissions, and vehicle-allocation analysis. An empty sentinel is written when no vehicle table is available.

Retained source fields keep their source meaning and generally keep their source type.

| Field | Type | Description |
|---|---|---|
| `body_type` | `String` | Vehicle body-style category parsed from vehicle_type. |
| `finalweight` | `Float64` | Vehicle expansion weight inherited from the owning household or set to 1.0 when unavailable. |
| `fuel_type` | `String` | Vehicle fuel or powertrain category parsed from vehicle_type. |
| `vehicle_age` | `Int64` | Vehicle age in years parsed from vehicle_type. |
| `household_id` | `Int64` | Canonical identifier of the household that owns the vehicle. |
| `vehicle_id` | `Int64` | Canonical vehicle identifier. |
| `vehicle_num` | `Int32` | Sequential vehicle number within the household. |
| `vehicle_type` | `String` | Source vehicle-type choice, commonly encoded as body type, age, and fuel type separated by underscores. |

### `joint_tour_participants` Prepared Table

_Processor runtime name: `joint_participants`._

**Information and analytical use.** Optional participation records linking people to fully joint tours. The usual grain is one person-tour participation, although additional source attributes are retained. Use it to determine joint-tour party size, composition, and person participation without treating a household tour as independent person tours. An empty sentinel is written when the source table is unavailable.

Retained source fields keep their source meaning and generally keep their source type.

| Field | Type | Description |
|---|---|---|
| `person_id` | `Int64` | Canonical identifier of a person participating in a joint tour. |
| `tour_id` | `Int64` | Canonical identifier of the joint tour. |

### `land_use` Prepared Table

_Processor runtime name: `land_use`._

**Information and analytical use.** Optional zone and land-use attribute table, normally one row per source MAZ or TAZ before any enrollment overlays are added. It supports zone translation, named geography joins, employment and enrollment controls, parking capacity, and destination-based analysis. When configured student markets are expanded, additional zone/student-type rows carry enrollment counts. An empty sentinel is written when land use is unavailable.

Retained source fields keep their source meaning and generally keep their source type.

| Field | Type | Description |
|---|---|---|
| `MAZ` | `Int64` | Canonical micro-analysis-zone identifier. |
| `employment_count` | `Float64` | Employment opportunities associated with the zone. |
| `enrollment_count` | `Float64` | Enrollment opportunities associated with the zone and student type. |
| `student_type` | `String` | Student or enrollment market segment. |
| `TAZ` | `Int64` | Canonical transportation-analysis-zone identifier. |
| `EMPLOYMENT` | `Float64` | Canonical total employment copied from the configured land-use employment field. |
| `land_use_geo__<name>` | `String` | Geography identifier for each configured named land-use aggregation. |


## 2. Summary Output Tables

The processor calculates **87** summary contracts: **85** in the standard workflow and **2** optional skim ECDF tables. The same schemas apply to weighted, unweighted, and segmented cache variants.

Every summary table is saved as a CSV file named `<summary_table>.csv`.

### Population and Demographics

| Summary Table | Information and Analytical Use | Fields |
|---|---|---|
| `household_size_distribution` | Household totals by modeled household size. Use it to profile household composition, calculate size shares, and compare population-synthesis results across runs. | `household_size` (`Int64`): number of people in the household.<br>`household_count` (`Float64`): weighted households in that size category. |
| `person_type_distribution` | Person totals by ActivitySim person type, with a display label. Use it to compare demographic market segments and as a denominator for person-type travel rates. | `person_type` (`String`): stable person-type code.<br>`person_type_label` (`String`): configured readable label for the code.<br>`person_count` (`Float64`): weighted people of that type. |
| `population_totals` | One run-level control-total row for people, households, person-tours, person-trips, and person-stops. Joint tour and trip records use the sum of all matching participant person weights when available and valid party-size expansion only as a fallback; sentinel, missing, or nonpositive fallback counts resolve to one. Use it for reasonableness checks and top-level comparisons; the measures use their own table weights and are not additive to one another. | `person_count` (`Float64`): weighted persons.<br>`household_count` (`Float64`): weighted households.<br>`tour_count` (`Float64`): weighted person-tours; joint records are participant-expanded.<br>`trip_count` (`Float64`): weighted person-trips; joint records are participant-expanded.<br>`stop_count` (`Float64`): weighted person-trip records flagged as intermediate stops; joint records are participant-expanded. |

### Person Attributes and Long-Term Choices

| Summary Table | Information and Analytical Use | Fields |
|---|---|---|
| `license_holding_status_distribution` | Licensed and unlicensed people age 16 or older by person type, including an all-person-types rollup. Use it to assess access to driving and explain auto-mode availability. | `person_type` (`String`): person-type code or `all_person_types` rollup.<br>`license_holding_status` (`String`): `has_license` or `no_license`.<br>`person_type_label` (`String`): configured readable person-type label.<br>`person_count` (`Float64`): weighted people in the group. |
| `bicycle_comfort_level_distribution` | Bicycle comfort categories by person type, including an all-person-types rollup. Use it to understand the population assumed willing to use different bicycle facilities. | `person_type` (`String`): person-type code or rollup.<br>`bicycle_comfort_level` (`String`): prepared bicycle-comfort category.<br>`person_type_label` (`String`): configured readable person-type label.<br>`person_count` (`Float64`): weighted people in the group. |
| `transit_pass_ownership_by_person_type` | Transit-pass ownership status by person type, including an all-person-types rollup. Use it to evaluate transit market eligibility and pass-ownership model results. | `person_type` (`String`): person-type code or rollup.<br>`transit_pass_ownership_status` (`String`): `has_transit_pass` or `no_transit_pass`.<br>`person_type_label` (`String`): configured readable person-type label.<br>`person_count` (`Float64`): weighted people in the group. |
| `transit_subsidy_by_person_type` | Transit-pass subsidy alternatives for workers, by person type and with an all-person-types rollup. Use it to examine employer or institutional transit-benefit assumptions. | `person_type` (`String`): person-type code or rollup.<br>`transit_subsidy_status` (`String`): prepared subsidy alternative code.<br>`transit_subsidy_label` (`String`): configured readable subsidy label.<br>`person_type_label` (`String`): configured readable person-type label.<br>`person_count` (`Float64`): weighted eligible workers in the group. |
| `telecommute_frequency_distribution` | Non-work-from-home workers by telecommute-frequency category and home geography, plus an all-geographies rollup. Use it to analyze recurring telecommuting among workers who still have an external workplace. | `geography_type` (`String`): home-geography system or rollup.<br>`geography_id` (`String`): home-geography identifier or rollup value.<br>`telecommute_frequency` (`String`): prepared telecommute-frequency alternative.<br>`person_count` (`Float64`): weighted workers in the group. |

### Household Vehicles and Vehicle Characteristics

| Summary Table | Information and Analytical Use | Fields |
|---|---|---|
| `autonomous_vehicle_ownership_totals` | One run-level total of households modeled as owning an autonomous vehicle. Use it to report scenario penetration and compare AV-ownership assumptions. | `household_with_autonomous_vehicle_count` (`Float64`): weighted households with `av_ownership` true. |
| `auto_ownership_distribution` | Household totals jointly classified by household size and vehicle count; household sizes of five or more are grouped as `5+`. Use it to assess motorization and auto sufficiency. | `household_size` (`String`): household-size category, with `5+` as the terminal group.<br>`household_vehicle_count` (`Int64`): vehicles available to the household.<br>`household_count` (`Float64`): weighted households in the joint category. |
| `vehicle_age_distribution` | Household vehicles by age, with ages 20 and older grouped as `20+`. Use it for fleet turnover, emissions, and technology analyses. | `age` (`String`): vehicle age in years or `20+`.<br>`vehicle_count` (`Float64`): weighted vehicles in the age category. |
| `vehicle_fuel_type_distribution` | Household vehicles by prepared fuel or powertrain type. Use it for fleet composition, energy, and emissions analysis. | `fuel_type` (`String`): prepared vehicle fuel/powertrain category.<br>`vehicle_count` (`Float64`): weighted vehicles of that type. |
| `vehicle_body_type_distribution` | Household vehicles by prepared body type. Use it to characterize the light-duty fleet and support occupancy or emissions comparisons. | `body_type` (`String`): prepared vehicle body-style category.<br>`vehicle_count` (`Float64`): weighted vehicles of that type. |

### Long-Term Geography, Location, and Shadow Pricing

| Summary Table | Information and Analytical Use | Fields |
|---|---|---|
| `work_from_home_rate_by_geography` | All workers and work-from-home workers by home geography, plus a regional rollup. Divide the WFH count by the worker count to calculate the WFH rate and map its spatial pattern. | `geography_type` (`String`): home-geography system or rollup.<br>`geography_id` (`String`): home-geography identifier or rollup value.<br>`worker_count` (`Float64`): weighted workers living in the geography.<br>`work_from_home_worker_count` (`Float64`): weighted workers flagged as working from home. |
| `internal_external_worker_by_geography` | Internal and external workers by home geography, plus a regional rollup. Use it to understand external-worker incidence and its residential distribution. | `geography_type` (`String`): home-geography system or rollup.<br>`geography_id` (`String`): home-geography identifier or rollup value.<br>`internal_worker_count` (`Float64`): weighted workers with an internal workplace.<br>`external_worker_count` (`Float64`): weighted workers classified as external. |
| `external_worker_workplace_locations` | External workers by their external workplace geography, plus a regional rollup. Use it to analyze external commute orientation; the all-worker denominator is repeated to support share calculations. | `geography_type` (`String`): external-workplace geography system or rollup.<br>`geography_id` (`String`): external-workplace geography identifier or rollup value.<br>`external_worker_count` (`Float64`): weighted external workers assigned to that destination.<br>`all_worker_count` (`Float64`): weighted workers in the full run, repeated on every row. |
| `workplace_location_employment_comparison` | Land-use employment and modeled worker workplace choices aligned by workplace geography. Use it to compare attraction targets with assigned workers and diagnose location-choice balance. | `geography_type` (`String`): workplace-geography system.<br>`geography_id` (`String`): workplace-geography identifier.<br>`employment_count` (`Float64`): employment opportunities from land use.<br>`worker_count` (`Float64`): weighted workers assigned to the geography. |
| `commuting_flows` | Worker flows from home geography to workplace geography at matching configured geography levels, plus a regional total. Use it as an origin-destination matrix for commute sheds, self-containment, and interjurisdictional flows. | `origin_geography_type` (`String`): home-geography system.<br>`origin_geography_id` (`String`): home-geography identifier.<br>`destination_geography_type` (`String`): workplace-geography system.<br>`destination_geography_id` (`String`): workplace-geography identifier.<br>`commuter_count` (`Float64`): weighted workers in the OD pair. |
| `school_location_enrollment_comparison` | Land-use enrollment and modeled student school locations aligned by geography and student type. Use it to compare school-location targets with assigned students. | `geography_type` (`String`): school-geography system.<br>`geography_id` (`String`): school-geography identifier.<br>`student_type` (`String`): prepared school/enrollment market segment.<br>`enrollment_count` (`Float64`): target enrollment from land use.<br>`student_count` (`Float64`): weighted students assigned to the geography and type. |
| `workplace_shadow_pricing_residuals` | Zone-level workplace target-versus-modeled residuals. Use positive residuals to find over-assigned workplace geographies and negative residuals to find under-assigned ones. | `geography_type` (`String`): workplace-geography system.<br>`geography_id` (`String`): workplace-geography identifier.<br>`target_count` (`Float64`): land-use employment target.<br>`modeled_count` (`Float64`): weighted assigned workers.<br>`residual_count` (`Float64`): `modeled_count - target_count`.<br>`absolute_residual_count` (`Float64`): absolute residual magnitude.<br>`percent_error` (`Float64`): residual divided by target, times 100; null when target is zero. |
| `school_shadow_pricing_residuals` | Zone-level school target-versus-modeled residuals by student type. Use it to diagnose school-location shadow-pricing convergence and segment-specific imbalance. | `geography_type` (`String`): school-geography system.<br>`geography_id` (`String`): school-geography identifier.<br>`student_type` (`String`): school/enrollment market segment.<br>`target_count` (`Float64`): land-use enrollment target.<br>`modeled_count` (`Float64`): weighted assigned students.<br>`residual_count` (`Float64`): modeled minus target.<br>`absolute_residual_count` (`Float64`): absolute residual magnitude.<br>`percent_error` (`Float64`): residual divided by target, times 100; null for zero targets. |
| `workplace_shadow_pricing_residual_histogram` | Distribution of workplace residuals by geography system. Use it to assess convergence across all zones without inspecting each zone separately; zero residuals receive their own zero-width bin. | `geography_type` (`String`): workplace-geography system.<br>`bin_start` (`Float64`): inclusive lower residual bound.<br>`bin_end` (`Float64`): upper residual bound; both bounds are zero for the exact-zero bin.<br>`geography_count` (`Float64`): number of geography records in the bin. |
| `school_shadow_pricing_residual_histogram` | Distribution of school residuals by geography system and student type. Use it to compare convergence across student markets. | `geography_type` (`String`): school-geography system.<br>`student_type` (`String`): school/enrollment market segment.<br>`bin_start` (`Float64`): lower residual bound.<br>`bin_end` (`Float64`): upper residual bound, or zero for the exact-zero bin.<br>`geography_count` (`Float64`): number of geography/student-type records in the bin. |
| `park_and_ride_location_residuals` | Modeled park-and-ride tour use compared with lot capacity by lot geography. Use it to identify over-capacity or underused PNR locations. | `geography_type` (`String`): PNR-lot geography system.<br>`geography_id` (`String`): PNR-lot geography identifier.<br>`pnr_tour_count` (`Float64`): weighted PNR tours assigned to the location.<br>`pnr_lot_capacity` (`Float64`): supplied lot capacity target.<br>`residual_count` (`Float64`): tours minus capacity.<br>`absolute_residual_count` (`Float64`): absolute residual magnitude.<br>`percent_error` (`Float64`): residual divided by capacity, times 100; null for zero capacity. |
| `park_and_ride_location_residual_histogram` | Distribution of PNR use-minus-capacity residuals by geography system. Use it for systemwide capacity-fit assessment. | `geography_type` (`String`): PNR-lot geography system.<br>`bin_start` (`Float64`): lower residual bound.<br>`bin_end` (`Float64`): upper residual bound, or zero for the exact-zero bin.<br>`geography_count` (`Float64`): number of PNR geography records in the bin. |
| `free_parking_eligibility_by_workplace_geography` | Workers with and without free workplace parking by workplace geography. Use it to analyze parking-cost exposure and its effect on commute mode choice. | `geography_type` (`String`): workplace-geography system.<br>`geography_id` (`String`): workplace-geography identifier.<br>`workers_without_free_parking_count` (`Float64`): weighted workers not eligible for free parking.<br>`workers_with_free_parking_count` (`Float64`): weighted workers eligible for free parking. |

### Long-Term Location Distance

| Summary Table | Information and Analytical Use | Fields |
|---|---|---|
| `work_location_distance_distribution_by_geography` | Internal, non-work-from-home workers with valid workplace locations by home geography and home-to-work distance. Use it for commute-length distributions and spatial comparisons. | `distance_bin` (`String`): exact-zero, positive-sub-mile, whole-mile lower-bound, or `51+` category.<br>`geography_type` (`String`): home-geography system or rollup.<br>`geography_id` (`String`): home-geography identifier or rollup value.<br>`person_count` (`Float64`): weighted workers in the bin. |
| `university_location_distance_distribution_by_geography` | University students, identified by person type 3, by home geography and home-to-school distance. Use it to examine university travel markets and campus catchments. | `distance_bin` (`String`): exact-zero, positive-sub-mile, whole-mile lower-bound, or `51+` category.<br>`geography_type` (`String`): home-geography system or rollup.<br>`geography_id` (`String`): home-geography identifier or rollup value.<br>`person_count` (`Float64`): weighted university students in the bin. |
| `school_location_distance_distribution_by_geography` | School students, identified by person types 6 and higher, by home geography and home-to-school distance. Use it for K--12 travel-distance and school-catchment analysis. | `distance_bin` (`String`): exact-zero, positive-sub-mile, whole-mile lower-bound, or `51+` category.<br>`geography_type` (`String`): home-geography system or rollup.<br>`geography_id` (`String`): home-geography identifier or rollup value.<br>`person_count` (`Float64`): weighted school students in the bin. |

### Daily Activity Patterns and Travel Rates

| Summary Table | Information and Analytical Use | Fields |
|---|---|---|
| `daily_activity_pattern_by_person_type` | Daily activity pattern alternatives by person type, using each person's non-null person-table CDAP value and falling back only for remaining persons to all observed day rows with day weights when available, including an all-person-types rollup. No day rows are deduplicated. Use it to compare mandatory, nonmandatory, and home-stay behavior. | `person_type` (`String`): person-type code or rollup.<br>`daily_activity_pattern` (`String`): prepared CDAP/activity-pattern category.<br>`person_count` (`Float64`): weighted people or observed person-days in the pattern. |
| `mandatory_tour_frequency_by_person_type` | Positive mandatory-tour-frequency choice by person type, using each person's non-null prepared choice and falling back only for remaining persons to choices derived from work and school tours on every person-day, with day weights when available, plus an all-person-types rollup. Use it to analyze how many mandatory tours travelers make. The table excludes records with a choice of zero. | `person_type` (`String`): person-type code or rollup.<br>`mandatory_tour_frequency` (`Int32`): prepared or tour-derived positive mandatory-tour frequency alternative.<br>`person_count` (`Float64`): weighted people or person-days choosing that frequency. |
| `nonmandatory_tour_frequency_by_person_type` | Count of individual nonmandatory tours plus joint-tour participation, grouped as 0, 1, 2, or 3+, by person type and for all types. Genuinely multi-day inputs are classified per person-day only when every tour and participant has a safe day key; otherwise the one-day/person fallback is retained rather than dropping records or guessing keys. Use it to compare discretionary travel propensity. | `person_type` (`String`): person-type code or rollup.<br>`nonmandatory_tour_frequency` (`String`): combined nonmandatory-tour category `0`, `1`, `2`, or `3+`.<br>`person_count` (`Float64`): weighted people or person-days in the category. |
| `tour_rates_by_person_type_and_tour_purpose` | Person-tours per person-day by person type and tour purpose under the selected weighting mode, plus all-person-types rates. Every eligible source row contributes and at-work subtours are excluded. Joint tours are attributed using each known participant's person weight or expanded by a valid party size when participant records are unavailable. Use it to compare tour-generation rates while controlling for population composition. | `person_type` (`String`): person-type code or rollup.<br>`tour_purpose` (`String`): prepared tour-purpose category.<br>`tour_rate` (`Float64`): sum of eligible person-tour weights, divided by summed person or person-day weights for that person type. |
| `trip_rates_by_person_type_and_trip_purpose` | Person-trips per person-day by person type and trip purpose under the selected weighting mode, plus all-person-types rates. Every eligible source row contributes. Joint trips are attributed using each known participant's person weight or expanded by a valid party size when participant records are unavailable. Use it to compare trip-generation rates across demographic markets. | `person_type` (`String`): person-type code or rollup.<br>`trip_purpose` (`String`): destination purpose of the trip.<br>`trip_rate` (`Float64`): sum of eligible person-trip weights, divided by summed person or person-day weights for that person type. |

### School Escorting

| Summary Table | Information and Analytical Use | Fields |
|---|---|---|
| `escorted_tour_totals` | One run-level total of adult-side tours with an outbound or inbound school-escort condition. Use it as the top-level escorted-tour control total. | `tour_count` (`Float64`): weighted distinct eligible tours with at least one escorted direction. |
| `school_escorted_tours_by_escort_type_and_direction` | Adult-side escorted tours by escort arrangement and direction, with an `all_directions` incidence rollup. Use it to compare ride-share and pure-escort patterns. | `escort_type` (`String`): prepared escort arrangement label.<br>`direction` (`String`): `outbound`, `inbound`, or `all_directions`.<br>`tour_count` (`Float64`): weighted escorted-tour incidences. |
| `adult_escorted_tour_purposes_by_direction` | Purposes of the adult tours that do school escorting, by direction and with an all-directions incidence rollup. Use it to see how escorting connects with work or other adult activities. | `tour_purpose` (`String`): adult tour's primary purpose.<br>`direction` (`String`): escorted half or `all_directions`.<br>`tour_count` (`Float64`): weighted escorted-tour incidences. |
| `adult_escorted_tours_by_person_type_and_direction` | Adult-side escorted tours by the adult traveler's person type and escorted direction. Use it to identify who performs school escorting. | `person_type` (`String`): adult traveler person-type code.<br>`direction` (`String`): `outbound`, `inbound`, or `both`.<br>`tour_count` (`Float64`): weighted tours meeting that directional condition. |
| `student_school_escort_status_by_direction` | Student school tours classified by normalized escort type for each direction and for tours escorted both ways. Use it to measure the student-side escort experience. | `direction` (`String`): `outbound`, `inbound`, or `both`.<br>`escort_type` (`String`): normalized escort arrangement, including unescorted alternatives where present.<br>`tour_count` (`Float64`): weighted student school tours in the group. |
| `student_households_by_student_count` | Households by the number of school-age/student household members recognized by the escort logic. Use it as a denominator for household escort participation. | `student_count` (`Int64`): students in the household.<br>`household_count` (`Float64`): weighted households with that count. |
| `households_with_school_escorting_by_student_count_and_direction` | Unique households with at least one escorted student school tour, by number of students and directional condition. Use it to calculate escort-participation rates by household composition. | `student_count` (`Int64`): students in the household.<br>`direction` (`String`): `outbound`, `inbound`, or `both`.<br>`household_count` (`Float64`): weighted unique households meeting the condition. |
| `schoolkids_per_escorted_tour_by_student_count_and_direction` | Average number of escorted children on adult-side escorted tours by household student count and direction. Use it to analyze escorting efficiency and child grouping. | `student_count` (`Int64`): students in the adult traveler's household.<br>`direction` (`String`): `outbound`, `inbound`, or `both`.<br>`avg_schoolkids_per_tour` (`Float64`): weighted mean number of escortees per eligible tour.<br>`tour_count` (`Float64`): weighted eligible tours used as the mean denominator. |
| `adult_escorted_tour_distance_distribution_by_direction` | Adult-side escorted tours by lower-bound tour-distance bin and directional escort condition. Use it to compare the length of outbound-only, inbound-only, and both-way escort tours. | `distance_bin` (`String`): exact `0`, positive sub-mile `>0-<1`, whole-mile lower bound, or `40+`.<br>`direction` (`String`): `outbound`, `inbound`, or `both`.<br>`tour_count` (`Float64`): weighted eligible tours in the bin. |
| `adult_escorted_trip_distance_distribution_by_direction` | Trips on adult tours marked as escorted, by outbound or inbound half and lower-bound trip-distance bin. Use it to examine the trip-leg distance for escorting. | `distance_bin` (`String`): exact `0`, positive sub-mile `>0-<1`, whole-mile lower bound, or `40+`.<br>`direction` (`String`): `outbound`, `inbound`, or `both` condition.<br>`trip_count` (`Float64`): weighted eligible trips in the bin. |
| `adult_escort_event_stop_distribution` | Intermediate stops before and after school drop-off or pickup on adult tours marked as escorted. Use it to analyze trip chains around escort events. | `segment` (`String`): one of `outbound_before_dropoff`, `outbound_after_dropoff`, `inbound_before_pickup`, or `inbound_after_pickup`.<br>`stop_count` (`Int32`): prepared count of stops in that segment.<br>`tour_count` (`Float64`): weighted escort-event records with that stop count. |
| `adult_escort_trip_stop_frequency` | Adult-side escorted tours jointly classified by purpose and outbound, inbound, and total stop counts. Use it to compare stop-making complexity on escort tours. | `tour_purpose` (`String`): adult tour purpose.<br>`outbound_stop_count` (`Int32`): outbound stops capped at 3.<br>`inbound_stop_count` (`Int32`): inbound stops capped at 3.<br>`total_stop_count` (`Int32`): total stops capped at 6.<br>`tour_count` (`Float64`): weighted escorted tours in the combination. |

### Joint Travel

| Summary Table | Information and Analytical Use | Fields |
|---|---|---|
| `jtf_distribution` | Household observations across the legacy 21 joint-tour-frequency labels, selected by minimum counts in five fixed purpose slots covering shopping, maintenance, eating out, visiting/social, and other discretionary. Purposes outside those slots do not affect the label, and counts above a label's threshold are not rejected, so the labels are not strict total-tour counts. When the day table shows a genuinely multi-day diary and tours contain `day_num`, observations use `(household_id, day_num)`; null or unmatched tour days do not contribute. Without the tour day column, the result is empty rather than pooled into a weekly choice. On a one-day input, the declaration does not require tours, so an unavailable tour table can instead classify every household as `No Joint Tours`; verify tour availability before using that result. Use it to validate compatible joint-tour generation inputs. | `jtf_code` (`Int32`): integer alternative 1--21.<br>`jtf_label` (`String`): readable minimum-frequency/purpose-combination label.<br>`household_count` (`Float64`): sum of `hh.finalweight` across households or household-day observations assigned to the alternative. |
| `joint_tours_by_household_size` | All household observations and observations making at least one joint tour by household size. A genuinely multi-day diary uses household-days when tours contain `day_num`; null or unmatched tour days do not contribute, and a missing tour day column produces an empty result rather than pooling days. Valid shared joint-tour or tour IDs collapse repeated records; records without either valid ID remain distinct. Use the two counts to calculate joint-tour participation rates. | `household_size` (`Int32`): number of household members.<br>`household_count` (`Float64`): sum of `hh.finalweight` across households or household-day observations of that size.<br>`joint_tour_hh_count` (`Float64`): sum of `hh.finalweight` for those observations with a joint tour. |
| `joint_tour_party_size_distribution` | Household joint tours by valid participant count, with parties of five or more stored in bin 5. Verified survey participant-row groups retain every row at a fractional representation weight that sums to one household tour; ordinary model joint-tour rows retain full weight. Sentinel values of 995 or greater, missing values, and nonpositive values are excluded. Use it to assess joint-tour occupancy. | `party_size` (`Int32`): household participants; value 5 represents `5+`.<br>`joint_tour_count` (`Float64`): weighted joint tours in the party-size bin. |
| `joint_tour_composition_distribution` | Household joint tours by prepared party-composition category. Verified participant-row representations retain every row fractionally so each complete group contributes one household tour. Use it to compare adult-only, child-inclusive, and other modeled compositions. | `tour_composition` (`String`): prepared joint-party composition.<br>`joint_tour_count` (`Float64`): weighted joint tours in the category. |
| `joint_tour_composition_by_party_size` | Household joint tours jointly classified by party composition and exact valid participant count. Verified participant-row representations retain every row fractionally so each complete group contributes one household tour. Sentinel values of 995 or greater, missing values, and nonpositive values are excluded. Use it to study how household makeup and group size interact. | `tour_composition` (`String`): prepared party-composition category.<br>`party_size` (`Int64`): number of tour participants.<br>`joint_tour_count` (`Float64`): weighted joint tours in the combination. |
| `person_jtp_by_household_size` | All person observations and observations participating in one or more joint tours by household size. When a multi-day input has person-day records and each joint-tour identity maps to one day, the observations are person-days and participation comes from linked joint participants. A missing or ambiguous tour-day mapping produces an empty result; if the day table lacks household, person, or day fields, the person-level fallback remains. The multi-day path's participant-table limitations are documented in chapter 25. Use the two counts to calculate participation rates. | `household_size` (`Int64`): size of the person's household.<br>`joint_tour_person_count` (`Float64`): sum of the applicable person or day weight for people or person-days participating in a joint tour.<br>`total_person_count` (`Float64`): sum of the applicable person or day weight for people or person-days in households of that size. |
| `household_jtp_by_household_size_and_jtf` | For household observations of size two or more, weighted percentage distribution across 0, 1, and 2+ joint-tour identities within each household size. A genuinely multi-day diary uses household-days when tours contain `day_num`; null or unmatched tour days do not contribute, and a missing tour day column produces an empty result rather than pooling days. Valid shared joint-tour or tour IDs collapse repeated records; records without either valid ID remain distinct. Use it to compare joint-tour propensity independent of household-size totals across compatible runs. | `jtf` (`String`): joint-tour count category `0`, `1`, or `2+`.<br>`household_size` (`String`): household size as a category.<br>`household_percent` (`Float64`): percent of summed `hh.finalweight` for household observations of that size in the JTF category. |

### Basic Tour Distributions

| Summary Table | Information and Analytical Use | Fields |
|---|---|---|
| `tour_category_distribution` | Household-tour-unit counts by ActivitySim category, such as mandatory, nonmandatory, at-work, or joint. Verified participant-row representations of one joint tour are retained fractionally rather than collapsed. Use it for high-level tour-system composition. | `tour_category` (`String`): prepared tour category.<br>`tour_count` (`Float64`): weighted tours in the category. |
| `tour_purpose_distribution` | Household-tour-unit counts by configured summary purpose. Verified participant-row representations of one joint tour are retained fractionally rather than collapsed. Use it to compare the volume and share of work, school, escort, shopping, and other travel. | `tour_purpose` (`String`): canonical summary tour purpose.<br>`tour_count` (`Float64`): weighted tours for that purpose. |

### Vehicles Allocated to Tours

| Summary Table | Information and Analytical Use | Fields |
|---|---|---|
| `allocated_vehicle_age_by_occupancy` | Allocated vehicle ages by occupancy condition. Use it to analyze how fleet age is associated with single- and shared-occupant travel. | `age` (`String`): decoded vehicle age, with `20+` terminal.<br>`occupancy` (`String`): allocation condition `1`, `2`, or `3+`.<br>`vehicle_count` (`Float64`): weighted tour allocation incidences. |
| `allocated_vehicle_fuel_type_by_occupancy` | Allocated vehicle fuel/powertrain type by occupancy condition. Use it for energy or emissions segmentation of auto travel. | `fuel_type` (`String`): decoded fuel/powertrain category.<br>`occupancy` (`String`): allocation condition `1`, `2`, or `3+`.<br>`vehicle_count` (`Float64`): weighted tour allocation incidences. |
| `allocated_vehicle_body_type_by_occupancy` | Allocated vehicle body type by occupancy condition. Use it to relate party size to the modeled vehicle used. | `body_type` (`String`): decoded vehicle body-style category.<br>`occupancy` (`String`): allocation condition `1`, `2`, or `3+`.<br>`vehicle_count` (`Float64`): weighted tour allocation incidences. |

### Tour Mode, Stops, Time, and Distance

| Summary Table | Information and Analytical Use | Fields |
|---|---|---|
| `tour_mode_by_tour_purpose_and_auto_sufficiency` | Person-tour mode counts by purpose and household auto sufficiency, with all-purpose rows. Joint records use the sum of all matching participant person weights when available and valid party-size expansion only as a fallback; sentinel, missing, or nonpositive fallback sizes resolve to one. Use it to compare mode choice across vehicle-availability markets. | `tour_mode` (`String`): prepared tour mode.<br>`tour_purpose` (`String`): tour purpose or `all_tour_purposes`.<br>`tour_count_zero_auto` (`Float64`): weighted person-tours from zero-auto households.<br>`tour_count_auto_deficient` (`Float64`): weighted person-tours from households with fewer autos than workers.<br>`tour_count_auto_sufficient` (`Float64`): weighted person-tours from auto-sufficient households.<br>`tour_count_all_households` (`Float64`): sum of the three auto-sufficiency counts. |
| `tour_stop_frequency_by_tour_purpose` | Household-tour-unit counts jointly classified by purpose and outbound, inbound, and total intermediate-stop counts. Verified participant-row joint-tour groups retain every row at fractional weight summing to one tour. Use it to measure tour complexity and stop-generation patterns. | `tour_purpose` (`String`): canonical tour purpose.<br>`outbound_stop_count` (`Int32`): outbound stops capped at 3.<br>`inbound_stop_count` (`Int32`): inbound stops capped at 3.<br>`total_stop_count` (`Int32`): total stops capped at 6.<br>`tour_count` (`Float64`): weighted tours in the combination. |
| `atwork_subtour_frequency_distribution` | Mandatory work tours by their at-work-subtour-frequency alternative. Use it to validate subtour generation from the workplace. | `atwork_subtour_frequency_category` (`String`): prepared at-work subtour-frequency category.<br>`atwork_subtour_count` (`Float64`): weighted parent work tours choosing the category. |
| `tour_time_of_day_by_tour_purpose` | Dense household-tour-unit departure, arrival, and duration profiles by tour purpose plus all-purpose totals. Every eligible row is retained; verified participant-row representations of one joint tour contribute fractionally so their combined weight equals one tour. Use it to compare scheduling and duration distributions. | `time_bin` (`Int32`): ActivitySim period index.<br>`tour_purpose` (`String`): tour purpose or `all_tour_purposes`.<br>`departure_tour_count` (`Float64`): weighted tours starting in the bin.<br>`arrival_tour_count` (`Float64`): weighted tours ending in the bin.<br>`duration_tour_count` (`Float64`): weighted tours whose prepared duration falls in the bin. |
| `tour_distance_by_tour_purpose` | Nonmandatory, joint, and at-work household-tour-unit records by lower-bound `SKIMDIST` bin and purpose, plus all-purpose totals; mandatory tours are excluded to match the legacy distribution. The metric is fixed to prepared origin-to-primary-destination `SKIMDIST` and does not switch to `tour_distance` or generic `distance_miles`. Every row is retained, with verified participant-row joint-tour groups contributing fractional weight that sums to one tour. | `distance_bin` (`String`): exact `0`, positive sub-mile `>0-<1`, whole-mile lower bound, or `40+`.<br>`tour_purpose` (`String`): purpose or `all_tour_purposes`.<br>`tour_count` (`Float64`): sum of eligible household-tour representation weight in the bin. |

### Tour Geography

| Summary Table | Information and Analytical Use | Fields |
|---|---|---|
| `average_mandatory_tour_distance_by_purpose_and_geography` | Weighted average home-to-work or home-to-school distance for internal non-WFH workers, university students, and school students, by home geography and regionwide. Use it to compare mandatory destination accessibility. | `mandatory_tour_purpose` (`String`): `work`, `university`, or `school`.<br>`geography_type` (`String`): home-geography system or rollup.<br>`geography_id` (`String`): home-geography identifier or rollup.<br>`average_tour_distance` (`Float64`): mean person-level mandatory distance weighted by `per.finalweight`.<br>`person_count` (`Float64`): sum of `per.finalweight` for people contributing to the mean. |
| `average_nonmandatory_tour_distance_by_purpose_and_geography` | Weighted average prepared origin-to-primary-destination `SKIMDIST` for individual nonmandatory tours by purpose and traveler home geography, plus regional rows. The metric does not switch to `tour_distance` or generic `distance_miles`. Use it to compare discretionary travel reach. | `nonmandatory_tour_purpose` (`String`): nonmandatory purpose.<br>`geography_type` (`String`): home-geography system or rollup.<br>`geography_id` (`String`): home-geography identifier or rollup.<br>`average_tour_distance` (`Float64`): mean prepared `SKIMDIST` weighted by `tours.finalweight`.<br>`tour_count` (`Float64`): sum of `tours.finalweight` for tours contributing to the mean. |
| `internal_external_nonmandatory_tour_frequency_by_home_geography` | Internal and external nonmandatory tours by traveler home geography, plus regional totals. Use it to calculate external-tour shares and locate households producing external discretionary travel. | `geography_type` (`String`): home-geography system or rollup.<br>`geography_id` (`String`): home-geography identifier or rollup.<br>`internal_nonmandatory_tour_count` (`Float64`): weighted internal nonmandatory tours.<br>`external_nonmandatory_tour_count` (`Float64`): weighted external nonmandatory tours. |
| `external_nonmandatory_tour_locations` | External nonmandatory tours by destination geography, plus a regional total. Use it to analyze external destination orientation and gateway demand. | `geography_type` (`String`): destination-geography system or rollup.<br>`geography_id` (`String`): destination-geography identifier or rollup.<br>`external_nonmandatory_tour_count` (`Float64`): weighted external nonmandatory tours ending there. |

### Trip Purpose, Mode, and Parking

| Summary Table | Information and Analytical Use | Fields |
|---|---|---|
| `trip_purpose_distribution` | Person-trip destination purpose cross-classified by parent tour purpose, with all-tour-purpose rows. Joint records use the sum of all matching participant person weights when available and valid party-size expansion only as a fallback. Use it to analyze activity chains within different kinds of tours. | `tour_purpose` (`String`): parent tour purpose or `all_tour_purposes`.<br>`trip_purpose` (`String`): destination purpose of the trip leg.<br>`trip_count` (`Float64`): weighted person-trips in the combination. |
| `stop_destination_purpose_by_tour_purpose` | Person-stop destination purposes by parent tour purpose. Joint records use the sum of all matching participant person weights when available and valid party-size expansion only as a fallback. Use it to understand what activities are chained into tours. | `stop_destination_purpose` (`String`): destination purpose of trip records flagged as stops.<br>`tour_purpose` (`String`): parent tour purpose.<br>`stop_count` (`Float64`): weighted person-stops in the combination. |
| `trip_mode_by_tour_purpose_and_tour_mode` | Person-trip mode counts by parent tour purpose and main tour mode, including all-purpose, all-tour-mode, and grand rollups. Joint records use the sum of all matching participant person weights when available; valid party-size expansion is the fallback, and sentinel, missing, or nonpositive party sizes fall back to one. Use it to examine access/egress and mode combinations within tours. | `tour_purpose` (`String`): parent purpose or `all_tour_purposes`.<br>`tour_mode` (`String`): main tour mode or `all_tour_modes`.<br>`trip_mode` (`String`): mode of the individual trip leg.<br>`trip_count` (`Float64`): weighted person-trips in the combination. |
| `parking_locations` | Auto-trip parking events by configured parking geography. Use it to map modeled parking demand and compare locations across runs. | `geography_type` (`String`): parking-geography system.<br>`geography_id` (`String`): valid positive parking-zone identifier at that geography.<br>`trip_count` (`Float64`): weighted trips parking there. |

### Trip Time and Distance

| Summary Table | Information and Analytical Use | Fields |
|---|---|---|
| `trip_departure_time_by_purpose` | Dense person-trip and person-stop departure-period profiles by parent tour purpose and for all purposes. Joint records use all matching participant person weights when available and valid party-size expansion only as a fallback. Use it to compare trip timing with stop timing. | `tour_purpose` (`String`): parent purpose or `all_tour_purposes`.<br>`time_bin` (`Int32`): prepared trip departure period index.<br>`departure_trip_count` (`Float64`): weighted person-trips departing in the bin.<br>`departure_stop_count` (`Float64`): weighted departing person-stops. |
| `trip_distance_by_purpose` | Person-trips by lower-bound OD-distance bin and parent tour purpose, plus all-purpose totals. Joint records use the sum of all matching participant person weights when available; valid party-size expansion is the fallback, non-joint trips contribute once, and sentinel, missing, or nonpositive fallback sizes resolve to one. Use it for purpose-specific trip length distributions. | `distance_bin` (`String`): exact `0`, positive sub-mile `>0-<1`, whole-mile lower bound, or `40+`.<br>`tour_purpose` (`String`): parent purpose or `all_tour_purposes`.<br>`trip_count` (`Float64`): sum of participant-adjusted trip weight in the bin. |
| `stop_out_of_direction_distance_by_tour_purpose` | Person-stops by lower-bound out-of-direction-distance bin, with a dense distribution for each purpose and all purposes. Joint records use all matching participant person weights when available and valid party-size expansion only as a fallback. Use it to quantify detour burden from stop-making. | `distance_bin` (`String`): exact `0`, positive sub-mile `>0-<1`, whole-mile lower bound, or `40+`.<br>`tour_purpose` (`String`): parent purpose or `all_tour_purposes`.<br>`stop_count` (`Float64`): weighted person-stops in the bin. |

### Skim Diagnostics

| Summary Table | Information and Analytical Use | Fields |
|---|---|---|
| `skimjoin_trip_component_stats` | Weighted descriptive statistics for every numeric `skim_` component on trips, by trip mode and skim scenario. Use it to QA joined time, distance, and cost values and identify missing or zero-heavy components. | `skim_scenario` (`String`): chosen or hypothetical evaluation scenario.<br>`trip_mode` (`String`): trip mode or `All Modes`.<br>`component` (`String`): numeric skim column name.<br>`n_total` (`Float64`): total trip weight eligible for the component/mode group.<br>`n_valid` (`Float64`): trip weight with non-null component values, including zeros.<br>`mean` (`Float64`): weighted mean including zeros.<br>`mean_nonzero` (`Float64`): weighted mean excluding zeros.<br>`std` (`Float64`): weighted population standard deviation.<br>`min` (`Float64`): minimum observed value.<br>`max` (`Float64`): maximum observed value.<br>`median` (`Float64`): weighted 50th percentile.<br>`mode` (`Float64`): value with greatest total weight, using the smaller value on ties.<br>`zero_share` (`Float64`): valid weight at exactly zero divided by `n_valid`.<br>`missing_share` (`Float64`): missing weight divided by `n_total`. |
| `skimjoin_trip_component_ecdf` | Optional 0th-through-100th weighted percentile curves for trip skim components by mode and scenario. Use it for distribution comparison when the compact stats table is insufficient. | `skim_scenario` (`String`): chosen or hypothetical scenario.<br>`trip_mode` (`String`): trip mode or `All Modes`.<br>`component` (`String`): numeric skim column name.<br>`percentile` (`Float64`): cumulative probability from 0.00 through 1.00 in 0.01 steps.<br>`value` (`Float64`): weighted quantile at that probability.<br>`n_valid` (`Float64`): total valid trip weight behind the curve. |
| `skimjoin_tour_component_stats` | Weighted descriptive statistics for numeric tour `skim_` components by tour mode and scenario. Use it to QA tour-level round-trip or composite skims. | `skim_scenario` (`String`): chosen or hypothetical evaluation scenario.<br>`tour_mode` (`String`): tour mode or `All Modes`.<br>`component` (`String`): numeric skim column name.<br>`n_total` (`Float64`): total tour weight in scope.<br>`n_valid` (`Float64`): tour weight with a non-null value, including zeros.<br>`mean` (`Float64`): weighted mean including zeros.<br>`mean_nonzero` (`Float64`): weighted mean excluding zeros.<br>`std` (`Float64`): weighted population standard deviation.<br>`min` (`Float64`): minimum value.<br>`max` (`Float64`): maximum value.<br>`median` (`Float64`): weighted median.<br>`mode` (`Float64`): highest-weight value, smaller on ties.<br>`zero_share` (`Float64`): valid weight at zero divided by `n_valid`.<br>`missing_share` (`Float64`): missing weight divided by `n_total`. |
| `skimjoin_tour_component_ecdf` | Optional weighted percentile curves for tour skim components by mode and scenario. Use it to compare complete tour-level distributions across runs. | `skim_scenario` (`String`): chosen or hypothetical scenario.<br>`tour_mode` (`String`): tour mode or `All Modes`.<br>`component` (`String`): numeric skim column name.<br>`percentile` (`Float64`): probability from 0.00 through 1.00.<br>`value` (`Float64`): weighted quantile at that probability.<br>`n_valid` (`Float64`): valid tour weight behind the curve. |

### Processor-Built Validation Summaries

| Summary Table | Information and Analytical Use | Fields |
|---|---|---|
| `traffic_count_comparisons` | Observed and modeled traffic counts that agree at count-location, direction, and period level. Use it for count scatterplots, percent differences, RMSE, and facility calibration. The table keeps only keys in both sources. | `count_location_id` (`String`): traffic-count station/location identifier.<br>`direction` (`String`): observed/modeled direction label.<br>`count_period` (`String`): count time-period label.<br>`observed_volume` (`Float64`): summed observed count for the key.<br>`modeled_volume` (`Float64`): summed assigned volume for the matching key. |
| `screenline_flow_comparisons` | Observed and modeled screenline flows matched by screenline, direction, and period, with a representative facility type. Use it for corridor-level flow validation and regression analysis. | `screenline_id` (`String`): screenline/cutline identifier.<br>`direction` (`String`): flow direction.<br>`count_period` (`String`): comparison period.<br>`facility_type` (`String`): supplied facility class, or `All` if absent.<br>`observed_volume` (`Float64`): summed observed flow.<br>`modeled_volume` (`Float64`): summed modeled flow for the matching key. |
| `transit_boardings_by_operator_and_technology` | Assigned transit boardings summed by operator and transit technology. Use it to compare ridership scale across agencies and modes. | `operator` (`String`): supplied transit operator identifier or name.<br>`technology` (`String`): supplied transit mode/technology category.<br>`boardings` (`Float64`): total assigned unlinked passenger boardings. |
| `transit_transfer_rate` | Assigned boardings divided by linked transit trips by operator, technology, and access mode. The value is boardings per linked trip, so values above one indicate transfers; subtract one if a transfers-per-trip measure is needed. | `operator` (`String`): transit operator.<br>`technology` (`String`): transit technology/mode.<br>`access_mode` (`String`): mode used to access transit.<br>`transfer_rate` (`Float64`): assigned boardings divided by linked trips; null for a zero linked-trip denominator. |
| `auto_vmt_totals` | One run-level personal-auto VMT total using the same eligible records, distance source, and legacy-compatible occupancy calculation as the detailed personal-auto VMT summary. Every eligible row is retained. Household-level joint rows use one vehicle, while repeated person-level joint rows use their fixed auto-mode occupancy. A prepared auto skim is preferred; otherwise eligible non-drive-transit trips use `od_dist`. Use it for overview controls and scenario comparison. | `auto_vmt` (`Float64`): total weighted personal-auto vehicle miles traveled. |
| `auto_vmt_by_home_geography_income_hhsize_time_period` | Personal-auto VMT and trip counts by home geography, income, household size, time period, and auto mode. When component periods exist, Daily rows are derived only from those non-Daily rows and replace any stale source Daily row; Daily-only groups are retained. Use it for equity, temporal, modal, and spatial VMT analysis. | `geography_type` (`String`): home-geography system or `all_geographies`.<br>`geography_id` (`String`): home-geography identifier or rollup.<br>`income_segment` (`String`): prepared household income segment or fallback rollup.<br>`household_size` (`String`): prepared household size or fallback rollup.<br>`time_period` (`String`): configured period or `Daily`.<br>`mode` (`String`): trip mode or `All Auto` fallback.<br>`auto_vmt` (`Float64`): sum of distance times `trips.finalweight`, divided by legacy-compatible vehicle occupancy.<br>`trip_count` (`Float64`): sum of `trips.finalweight` for eligible auto trips.<br>`distance_source` (`String`): provenance of the distance used, such as a skim or OD-distance field.<br>`time_period_source` (`String`): provenance of the time-period assignment. |
| `non_motorized_vmt_by_home_geography_income_hhsize_time_period` | Walk, bicycle, and e-bike weighted miles and trip counts by home geography, income, household size, period, and mode, including derived daily rows. Use it for active-travel exposure and equity analysis. | `geography_type` (`String`): home-geography system or rollup.<br>`geography_id` (`String`): home-geography identifier or rollup.<br>`income_segment` (`String`): household income segment or fallback rollup.<br>`household_size` (`String`): household size or fallback rollup.<br>`time_period` (`String`): configured period or `Daily`.<br>`mode` (`String`): `WALK`, `BIKE`, or `EBIKE` as available.<br>`non_motorized_vmt` (`Float64`): distance times `trips.finalweight`; despite the VMT name, this is weighted traveler mileage.<br>`trip_count` (`Float64`): sum of `trips.finalweight` for eligible trips.<br>`distance_source` (`String`): prepared or skim distance source used for the mode.<br>`time_period_source` (`String`): provenance of the period assignment. |
| `commercial_vmt_totals` | Commercial-vehicle VMT by vehicle type, split between internal and external travel. Use it for freight VMT totals and internal/external shares. | `commercial_vehicle_type` (`String`): supplied commercial vehicle/truck class.<br>`external_vmt` (`Float64`): VMT from records classified as external.<br>`internal_vmt` (`Float64`): VMT from records classified as internal. |
| `bicycle_vmt_by_facility_type` | Bicycle VMT by facility type, read directly when supplied or calculated as assigned bicycle trips times link distance. Use it to evaluate bicycle use by facility class. | `facility_type` (`String`): supplied bicycle/network facility category.<br>`bicycle_vmt` (`Float64`): summed bicycle vehicle/traveler miles on that facility type. |

## 3. Hypothetical All-Modes Skim Tables

These optional long-form tables evaluate skim components for all configured modes, not only the observed mode. Each file uses the prepared-cache format and is named `<hypothetical_skim_table>.<parquet|csv>`. Operational skimjoin QA report CSVs are outside the scope of this reference.

| Hypothetical Skim Table | Information and Analytical Use | Fields |
|---|---|---|
| `trip_hypothetical_skims` | Optional long-form trip skim values evaluated under configured modes other than each trip's observed mode. One row represents a trip, hypothetical mode, and skim component. Use it to compare travel impedance across modal alternatives without duplicating the full prepared trip table. It is written only when hypothetical skim tables are enabled and populated. | `trip_id` (`Int64`): Canonical identifier of the evaluated trip.<br>`observed_mode` (`String`): Mode selected in the source trip record.<br>`hypothetical_mode` (`String`): Alternative mode used for the skim lookup.<br>`component` (`String`): Configured skim output name, which determines the value's units and interpretation.<br>`value` (`Float64`): Skim value for the trip and hypothetical mode; null when the lookup is unresolved.<br>`finalweight` (`Float64`): Expansion weight inherited from the prepared trip record. |
| `tour_hypothetical_skims` | Optional long-form tour skim values evaluated under configured modes other than each tour's observed mode. One row represents a tour, hypothetical mode, direction, and skim component. Use it to compare outbound, inbound, and combined tour impedance across modal alternatives. It is written only when hypothetical skim tables are enabled and populated. | `tour_id` (`Int64`): Canonical identifier of the evaluated tour.<br>`observed_mode` (`String`): Main mode selected in the source tour record.<br>`hypothetical_mode` (`String`): Alternative mode used for the skim lookup.<br>`direction` (`String`): Outbound or inbound for directional components; null for nondirectional components.<br>`component` (`String`): Configured skim output name, which determines the value's units and interpretation.<br>`value` (`Float64`): Skim value for the tour, direction, and hypothetical mode; null when unresolved.<br>`finalweight` (`Float64`): Expansion weight inherited from the prepared tour record. |

## 4. Externally Supplied Table Schemas

**These tables are not created by the processor.** They are registered schemas for validation files supplied through `summary_table_map`. A mapped file can be CSV or Parquet and its configured filename does not need to match the schema name.

| Externally Supplied Table Schema | Information and Analytical Use | Fields |
|---|---|---|
| `link_validation_summary` | Modeled network link volumes with link endpoints and facility class. Use it to aggregate modeled flow by facility or inspect high-volume links. | `id` (`Int64`): link identifier.<br>`From_Node` (`Int64`): upstream node identifier.<br>`To_Node` (`Int64`): downstream node identifier.<br>`FACTYPE` (`Int64`): facility-type code.<br>`am_vol` (`Float64`): AM-period modeled link volume.<br>`md_vol` (`Float64`): midday modeled link volume.<br>`pm_vol` (`Float64`): PM-period modeled link volume.<br>`day_vol` (`Float64`): daily modeled link volume. |
| `count_location_counts_validation_summary` | Observed traffic-count volumes by count location and facility class. Use it as the observed side of location-level modeled-versus-observed comparisons. | `id` (`Int64`): count-location identifier.<br>`FACTYPE` (`Int64`): facility-type code.<br>`am_vol` (`Float64`): observed AM volume.<br>`md_vol` (`Float64`): observed midday volume.<br>`pm_vol` (`Float64`): observed PM volume.<br>`day_vol` (`Float64`): observed daily volume. |
| `count_location_volumes_validation_summary` | Modeled volumes at the traffic-count locations. Use it as the modeled side of location-level count comparisons. | `id` (`Int64`): count-location identifier matching the observed table.<br>`FACTYPE` (`Int64`): facility-type code.<br>`am_vol` (`Float64`): modeled AM volume.<br>`md_vol` (`Float64`): modeled midday volume.<br>`pm_vol` (`Float64`): modeled PM volume.<br>`day_vol` (`Float64`): modeled daily volume. |
| `count_location_scatter_validation_summary` | Long-form observed/modeled point pairs already prepared for count scatterplots. Use it when the source workflow supplies paired values directly. | `id` (`Int64`): count-location identifier.<br>`facility_type` (`String`): facility class code or label.<br>`period` (`String`): comparison period.<br>`observed_volume` (`Float64`): observed traffic volume.<br>`modeled_volume` (`Float64`): modeled traffic volume. |
| `count_location_fit_validation_summary` | Precomputed linear-fit diagnostics for observed-versus-modeled counts by facility type and period. Use it to draw regression lines and report calibration fit. | `facility_type` (`String`): facility class used for the fit.<br>`period` (`String`): time period used for the fit.<br>`slope` (`Float64`): fitted slope for modeled volume as a function of observed volume.<br>`intercept` (`Float64`): fitted modeled-volume intercept.<br>`r_squared` (`Float64`): coefficient of determination.<br>`n_locations` (`Int64`): paired count locations in the fit.<br>`observed_min` (`Float64`): minimum observed volume in the fitting data.<br>`observed_max` (`Float64`): maximum observed volume.<br>`equation_label` (`String`): preformatted regression-equation text.<br>`r_squared_label` (`String`): preformatted R-squared text. |
| `district_commuting_flows_validation_summary` | Supplied district-to-district commute-flow matrix for Albany, Corvallis, Lebanon, and Philomath. Use it as a local validation/control matrix. | `""` (`String`): origin district or row label.<br>`Albany` (`Float64`): commuters to Albany.<br>`Corvallis` (`Float64`): commuters to Corvallis.<br>`Lebanon` (`Float64`): commuters to Lebanon.<br>`Philomath` (`Float64`): commuters to Philomath.<br>`Total` (`Float64`): row total across destinations. |
| `county_commuting_flows_validation_summary` | Supplied county-to-county commute-flow matrix for Benton, Linn, and Marion counties. Use it as a regional commute-flow validation/control matrix. | `""` (`String`): origin county or row label.<br>`Benton` (`Float64`): commuters to Benton County.<br>`Linn` (`Float64`): commuters to Linn County.<br>`Marion` (`Float64`): commuters to Marion County.<br>`Total` (`Float64`): row total across destinations. |
| `commercial_vehicle_validation_summary` | Supplied commercial-vehicle trip totals by time of day and vehicle class. Use it to compare commercial demand composition and daily profiles. | `tod` (`String`): time-of-day row label.<br>`car` (`Float64`): commercial-car/light-vehicle trips.<br>`mu` (`Float64`): multi-unit truck trips.<br>`su` (`Float64`): single-unit truck trips.<br>`Total` (`Float64`): total commercial trips across classes. |
| `commercial_vehicle_vmt_validation_summary` | Supplied commercial-vehicle VMT by time of day and vehicle class. Use it to compare freight mileage composition and temporal patterns. | `tod` (`String`): time-of-day row label.<br>`car` (`Float64`): commercial-car/light-vehicle VMT.<br>`mu` (`Float64`): multi-unit truck VMT.<br>`su` (`Float64`): single-unit truck VMT.<br>`Total` (`Float64`): total commercial VMT across classes. |
| `external_trip_validation_summary` | Supplied external trip totals by time of day and purpose/class. Use it to analyze gateway demand by travel market. | `tod` (`String`): time-of-day row label.<br>`hbcoll` (`Float64`): home-based college trips.<br>`hbo` (`Float64`): home-based other trips.<br>`hbr` (`Float64`): home-based recreation trips.<br>`hbs` (`Float64`): home-based shopping trips.<br>`hbsch` (`Float64`): home-based school trips.<br>`hbw` (`Float64`): home-based work trips.<br>`nhbnw` (`Float64`): non-home-based non-work trips.<br>`nhbw` (`Float64`): non-home-based work trips.<br>`truck` (`Float64`): truck trips.<br>`Total` (`Float64`): total external trips across purposes/classes. |
| `external_vmt_validation_summary` | Supplied external VMT by time of day and purpose/class. Use it to identify which external markets contribute mileage. | `tod` (`String`): time-of-day row label.<br>`hbcoll` (`Float64`): home-based college VMT.<br>`hbo` (`Float64`): home-based other VMT.<br>`hbr` (`Float64`): home-based recreation VMT.<br>`hbs` (`Float64`): home-based shopping VMT.<br>`hbsch` (`Float64`): home-based school VMT.<br>`hbw` (`Float64`): home-based work VMT.<br>`nhbnw` (`Float64`): non-home-based non-work VMT.<br>`nhbw` (`Float64`): non-home-based work VMT.<br>`truck` (`Float64`): truck VMT.<br>`Total` (`Float64`): total external VMT across purposes/classes. |
| `auto_vmt_validation_summary` | Supplied auto and truck VMT by time of day and occupancy class. Use it as an independent control for modeled VMT. | `TOD` (`String`): time-of-day row label.<br>`SOV` (`Float64`): single-occupant-vehicle VMT.<br>`HOV2` (`Float64`): two-occupant shared-ride VMT.<br>`HOV3` (`Float64`): three-or-more-occupant shared-ride VMT.<br>`Truck` (`Float64`): truck VMT.<br>`Total` (`Float64`): total VMT across listed classes. |
| `work_from_home_validation_summary` | Supplied worker and work-from-home controls by district. Use it to compare modeled WFH counts or rates with external targets. | `District` (`String`): district name or identifier.<br>`Workers` (`Float64`): total workers in the district.<br>`WFH` (`Float64`): workers who work from home. |
<!-- GENERATED:PROCESSOR-OUTPUT-REFERENCE END -->
