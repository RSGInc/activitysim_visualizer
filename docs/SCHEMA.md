# Prepared Cache Estimation-Output Schemas

This reference now mirrors the parquet schemas in `artifacts/prepared_cache/estimation-output/`.
The file remains here for convenience, but the table definitions below are based on `estimation-output`, not `filtered`.

## Primer: Adding a New Summary Function

The summary layer in this repo is built around small Polars functions that take prepared runtime tables and return one summary table:

```python
def my_summary(rd: RunData, config: Config) -> pl.DataFrame:
    ...
```

The prepared tables documented below are the main contract those functions should use. In practice:

- `rd.hh` maps to `households.parquet`
- `rd.per` maps to `persons.parquet`
- `rd.tours` maps to `tours.parquet`
- `rd.trips` maps to `trips.parquet`
- `rd.joint_participants` maps to `joint_tour_participants.parquet`
- `rd.land_use` maps to `land_use.parquet`

### Where New Summaries Live

- Put the builder in one of the modules under `processor/summarize/summaries/`.
- Follow the existing topical split:
  - `demographics.py` for household/person summaries
  - `long_term.py` for ownership, telecommute, and geography-based long-term summaries
  - `daily_travel.py` for person-day and tour-frequency summaries
  - `joint_travel.py` for joint-tour and participant summaries
  - `tour.py` for tour-level distributions
  - `trip.py` for trip/stop distributions

Examples worth copying:

- `processor/summarize/summaries/daily_travel.py`
- `processor/summarize/summaries/trip.py`
- `processor/summarize/summaries/tour.py`
- `processor/summarize/summaries/long_term.py`

### Builder Pattern Used In This Repo

Most builders follow the same pattern:

1. Define a stable output schema up front.
2. Check for the required prepared columns and return an empty typed table if they are missing.
3. Use prepared columns from `RunData` rather than raw ActivitySim inputs.
4. Aggregate with `finalweight` unless the logic explicitly needs something else.
5. Cast output columns to stable types before returning.
6. Sort the result for deterministic output.
7. Add total rows like `all_person_types`, `all_tour_purposes`, or `all_geographies` when the dashboard expects them.

Starter template:

```python
import polars as pl

from processor.models import RunData
from runtime.config import Config


def my_summary(rd: RunData, config: Config) -> pl.DataFrame:
    result_schema = {
        "category": pl.Utf8,
        "value": pl.Float64,
    }

    if "some_column" not in rd.trips.columns:
        return pl.DataFrame(schema=result_schema)

    return (
        rd.trips
        .filter(pl.col("some_column").is_not_null())
        .group_by("some_column")
        .agg(value=pl.col("finalweight").sum())
        .rename({"some_column": "category"})
        .with_columns(
            pl.col("category").cast(pl.Utf8),
            pl.col("value").cast(pl.Float64),
        )
        .select("category", "value")
        .sort("category")
    )
```

### Important Conventions

- Prefer prepared aliases and normalized columns from `RunData`. `processor/models.py` explicitly calls out fields like `household_id`, `person_id`, `tour_id`, `tour_purpose`, `trip_purpose`, `tour_mode`, `trip_mode`, `tour_category`, `depart_hour`, `stops`, `out_dir_dist`, `SKIMDIST`, `HGEO`, and `WGEO` as part of the prepared summary contract.
- Be defensive about missing columns. Several existing functions return an empty DataFrame with the right schema when a needed column is absent.
- When choosing a purpose column, some existing summaries probe multiple candidates and prefer a non-numeric string field, for example `tour_purpose`, `tour_type`, or `purpose`.
- Use `config` helpers when labels or ordering matter. Examples include `config.person_type_label(...)` and `config.ordered_modes(...)`.
- Geography-aware summaries usually emit per-geography rows plus an `all_geographies` row when `config.geography_enabled` is true.
- Dense outputs are often better than sparse outputs for charts. For example, distance-bin and time-bin summaries fill in missing bins with zeros.

### Registering A New Summary

After you add the function, register it in `processor/summarize/summary_specs.py` by adding a `SummarySpec` entry to `SUMMARY_SPECS`:

```python
SummarySpec(
    "my_summary_id",
    "my_summary_filename",
    my_module.my_summary,
),
```

Notes:

- `summary_id` is the stable internal identifier used by the cache and dashboard layers.
- `filename` becomes the CSV name written to the summary cache.
- The builder must return a single `pl.DataFrame`.
- If you need multiple outputs from one shared computation, follow the `long_term.tlfd(...)` pattern and add small wrapper builders in `summary_specs.py`.

### When To Update `processor/summarize/schema.py`

If the dashboard expects a canonical column layout for the new summary, add an entry to `SUMMARY_OUTPUT_COLUMNS` in `processor/summarize/schema.py`.

That file is not required for every summary, but it is used for dashboard-facing output contracts, especially where column names must stay fixed.

### Practical Checklist

- Add the builder function under `processor/summarize/summaries/`.
- Use prepared `RunData` tables and columns from the schema reference below.
- Return an empty typed DataFrame if required inputs are missing.
- Aggregate with weights, usually `finalweight`.
- Cast and order output columns explicitly.
- Register the summary in `processor/summarize/summary_specs.py`.
- Add a canonical output schema in `processor/summarize/schema.py` if the dashboard depends on fixed columns.
- Run the relevant summary build or tests to verify the output shape.

## households.parquet

- Rows: 43,637
- Columns: 203

