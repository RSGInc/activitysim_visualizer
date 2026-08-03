# 31 - Dashboard Pages

Dashboard pages are discovered from modules under
[`dashboard/pages`](../dashboard/pages). Each leaf module contains one
`DashboardPage` subclass decorated with `@dashboard_page(...)`; page packages
export a `DashboardGroupDefinition` as `GROUP`.

## Page Definition Contract

Important fields:

| Field | Meaning |
|---|---|
| `page_id` | Stable config-facing page ID. |
| `title` | Display title. |
| `group_id` | Optional group such as `tour_summaries`. |
| `default_enabled` | Whether the page appears by default. |
| `prepared_data_mode` | `none`, `optional`, or `required`. |
| `required_summary_ids` | Summary tables required by the page. |
| `optional_summary_ids` | Independent add-on summaries that may be absent. |
| `required_prepared_tables` | Prepared tables required by the page. |

These declarations control dashboard cache loading, pruning, availability
diagnostics, and prepared-table loading. They do **not** select which generated
summaries the summarize workflow builds; ordinary summarize runs build every
`build_by_default=True` declaration.

`required_summary_ids` marks the page's primary data. If no run has a usable
required table, `self.data.summary(...)` records a required-data warning and the
page should render a standard unavailable card. `optional_summary_ids` declares
an independent add-on: its absence should hide or replace only that feature.
Neither declaration crashes the whole dashboard, and both can be partially
available when some runs are usable and others are excluded.

## Enabling Pages

Live pages are selected in config:

```yaml
dashboard:
  live:
    pages:
      - overview
      - long_term_choices
      - daily_travel
      - tour_summaries
```

Group selection modes are:

| Config entry | Selected children |
|---|---|
| `trip_summaries` | Default-enabled children, or the group's fallback child when none are default-enabled. |
| `trip_summaries: default` | Same default-child behavior, stated explicitly. |
| `trip_summaries: all` | Every registered child, including children with `default_enabled=False`. |
| `trip_summaries: [trip_mode, trip_stop_distance]` | Exactly the listed children in that order. |

When `dashboard.live.pages` is omitted, standalone pages and groups must be
default-enabled, and grouped children must also be default-enabled. A group's
`default_page_id` selects the initially visible tab/fallback; it does not by
itself enable every child.

`dashboard.export.pages` modifies matching pages in the resolved live page set;
it is not an allow-list. Unmentioned live pages keep their default export
behavior. Use `enabled: false`, `exclude_pages`, or `exclude_groups` to narrow
the export. Export cannot add a page omitted from `dashboard.live.pages`.

For example, enable only two trip-summary children:

```yaml
dashboard:
  live:
    pages:
      - overview
      - trip_summaries:
          - trip_mode
          - trip_stop_distance
```

## Prepared-Data Pages

Most pages are summary-backed. A prepared-data page declares
`prepared_data_mode` and `required_prepared_tables`. Use prepared data only when
the page truly needs disaggregate records.

Current runtime behavior is:

| Mode | Live dashboard behavior |
|---|---|
| `none` | Prepared caches are not requested for the page. `required_prepared_tables` must be empty. |
| `optional` | Prepared caches are requested, but the page's primary summary-backed workflow should remain useful when they are unavailable. |
| `required` | Prepared caches are requested and the page should present an unavailable state when they cannot be loaded. |

Both `optional` and `required` trigger loading; the distinction communicates
feature criticality and contributes to the strongest requirement across enabled
pages. Page render code remains responsible for the fallback. Standalone HTML
export does not load prepared tables; see chapter 34 for section-level export
rules.

## Generated Page Catalog

The catalog below is generated from the dashboard page registry. Regenerate it
with:

```bash
uv run python scripts/generate_wiki_catalogs.py
```

<!-- GENERATED:DASHBOARD-PAGE-CATALOG START -->
_Generated from the dashboard page registry._

Total registered pages: **27**