| Column | Type | Nullable |
|---|---|---|
| password | large_string | yes |
| rm_household_id | int64 | yes |
| ms_household_id | int64 | yes |
| participation_group | int64 | yes |
| incentive | int64 | yes |
| incentive_amount | int64 | yes |
| first_travel_date | large_string | yes |
| last_travel_date | large_string | yes |
| browser | int64 | yes |
| tester | int64 | yes |
| num_days_complete | int64 | yes |
| is_complete | int64 | yes |
| disposition | int64 | yes |
| signup_complete_time | large_string | yes |
| signup_platform | large_string | yes |
| diary_platform | large_string | yes |
| signup_rmove | int64 | yes |
| signup_call_center | int64 | yes |
| diary_call_center | int64 | yes |
| num_days_complete_weekday | int64 | yes |
| num_complete_mon | int64 | yes |
| num_complete_tue | int64 | yes |
| num_complete_wed | int64 | yes |
| num_complete_thu | int64 | yes |
| num_complete_fri | int64 | yes |
| num_days_complete_weekend | int64 | yes |
| num_complete_sat | int64 | yes |
| num_complete_sun | int64 | yes |
| num_trips | int64 | yes |
| num_people_survey | int64 | yes |
| num_people | int64 | yes |
| raw_person_count | int64 | yes |
| num_surveyable | int64 | yes |
| num_activated | int64 | yes |
| num_participants | int64 | yes |
| num_adults | int64 | yes |
| num_kids | int64 | yes |
| num_workers | int64 | yes |
| num_students | int64 | yes |
| num_vehicles | int64 | yes |
| income_detailed | int64 | yes |
| income_followup | int64 | yes |
| income_broad | int64 | yes |
| residence_type | int64 | yes |
| residence_rent_own | int64 | yes |
| home_in_region | int64 | yes |
| home_state | int64 | yes |
| home_county | int64 | yes |
| home_bg_2010 | int64 | yes |
| home_bg_2020 | int64 | yes |
| home_puma_2012 | int64 | yes |
| home_puma_2022 | int64 | yes |
| home_lon | double | yes |
| home_lat | double | yes |
| sample_home_bg | double | yes |
| sample_home_lon | double | yes |
| sample_home_lat | double | yes |
| hh_weight | double | yes |
| bicycle_cargo_1 | int64 | yes |
| bicycle_cargo_2 | int64 | yes |
| bicycle_cargo_3 | int64 | yes |
| bicycle_cargo_4 | int64 | yes |
| bicycle_type_1 | int64 | yes |
| bicycle_type_2 | int64 | yes |
| bicycle_type_3 | int64 | yes |
| bicycle_type_4 | int64 | yes |
| bicycle_type_997 | int64 | yes |
| num_bicycle_adult | int64 | yes |
| num_bicycle_child | int64 | yes |
| ordot_hh | int64 | yes |
| past_participation | int64 | yes |
| feedback_web | large_string | yes |
| is_complete_adjusted_a | int64 | yes |
| is_complete_adjusted_b | int64 | yes |
| sample_segment | int64 | yes |
| home_mpo | large_string | yes |
| TAZ | int64 | yes |
| home_zone_id | int64 | yes |
| external_home_taz | bool | yes |
| external_home_zone_id | bool | yes |
| survey_household_id | int64 | yes |
| survey_hh_weight | int64 | yes |
| household_id.1 | int64 | yes |
| hhsize | int64 | yes |
| children | int64 | yes |
| auto_ownership | int64 | yes |
| income | int64 | yes |
| synthetic_income | bool | yes |
| HHT | int64 | yes |
| group_quarters | bool | yes |
| external_MAZ | bool | yes |
| school_escorting_outbound | int64 | yes |
| school_escorting_inbound | int64 | yes |
| school_escorting_outbound_cond | int64 | yes |
| joint_tour_frequency_composition | int64 | yes |
| has_joint_tour | int64 | yes |
| sample_rate | int64 | yes |
| income_segment | int64 | yes |
| num_drivers | int64 | yes |
| num_children | int64 | yes |
| num_young_children | int64 | yes |
| num_children_6_to_12 | int64 | yes |
| num_children_5_to_15 | int64 | yes |
| num_children_16_to_17 | int64 | yes |
| num_gradeschool | int64 | yes |
| num_highschool | int64 | yes |
| num_college_age | int64 | yes |
| num_young_adults | int64 | yes |
| num_non_workers | int64 | yes |
| num_predrive_child | int64 | yes |
| num_nonworker_adults | int64 | yes |
| num_fullTime_workers | int64 | yes |
| num_partTime_workers | int64 | yes |
| num_retired_adults | int64 | yes |
| home_is_urban | bool | yes |
| home_is_rural | bool | yes |
| num_hh_in_zone | int64 | yes |
| ebike_owner | bool | yes |
| av_ownership | bool | yes |
| workplace_location_accessibility | double | yes |
| shopping_accessibility | double | yes |
| othdiscr_accessibility | double | yes |
| numAVowned | int64 | yes |
| num_travel_active | int64 | yes |
| num_travel_active_adults | int64 | yes |
| num_travel_active_preschoolers | int64 | yes |
| num_travel_active_children | int64 | yes |
| num_travel_active_non_preschoolers | int64 | yes |
| participates_in_jtf_model | bool | yes |
| EXTERNAL | int64 | yes |
| EMP_AFS | int64 | yes |
| EMP_CON | int64 | yes |
| EMP_GOV | int64 | yes |
| EMP_HCS | int64 | yes |
| EMP_IFRPBS | int64 | yes |
| EMP_NRM | int64 | yes |
| EMP_OSV | int64 | yes |
| EMP_RET | int64 | yes |
| EMP_AER | int64 | yes |
| EMP_MFG | int64 | yes |
| EMP_WT | int64 | yes |
| EMP_EDU | int64 | yes |
| EMP_TWU | int64 | yes |
| EMP_TOTAL | int64 | yes |
| ENROLLGRADEKto8 | int64 | yes |
| ENROLLGRADE9to12 | int64 | yes |
| DIST_Kto8 | large_string | yes |
| DIST_9to12 | large_string | yes |
| COLLEGEENROLL | int64 | yes |
| PRKCST_HR | double | yes |
| PRKCST_DAY | double | yes |
| PRKCST_MNTH | double | yes |
| PRKSPACES | large_string | yes |
| INTHMI | int64 | yes |
| PARKATTRACT | int64 | yes |
| TERMINALTIME | large_string | yes |
| ESCOOACCTIME | int64 | yes |
| EBIKEACCTIME | large_string | yes |
| PNR_SPACES | int64 | yes |
| DISTRICT9 | int64 | yes |
| TOTHHS | int64 | yes |
| TOTPOP | int64 | yes |
| ACRES | double | yes |
| walk_dist_local_bus | double | yes |
| walk_dist_premium_transit | double | yes |
| icnt | int64 | yes |
| empden | double | yes |
| retempden | double | yes |
| duden | double | yes |
| popden | double | yes |
| popempdenpermi | double | yes |
| totint | int64 | yes |
| None | bool | yes |
| household_density | double | yes |
| population_density | double | yes |
| employment_density | double | yes |
| density_index | double | yes |
| ACTIVE_ACRES | double | yes |
| pseudomsa | int64 | yes |
| micro_dist_local_bus | int64 | yes |
| microtransit | int64 | yes |
| nev | int64 | yes |
| preschool_target | int64 | yes |
| is_parking_zone | bool | yes |
| auPkRetail | double | yes |
| auPkTotal | double | yes |
| auOpRetail | double | yes |
| auOpTotal | double | yes |
| trPkRetail | double | yes |
| trPkTotal | double | yes |
| trPkHH | double | yes |
| trOpRetail | double | yes |
| trOpTotal | double | yes |
| nmRetail | double | yes |
| nmTotal | double | yes |
| num_hh_joint_tours | int64 | yes |
| household_id | int64 | yes |
| finalweight | double | yes |
| HHVEH | int32 | yes |
| HHSIZE | int32 | yes |
| WORKERS | int32 | yes |
| ADULTS | int32 | yes |
| home_taz | int64 | yes |

## joint_tour_participants.parquet

- Rows: 16,576
- Columns: 5

| Column | Type | Nullable |
|---|---|---|
| tour_id | int64 | yes |
| household_id | int64 | yes |
| person_id | int64 | yes |
| participant_num | int64 | yes |
| participant_id | int64 | yes |

## land_use.parquet

- Rows: 22,333
- Columns: 45

| Column | Type | Nullable |
|---|---|---|
| MAZ | int64 | yes |
| TAZ | int64 | yes |
| EXTERNAL | int64 | yes |
| EMP_AFS | int64 | yes |
| EMP_CON | int64 | yes |
| EMP_GOV | int64 | yes |
| EMP_HCS | int64 | yes |
| EMP_IFRPBS | int64 | yes |
| EMP_NRM | int64 | yes |
| EMP_OSV | int64 | yes |
| EMP_RET | int64 | yes |
| EMP_AER | int64 | yes |
| EMP_MFG | int64 | yes |
| EMP_WT | int64 | yes |
| EMP_EDU | int64 | yes |
| EMP_TWU | int64 | yes |
| EMP_TOTAL | int64 | yes |
| ENROLLGRADEKto8 | int64 | yes |
| ENROLLGRADE9to12 | int64 | yes |
| DIST_Kto8 | large_string | yes |
| DIST_9to12 | large_string | yes |
| COLLEGEENROLL | int64 | yes |
| PRKCST_HR | double | yes |
| PRKCST_DAY | double | yes |
| PRKCST_MNTH | double | yes |
| PRKSPACES | large_string | yes |
| INTHMI | int64 | yes |
| PARKATTRACT | int64 | yes |
| TERMINALTIME | large_string | yes |
| ESCOOACCTIME | large_string | yes |
| EBIKEACCTIME | large_string | yes |
| PNR_SPACES | int64 | yes |
| DISTRICT9 | int64 | yes |
| TOTHHS | int64 | yes |
| TOTPOP | int64 | yes |
| ACRES | double | yes |
| walk_dist_local_bus | double | yes |
| walk_dist_premium_transit | double | yes |
| icnt | int64 | yes |
| empden | double | yes |
| retempden | double | yes |
| duden | double | yes |
| popden | double | yes |
| popempdenpermi | double | yes |
| totint | int64 | yes |

## persons.parquet

- Rows: 86,280
- Columns: 327