| Page ID | Title | Group | Default | Prepared data | Required summaries | Optional summaries | Required prepared tables |
|---|---|---|---|---|---|---|---|
| `overview` | Overview | - | yes | `none` | `population_totals`, `person_type_distribution`, `household_size_distribution`, `auto_vmt_totals` | - | - |
| `daily_activity_pattern` | Daily Activity Pattern | Daily Travel | yes | `none` | `daily_activity_pattern_by_person_type`, `mandatory_tour_frequency_by_person_type`, `nonmandatory_tour_frequency_by_person_type`, `tour_rates_by_person_type_and_tour_purpose`, `trip_rates_by_person_type_and_trip_purpose` | - | - |
| `escorted_tours` | Escorted Tours | Daily Travel | yes | `none` | `escorted_tour_totals`, `school_escorted_tours_by_escort_type_and_direction`, `adult_escort_event_stop_distribution`, `adult_escorted_tours_by_person_type_and_direction`, `adult_escorted_tour_distance_distribution_by_direction`, `adult_escorted_trip_distance_distribution_by_direction`, `student_school_escort_status_by_direction`, `student_households_by_student_count`, `households_with_school_escorting_by_student_count_and_direction`, `schoolkids_per_escorted_tour_by_student_count_and_direction` | - | - |
| `joint_travel` | Joint Travel | - | yes | `none` | `jtf_distribution`, `joint_tours_by_household_size`, `joint_tour_party_size_distribution`, `joint_tour_composition_by_party_size`, `person_jtp_by_household_size`, `household_jtp_by_household_size_and_jtf` | - | - |
| `individual_choices` | Individual Choices | Long-Term Choices | yes | `none` | `license_holding_status_distribution`, `bicycle_comfort_level_distribution`, `transit_pass_ownership_by_person_type`, `transit_subsidy_by_person_type` | - | - |
| `vehicle_ownership_type` | Vehicle Ownership and Type | Long-Term Choices | yes | `none` | `auto_ownership_distribution`, `autonomous_vehicle_ownership_totals`, `vehicle_age_distribution`, `vehicle_fuel_type_distribution`, `vehicle_body_type_distribution` | - | - |
| `mandatory_location_choice` | Mandatory Location Choice | Long-Term Choices | yes | `none` | `internal_external_worker_by_geography`, `external_worker_workplace_locations`, `work_location_distance_distribution_by_geography`, `school_location_distance_distribution_by_geography`, `university_location_distance_distribution_by_geography`, `work_from_home_rate_by_geography`, `telecommute_frequency_distribution`, `average_mandatory_tour_distance_by_purpose_and_geography` | - | - |
| `shadow_pricing` | Employment\Enrollment Match By Geography | Long-Term Choices | yes | `none` | `workplace_shadow_pricing_residuals`, `workplace_shadow_pricing_residual_histogram`, `school_shadow_pricing_residuals`, `school_shadow_pricing_residual_histogram` | - | - |
| `tour_skims` | Tour Skims | Skim Summaries | yes | `optional` | `skimjoin_tour_component_stats` | - | `tours` |
| `trip_skims` | Trip Skims | Skim Summaries | yes | `optional` | `skimjoin_trip_component_stats` | - | `trips` |
| `tour_purpose` | Tour Purpose | Tour Summaries | yes | `none` | `tour_category_distribution`, `tour_purpose_distribution` | - | - |
| `tour_mode` | Tour Mode | Tour Summaries | yes | `none` | `tour_mode_by_tour_purpose_and_auto_sufficiency`, `allocated_vehicle_age_by_occupancy`, `allocated_vehicle_fuel_type_by_occupancy`, `allocated_vehicle_body_type_by_occupancy` | - | - |
| `tour_time` | Tour Time | Tour Summaries | yes | `none` | `tour_time_of_day_by_tour_purpose` | - | - |
| `tour_distance` | Tour Distance | Tour Summaries | yes | `none` | `tour_distance_by_tour_purpose`, `average_mandatory_tour_distance_by_purpose_and_geography`, `average_nonmandatory_tour_distance_by_purpose_and_geography` | - | - |
| `tour_stop_frequency` | Tour Stop Frequency | Tour Summaries | yes | `none` | `tour_stop_frequency_by_tour_purpose`, `atwork_subtour_frequency_distribution` | - | - |
| `internal_external_tours` | Internal vs. External Tours | Tour Summaries | yes | `none` | `internal_external_nonmandatory_tour_frequency_by_home_geography`, `external_nonmandatory_tour_locations` | - | - |
| `park_and_ride_location` | Park-and-Ride Location | Tour Summaries | yes | `none` | `park_and_ride_location_residuals`, `park_and_ride_location_residual_histogram` | - | - |
| `trip_stop_purpose` | Trip and Stop Purpose | Trip Summaries | yes | `none` | `trip_purpose_distribution`, `stop_destination_purpose_by_tour_purpose` | - | - |
| `trip_mode` | Trip Mode | Trip Summaries | yes | `none` | `trip_mode_by_tour_purpose_and_tour_mode` | - | - |
| `trip_stop_time` | Trip and Stop Time | Trip Summaries | yes | `none` | `trip_departure_time_by_purpose` | - | - |
| `trip_stop_distance` | Trip and Stop Distance | Trip Summaries | yes | `none` | `trip_distance_by_purpose`, `stop_out_of_direction_distance_by_tour_purpose` | - | - |
| `parking_location` | Parking Location | Trip Summaries | no | `required` | `parking_locations` | - | `land_use` |
| `traffic` | Traffic Validation | Validation Summaries | yes | `none` | `screenline_flow_comparisons` | `link_validation_summary`, `count_location_counts_validation_summary`, `count_location_volumes_validation_summary`, `count_location_scatter_validation_summary`, `count_location_fit_validation_summary` | - |
| `transit` | Transit Validation | Validation Summaries | yes | `none` | `transit_boardings_by_operator_and_technology`, `transit_transfer_rate` | - | - |
| `vmt` | VMT Validation | Validation Summaries | yes | `none` | `auto_vmt_by_home_geography_income_hhsize_time_period`, `non_motorized_vmt_by_home_geography_income_hhsize_time_period`, `bicycle_vmt_by_facility_type` | `commercial_vehicle_validation_summary`, `commercial_vehicle_vmt_validation_summary`, `external_trip_validation_summary`, `external_vmt_validation_summary` | - |
| `regional_validation` | Regional Validation | Validation Summaries | no | `none` | - | `county_flows_validation_summary`, `county_flows_joja_validation_summary`, `commuting_flows` | - |
| `raw_trip_demo` | Prepared Trip Demo | - | no | `required` | - | - | `trips` |

## Registered Page Groups

| Group ID | Title | Default page | Default enabled |
|---|---|---|---|
| `daily_travel` | Daily Travel | `daily_activity_pattern` | yes |
| `long_term_choices` | Long-Term Choices | `individual_choices` | yes |
| `skim_summaries` | Skim Summaries | `tour_skims` | yes |
| `tour_summaries` | Tour Summaries | `tour_purpose` | yes |
| `trip_summaries` | Trip Summaries | `trip_stop_purpose` | yes |
| `validation` | Validation Summaries | `traffic` | yes |
<!-- GENERATED:DASHBOARD-PAGE-CATALOG END -->

## Related Chapters

- [30 - Output Visualizer](30-output-visualizer.md)
- [32 - Figures and Widgets](32-figures-and-widgets.md)
- [33 - Dashboard Page Recipes](33-dashboard-page-recipes.md)
- [45 - Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md)