| Column | Type | Nullable |
|---|---|---|
| person_num | int64 | yes |
| rm_person_id | int64 | yes |
| ms_person_id | int64 | yes |
| hh_id | int64 | yes |
| password | large_string | yes |
| rm_household_id | int64 | yes |
| surveyable | int64 | yes |
| is_participant | int64 | yes |
| is_proxy | int64 | yes |
| has_proxy | int64 | yes |
| has_phone | int64 | yes |
| phone_type | int64 | yes |
| hh_is_complete | int64 | yes |
| is_complete | int64 | yes |
| num_days | int64 | yes |
| num_days_complete | int64 | yes |
| num_trips | int64 | yes |
| rmove_activated_time | large_string | yes |
| is_active_participant | int64 | yes |
| num_devices | int64 | yes |
| hh_surveyable | int64 | yes |
| relationship | int64 | yes |
| hh_ages | int64 | yes |
| age_app | int64 | yes |
| gender | int64 | yes |
| race_other | large_string | yes |
| ethnicity_other | large_string | yes |
| hh_employed | int64 | yes |
| employment | int64 | yes |
| work_freq | int64 | yes |
| work_mode | int64 | yes |
| telework_freq | int64 | yes |
| industry | int64 | yes |
| industry_other | large_string | yes |
| job_type | int64 | yes |
| num_jobs | int64 | yes |
| commute_freq | int64 | yes |
| work_lon | double | yes |
| work_lat | double | yes |
| work_in_region | int64 | yes |
| work_state | int64 | yes |
| work_county | int64 | yes |
| work_bg_2010 | double | yes |
| work_bg_2020 | double | yes |
| work_puma_2012 | int64 | yes |
| work_puma_2022 | int64 | yes |
| education | int64 | yes |
| hh_students | int64 | yes |
| student | int64 | yes |
| school_mode | int64 | yes |
| school_type | int64 | yes |
| school_freq | int64 | yes |
| remote_class_freq | int64 | yes |
| school_in_region | int64 | yes |
| school_state | int64 | yes |
| school_county | int64 | yes |
| school_puma_2012 | int64 | yes |
| school_puma_2022 | int64 | yes |
| school_bg_2010 | double | yes |
| school_bg_2020 | double | yes |
| school_lon | double | yes |
| school_lat | double | yes |
| second_home | int64 | yes |
| can_drive | int64 | yes |
| vehicle | int64 | yes |
| transit_freq | int64 | yes |
| tnc_freq | int64 | yes |
| bike_freq | int64 | yes |
| vanpool_freq | int64 | yes |
| bikeshare_freq | int64 | yes |
| scootshare_freq | int64 | yes |
| walk_freq | int64 | yes |
| transit_pass | int64 | yes |
| disability | int64 | yes |
| participate | int64 | yes |
| person_weight | double | yes |
| age_fv | int64 | yes |
| bike_attitude | int64 | yes |
| bike_comfort_bike_lanes | int64 | yes |
| bike_comfort_four_lanes | int64 | yes |
| bike_comfort_markings | int64 | yes |
| bike_comfort_path | int64 | yes |
| bike_comfort_street | int64 | yes |
| bike_comfort_wide_bike | int64 | yes |
| bike_purp_1 | int64 | yes |
| bike_purp_2 | int64 | yes |
| bike_purp_3 | int64 | yes |
| bike_purp_4 | int64 | yes |
| bike_purp_5 | int64 | yes |
| bike_purp_6 | int64 | yes |
| bike_purp_7 | int64 | yes |
| bike_purp_997 | int64 | yes |
| bike_purp_other | large_string | yes |
| commute_subsidy_1 | int64 | yes |
| commute_subsidy_10 | int64 | yes |
| commute_subsidy_11 | int64 | yes |
| commute_subsidy_12 | int64 | yes |
| commute_subsidy_13 | int64 | yes |
| commute_subsidy_2 | int64 | yes |
| commute_subsidy_3 | int64 | yes |
| commute_subsidy_4 | int64 | yes |
| commute_subsidy_5 | int64 | yes |
| commute_subsidy_6 | int64 | yes |
| commute_subsidy_7 | int64 | yes |
| commute_subsidy_8 | int64 | yes |
| commute_subsidy_9 | int64 | yes |
| commute_subsidy_996 | int64 | yes |
| commute_subsidy_998 | int64 | yes |
| commute_subsidy_use_1 | int64 | yes |
| commute_subsidy_use_10 | int64 | yes |
| commute_subsidy_use_11 | int64 | yes |
| commute_subsidy_use_12 | int64 | yes |
| commute_subsidy_use_13 | int64 | yes |
| commute_subsidy_use_2 | int64 | yes |
| commute_subsidy_use_3 | int64 | yes |
| commute_subsidy_use_4 | int64 | yes |
| commute_subsidy_use_5 | int64 | yes |
| commute_subsidy_use_6 | int64 | yes |
| commute_subsidy_use_7 | int64 | yes |
| commute_subsidy_use_8 | int64 | yes |
| commute_subsidy_use_9 | int64 | yes |
| commute_subsidy_use_996 | int64 | yes |
| ethnicity_1 | int64 | yes |
| ethnicity_2 | int64 | yes |
| ethnicity_3 | int64 | yes |
| ethnicity_4 | int64 | yes |
| ethnicity_997 | int64 | yes |
| ethnicity_999 | int64 | yes |
| ev_charge | int64 | yes |
| ev_charge_duration | int64 | yes |
| ev_charge_time | int64 | yes |
| ev_purchase | int64 | yes |
| exercise_freq | int64 | yes |
| exercise_freq_followup | int64 | yes |
| home_park | int64 | yes |
| home_park_pay | int64 | yes |
| home_vehicle_park_other | large_string | yes |
| micromobility_devices_1 | int64 | yes |
| micromobility_devices_2 | int64 | yes |
| micromobility_devices_3 | int64 | yes |
| micromobility_devices_4 | int64 | yes |
| micromobility_devices_996 | int64 | yes |
| micromobility_devices_997 | int64 | yes |
| office_available | int64 | yes |
| online_socialize_1 | int64 | yes |
| online_socialize_2 | int64 | yes |
| online_socialize_3 | int64 | yes |
| online_socialize_996 | int64 | yes |
| online_socialize_997 | int64 | yes |
| phone_contact | large_string | yes |
| race_1 | int64 | yes |
| race_2 | int64 | yes |
| race_3 | int64 | yes |
| race_4 | int64 | yes |
| race_5 | int64 | yes |
| race_997 | int64 | yes |
| race_999 | int64 | yes |
| remote_work_ability | int64 | yes |
| remote_work_broadband_1 | int64 | yes |
| remote_work_broadband_2 | int64 | yes |
| remote_work_broadband_3 | int64 | yes |
| remote_work_broadband_4 | int64 | yes |
| remote_work_broadband_5 | int64 | yes |
| remote_work_broadband_996 | int64 | yes |
| remote_work_broadband_997 | int64 | yes |
| remote_work_broadband_other | large_string | yes |
| school_mode_all_1 | int64 | yes |
| school_mode_all_100 | int64 | yes |
| school_mode_all_101 | int64 | yes |
| school_mode_all_102 | int64 | yes |
| school_mode_all_103 | int64 | yes |
| school_mode_all_104 | int64 | yes |
| school_mode_all_105 | int64 | yes |
| school_mode_all_106 | int64 | yes |
| school_mode_all_107 | int64 | yes |
| school_mode_all_24 | int64 | yes |
| school_mode_all_other_comment | large_string | yes |
| school_mode_primary | int64 | yes |
| share_2 | int64 | yes |
| share_5 | int64 | yes |
| share_6 | int64 | yes |
| share_7 | int64 | yes |
| share_996 | int64 | yes |
| share_work_1 | int64 | yes |
| share_work_2 | int64 | yes |
| share_work_3 | int64 | yes |
| share_work_5 | int64 | yes |
| share_work_996 | int64 | yes |
| share_work_997 | int64 | yes |
| tnc_work_hours | int64 | yes |
| transit_increase_1 | int64 | yes |
| transit_increase_10 | int64 | yes |
| transit_increase_11 | int64 | yes |
| transit_increase_2 | int64 | yes |
| transit_increase_3 | int64 | yes |
| transit_increase_4 | int64 | yes |
| transit_increase_5 | int64 | yes |
| transit_increase_6 | int64 | yes |
| transit_increase_7 | int64 | yes |
| transit_increase_8 | int64 | yes |
| transit_increase_9 | int64 | yes |
| transit_increase_996 | int64 | yes |
| work_vehicle_park | int64 | yes |
| work_vehicle_park_pay | int64 | yes |
| student_housing | int64 | yes |
| ecommerce | int64 | yes |
| OCCP | int64 | yes |
| occupation_other | large_string | yes |
| occupation_business | int64 | yes |
| occupation_business_other | large_string | yes |
| occupation_hosp | int64 | yes |
| occupation_hosp_other | large_string | yes |
| person_pct_trips_flagged | double | yes |
| num_no_flag_days | int64 | yes |
| age | int64 | yes |
| person_type | int64 | yes |
| work_taz | int64 | yes |
| work_maz | int64 | yes |
| external_work_taz | bool | yes |
| external_work_maz | bool | yes |
| school_taz | int64 | yes |
| school_maz | int64 | yes |
| external_school_taz | bool | yes |
| external_school_maz | bool | yes |
| survey_person_id | int64 | yes |
| survey_household_id | int64 | yes |
| survey_person_weight | int64 | yes |
| household_id | int64 | yes |
| SEX | int64 | yes |
| PNUM | int64 | yes |
| pstudent | int64 | yes |
| is_student | bool | yes |
| major_uni | bool | yes |
| school_zone_id | int64 | yes |
| is_commercial_driver_no_workplace | bool | yes |
| is_delivery_driver | bool | yes |
| transit_pass_subsidy | int64 | yes |
| free_parking_at_work | bool | yes |
| transit_pass_ownership | bool | yes |
| telecommute_frequency | large_string | yes |
| industry_coded | large_string | yes |
| SCHG | int64 | yes |
| ESR | int64 | yes |
| is_worker | large_string | yes |
| occupation_category | large_string | yes |
| work_from_home | large_string | yes |
| workplace_zone_id | int64 | yes |
| external_worker_identification | bool | yes |
| is_internal_worker | bool | yes |
| external_workplace_zone_id | int64 | yes |
| has_license | bool | yes |
| WKHP | int64 | yes |
| WKW | int64 | yes |
| ptype | int64 | yes |
| bike_comfort | large_string | yes |
| cdap_activity | large_string | yes |
| mandatory_tour_frequency | large_string | yes |
| _escort | int64 | yes |
| _shopping | int64 | yes |
| _othmaint | int64 | yes |
| _eatout | int64 | yes |
| _social | int64 | yes |
| _othdiscr | int64 | yes |
| non_mandatory_tour_frequency | int64 | yes |
| age_16_to_19 | bool | yes |
| age_16_p | bool | yes |
| adult | bool | yes |
| male | bool | yes |
| female | bool | yes |
| pemploy | int64 | yes |
| is_university | bool | yes |
| school_segment | int64 | yes |
| is_external_worker | bool | yes |
| home_zone_id | int64 | yes |
| time_factor_work | double | yes |
| time_factor_nonwork | double | yes |
| naics_code | int64 | yes |
| occupation | large_string | yes |
| is_income_less25K | bool | yes |
| is_income_25K_to_60K | bool | yes |
| is_income_60K_to_120K | bool | yes |
| is_income_greater60K | bool | yes |
| is_income_greater120K | bool | yes |
| is_non_worker_in_HH | bool | yes |
| is_all_adults_full_time_workers | bool | yes |
| is_pre_drive_child_in_HH | bool | yes |
| is_out_of_home_worker | bool | yes |
| external_workplace_location_logsum | large_string | yes |
| external_workplace_modechoice_logsum | large_string | yes |
| school_location_logsum | double | yes |
| school_modechoice_logsum | double | yes |
| distance_to_school | double | yes |
| roundtrip_auto_time_to_school | double | yes |
| workplace_location_logsum | double | yes |
| workplace_modechoice_logsum | double | yes |
| distance_to_work | double | yes |
| work_zone_area_type | int64 | yes |
| auto_time_home_to_work | double | yes |
| roundtrip_auto_time_to_work | double | yes |
| exp_daily_work | double | yes |
| travel_active | bool | yes |
| work_and_school_and_worker | bool | yes |
| work_and_school_and_student | bool | yes |
| num_mand | int64 | yes |
| num_work_tours | int64 | yes |
| has_pre_school_child_with_mandatory | bool | yes |
| has_driving_age_child_with_mandatory | bool | yes |
| num_joint_tours | int64 | yes |
| num_non_mand | int64 | yes |
| num_escort_tours | int64 | yes |
| num_eatout_tours | int64 | yes |
| num_shop_tours | int64 | yes |
| num_maint_tours | int64 | yes |
| num_discr_tours | int64 | yes |
| num_social_tours | int64 | yes |
| num_non_escort_tours | int64 | yes |
| num_shop_maint_tours | int64 | yes |
| num_shop_maint_escort_tours | int64 | yes |
| num_add_shop_maint_tours | int64 | yes |
| num_soc_discr_tours | int64 | yes |
| num_add_soc_discr_tours | int64 | yes |
| person_id | int64 | yes |
| finalweight | double | yes |
| home_taz | int64 | yes |
| work_taz_right | int64 | yes |
| school_taz_right | int64 | yes |
| imf_choice | int32 | yes |

## tours.parquet

- Rows: 72,311
- Columns: 51

| Column | Type | Nullable |
|---|---|---|
| person_id | int64 | yes |
| tour_type | large_string | yes |
| tour_type_count | int64 | yes |
| tour_type_num | int64 | yes |
| tour_num | int64 | yes |
| tour_count | int64 | yes |
| tour_category | large_string | yes |
| number_of_participants | int64 | yes |
| destination | int64 | yes |
| origin | int64 | yes |
| household_id | int64 | yes |
| start | int64 | yes |
| end | int64 | yes |
| duration | int64 | yes |
| school_esc_outbound | large_string | yes |
| school_esc_inbound | large_string | yes |
| num_escortees | int64 | yes |
| tdd | int64 | yes |
| tour_id_temp | int64 | yes |
| composition | large_string | yes |
| is_external_tour | bool | yes |
| is_internal_tour | bool | yes |
| destination_logsum | double | yes |
| vehicle_occup_1 | large_string | yes |
| vehicle_occup_2 | large_string | yes |
| vehicle_occup_3.5 | large_string | yes |
| pnr_zone_id | int64 | yes |
| tour_mode | large_string | yes |
| mode_choice_logsum | double | yes |
| selected_vehicle | large_string | yes |
| atwork_subtour_frequency | large_string | yes |
| parent_tour_id | double | yes |
| stop_frequency | large_string | yes |
| primary_purpose | large_string | yes |
| tour_id | int64 | yes |
| tour_purpose | large_string | yes |
| start_hour | int32 | yes |
| end_hour | int32 | yes |
| tourdur | int32 | yes |
| finalweight | double | yes |
| HHVEH | int64 | yes |
| WORKERS | int64 | yes |
| ADULTS | int64 | yes |
| AUTOSUFF | int32 | yes |
| num_ob_stops | int32 | yes |
| num_ib_stops | int32 | yes |
| num_tot_stops | int32 | yes |
| OTAZ | int32 | yes |
| DTAZ | int32 | yes |
| SKIMDIST | double | yes |
| NUMBER_HH | int32 | yes |

## trips.parquet

- Rows: 207,207
- Columns: 262

| Column | Type | Nullable |
|---|---|---|
| person_id | int64 | yes |
| household_id | int64 | yes |
| primary_purpose | large_string | yes |
| trip_num | int32 | yes |
| outbound | bool | yes |
| trip_count | int64 | yes |
| destination | int64 | yes |
| origin | int64 | yes |
| tour_id | int64 | yes |
| escort_participants | large_string | yes |
| school_escort_direction | large_string | yes |
| purpose | large_string | yes |
| destination_logsum | double | yes |
| depart | int64 | yes |
| trip_mode | large_string | yes |
| mode_choice_logsum | double | yes |
| vot_da | double | yes |
| vot_s2 | double | yes |
| vot_s3 | double | yes |
| ebike_owner | bool | yes |
| parkingCost | double | yes |
| auto_op_cost | double | yes |
| autoCPMFactor | double | yes |
| autoParkingCostFactor | double | yes |
| autoTermTimeFactor | double | yes |
| costFactorS2 | double | yes |
| costFactorS3 | double | yes |
| transitSubsidyPassDiscount | int64 | yes |
| origTaxiWaitTime | double | yes |
| origSingleTNCWaitTime | double | yes |
| destSingleTNCWaitTime | double | yes |
| origSharedTNCWaitTime | double | yes |
| da_dist_skims | double | yes |
| s2_time_skims | double | yes |
| s2_dist_skims | double | yes |
| s2_cost_skims | int64 | yes |
| s3_time_skims | double | yes |
| s3_dist_skims | double | yes |
| s3_cost_skims | int64 | yes |
| ebike_time | double | yes |
| escooter_time | double | yes |
| microtransit_orig | int64 | yes |
| microtransit_dest | int64 | yes |
| microtransit_operating | bool | yes |
| microtransit_available | bool | yes |
| microtransit_time | double | yes |
| nev_orig | int64 | yes |
| nev_dest | int64 | yes |
| nev_operating | bool | yes |
| nev_available | bool | yes |
| nev_time | double | yes |
| microtransit_local_access_available_out | bool | yes |
| nev_local_access_available_out | bool | yes |
| microtransit_local_egress_available_out | bool | yes |
| nev_local_egress_available_out | bool | yes |
| microtransit_local_access_available_in | bool | yes |
| nev_local_access_available_in | bool | yes |
| microtransit_local_egress_available_in | bool | yes |
| nev_local_egress_available_in | bool | yes |
| microtransit_local_access_time_out | double | yes |
| nev_local_access_time_out | double | yes |
| microtransit_local_egress_time_out | int64 | yes |
| nev_local_egress_time_out | int64 | yes |
| microtransit_local_access_time_in | int64 | yes |
| nev_local_access_time_in | int64 | yes |
| microtransit_local_egress_time_in | double | yes |
| nev_local_egress_time_in | double | yes |
| parking_zone | int64 | yes |
| trip_period | large_string | yes |
| tour_participants | int64 | yes |
| is_ea | bool | yes |
| is_am | bool | yes |
| is_md | bool | yes |
| is_pm | bool | yes |
| is_ev | bool | yes |
| vot1 | int64 | yes |
| vot2 | int64 | yes |
| vot3 | int64 | yes |
| inbound | int32 | yes |
| DRIVEALONE_EA_LOW | int64 | yes |
| SHARED2_EA_LOW | int64 | yes |
| SHARED3_EA_LOW | int64 | yes |
| DRIVEALONE_EA_MED | int64 | yes |
| SHARED2_EA_MED | int64 | yes |
| SHARED3_EA_MED | int64 | yes |
| DRIVEALONE_EA_HIGH | int64 | yes |
| SHARED2_EA_HIGH | int64 | yes |
| SHARED3_EA_HIGH | int64 | yes |
| WALK_LOC_EA | int64 | yes |
| WALK_PRM_EA | int64 | yes |
| WALK_MIX_EA | int64 | yes |
| PNR_LOCOUT_EA | int64 | yes |
| PNR_PRMOUT_EA | int64 | yes |
| PNR_MIXOUT_EA | int64 | yes |
| KNR_LOCOUT_EA | int64 | yes |
| KNR_PRMOUT_EA | int64 | yes |
| KNR_MIXOUT_EA | int64 | yes |
| TNC_LOCOUT_EA | int64 | yes |
| TNC_PRMOUT_EA | int64 | yes |
| TNC_MIXOUT_EA | int64 | yes |
| PNR_LOCIN_EA | int64 | yes |
| PNR_PRMIN_EA | int64 | yes |
| PNR_MIXIN_EA | int64 | yes |
| KNR_LOCIN_EA | int64 | yes |
| KNR_PRMIN_EA | int64 | yes |
| KNR_MIXIN_EA | int64 | yes |
| TNC_LOCIN_EA | int64 | yes |
| TNC_PRMIN_EA | int64 | yes |
| TNC_MIXIN_EA | int64 | yes |
| BIKE_EA | int64 | yes |
| WALK_EA | int64 | yes |
| DRIVEALONE_AM_LOW | int64 | yes |
| SHARED2_AM_LOW | int64 | yes |
| SHARED3_AM_LOW | int64 | yes |
| DRIVEALONE_AM_MED | int64 | yes |
| SHARED2_AM_MED | int64 | yes |
| SHARED3_AM_MED | int64 | yes |
| DRIVEALONE_AM_HIGH | int64 | yes |
| SHARED2_AM_HIGH | int64 | yes |
| SHARED3_AM_HIGH | int64 | yes |
| WALK_LOC_AM | int64 | yes |
| WALK_PRM_AM | int64 | yes |
| WALK_MIX_AM | int64 | yes |
| PNR_LOCOUT_AM | int64 | yes |
| PNR_PRMOUT_AM | int64 | yes |
| PNR_MIXOUT_AM | int64 | yes |
| KNR_LOCOUT_AM | int64 | yes |
| KNR_PRMOUT_AM | int64 | yes |
| KNR_MIXOUT_AM | int64 | yes |
| TNC_LOCOUT_AM | int64 | yes |
| TNC_PRMOUT_AM | int64 | yes |
| TNC_MIXOUT_AM | int64 | yes |
| PNR_LOCIN_AM | int64 | yes |
| PNR_PRMIN_AM | int64 | yes |
| PNR_MIXIN_AM | int64 | yes |
| KNR_LOCIN_AM | int64 | yes |
| KNR_PRMIN_AM | int64 | yes |
| KNR_MIXIN_AM | int64 | yes |
| TNC_LOCIN_AM | int64 | yes |
| TNC_PRMIN_AM | int64 | yes |
| TNC_MIXIN_AM | int64 | yes |
| BIKE_AM | int64 | yes |
| WALK_AM | int64 | yes |
| DRIVEALONE_MD_LOW | int64 | yes |
| SHARED2_MD_LOW | int64 | yes |
| SHARED3_MD_LOW | int64 | yes |
| DRIVEALONE_MD_MED | int64 | yes |
| SHARED2_MD_MED | int64 | yes |
| SHARED3_MD_MED | int64 | yes |
| DRIVEALONE_MD_HIGH | int64 | yes |
| SHARED2_MD_HIGH | int64 | yes |
| SHARED3_MD_HIGH | int64 | yes |
| WALK_LOC_MD | int64 | yes |
| WALK_PRM_MD | int64 | yes |
| WALK_MIX_MD | int64 | yes |
| PNR_LOCOUT_MD | int64 | yes |
| PNR_PRMOUT_MD | int64 | yes |
| PNR_MIXOUT_MD | int64 | yes |
| KNR_LOCOUT_MD | int64 | yes |
| KNR_PRMOUT_MD | int64 | yes |
| KNR_MIXOUT_MD | int64 | yes |
| TNC_LOCOUT_MD | int64 | yes |
| TNC_PRMOUT_MD | int64 | yes |
| TNC_MIXOUT_MD | int64 | yes |
| PNR_LOCIN_MD | int64 | yes |
| PNR_PRMIN_MD | int64 | yes |
| PNR_MIXIN_MD | int64 | yes |
| KNR_LOCIN_MD | int64 | yes |
| KNR_PRMIN_MD | int64 | yes |
| KNR_MIXIN_MD | int64 | yes |
| TNC_LOCIN_MD | int64 | yes |
| TNC_PRMIN_MD | int64 | yes |
| TNC_MIXIN_MD | int64 | yes |
| BIKE_MD | int64 | yes |
| WALK_MD | int64 | yes |
| DRIVEALONE_PM_LOW | int64 | yes |
| SHARED2_PM_LOW | int64 | yes |
| SHARED3_PM_LOW | int64 | yes |
| DRIVEALONE_PM_MED | int64 | yes |
| SHARED2_PM_MED | int64 | yes |
| SHARED3_PM_MED | int64 | yes |
| DRIVEALONE_PM_HIGH | int64 | yes |
| SHARED2_PM_HIGH | int64 | yes |
| SHARED3_PM_HIGH | int64 | yes |
| WALK_LOC_PM | int64 | yes |
| WALK_PRM_PM | int64 | yes |
| WALK_MIX_PM | int64 | yes |
| PNR_LOCOUT_PM | int64 | yes |
| PNR_PRMOUT_PM | int64 | yes |
| PNR_MIXOUT_PM | int64 | yes |
| KNR_LOCOUT_PM | int64 | yes |
| KNR_PRMOUT_PM | int64 | yes |
| KNR_MIXOUT_PM | int64 | yes |
| TNC_LOCOUT_PM | int64 | yes |
| TNC_PRMOUT_PM | int64 | yes |
| TNC_MIXOUT_PM | int64 | yes |
| PNR_LOCIN_PM | int64 | yes |
| PNR_PRMIN_PM | int64 | yes |
| PNR_MIXIN_PM | int64 | yes |
| KNR_LOCIN_PM | int64 | yes |
| KNR_PRMIN_PM | int64 | yes |
| KNR_MIXIN_PM | int64 | yes |
| TNC_LOCIN_PM | int64 | yes |
| TNC_PRMIN_PM | int64 | yes |
| TNC_MIXIN_PM | int64 | yes |
| BIKE_PM | int64 | yes |
| WALK_PM | int64 | yes |
| DRIVEALONE_EV_LOW | int64 | yes |
| SHARED2_EV_LOW | int64 | yes |
| SHARED3_EV_LOW | int64 | yes |
| DRIVEALONE_EV_MED | int64 | yes |
| SHARED2_EV_MED | int64 | yes |
| SHARED3_EV_MED | int64 | yes |
| DRIVEALONE_EV_HIGH | int64 | yes |
| SHARED2_EV_HIGH | int64 | yes |
| SHARED3_EV_HIGH | int64 | yes |
| WALK_LOC_EV | int64 | yes |
| WALK_PRM_EV | int64 | yes |
| WALK_MIX_EV | int64 | yes |
| PNR_LOCOUT_EV | int64 | yes |
| PNR_PRMOUT_EV | int64 | yes |
| PNR_MIXOUT_EV | int64 | yes |
| KNR_LOCOUT_EV | int64 | yes |
| KNR_PRMOUT_EV | int64 | yes |
| KNR_MIXOUT_EV | int64 | yes |
| TNC_LOCOUT_EV | int64 | yes |
| TNC_PRMOUT_EV | int64 | yes |
| TNC_MIXOUT_EV | int64 | yes |
| PNR_LOCIN_EV | int64 | yes |
| PNR_PRMIN_EV | int64 | yes |
| PNR_MIXIN_EV | int64 | yes |
| KNR_LOCIN_EV | int64 | yes |
| KNR_PRMIN_EV | int64 | yes |
| KNR_MIXIN_EV | int64 | yes |
| TNC_LOCIN_EV | int64 | yes |
| TNC_PRMIN_EV | int64 | yes |
| TNC_MIXIN_EV | int64 | yes |
| BIKE_EV | int64 | yes |
| WALK_EV | int64 | yes |
| sample_rate | int64 | yes |
| origin_parking_zone | int64 | yes |
| otaz | int64 | yes |
| dtaz | int64 | yes |
| trip_id | int64 | yes |
| trip_purpose | large_string | yes |
| depart_hour | int32 | yes |
| tour_purpose | large_string | yes |
| finalweight | double | yes |
| AUTOSUFF | int32 | yes |
| num_participants | int32 | yes |
| tour_mode | large_string | yes |
| tour_category | large_string | yes |
| HHVEH | int64 | yes |
| WORKERS | int64 | yes |
| OTAZ | int32 | yes |
| DTAZ | int32 | yes |
| od_dist | double | yes |
| max_trip_num | int64 | yes |
| stops | int32 | yes |
| tour_OTAZ | int64 | yes |
| tour_DTAZ | int64 | yes |
| out_dir_dist | double | yes |
