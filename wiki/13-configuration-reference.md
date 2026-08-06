# 13 - Configuration Reference

This page is a field-by-field reference for the main ActivitySim Visualizer
configuration. For an introduction, read
[11 - Configuring Your Data](11-configuring-your-data.md); for the canonical
example, see [`config.yaml`](../config.yaml).

Unknown and removed keys cause a validation error, which gives the canonical
replacement when one is available.

## Reading This Reference

The field type controls the base directory for a relative path:

| Field family | Relative to | Notes |
|---|---|---|
| `root` | main config directory | Becomes an absolute artifact/cache root during config loading. |
| `runs[*].dir` | main config directory | Raw ActivitySim output directory. |
| `files.*`, `runs[*].file_map.*` | the resolved run directory | File stems may omit `.parquet` or `.csv`; Parquet is tried before CSV. |
| `fallback_files.*`, `prepared_table_map.*`, `summary_table_map.*` | main config directory | Values must include `.parquet` or `.csv`. |
| `prepare.distance_skim.file`, `runs[*].skim_file` | the resolved run directory | The loader resolves a relative legacy distance-skim path separately for each run. |
| other main-config enrichment, lookup, and skimjoin paths | main config directory | Includes `prepare.time_periods.network_los_file`, `prepare.non_motorized_distance_skim.file`, segmentation CSVs, and `skimjoin.defaults.*`. |
| paths inside the standalone skimjoin config | standalone skimjoin config directory | See chapter 25. |
| `dashboard.export.output_path` | resolved `root` | Absolute output paths remain absolute. |

The Impact columns use these terms:

| Impact | Meaning |
|---|---|
| Prepare | Can change prepared tables or prepared cache identity. |
| Summary | Can change summary cache outputs. |
| Presentation | Can change dashboard labels, pages, colors, or export output. |
| Runtime | Controls which workflow runs, but does not directly define data content. |

## Common Recipes

### Minimal Two-Run Comparison

```yaml
name: Regional Model Comparison
root: artifacts

pipeline:
  steps: [prepare, summarize, dashboard]
  dashboard_mode: live

runs:
  - dir: C:\models\base\output
    label: Base
  - dir: C:\models\build\output
    label: Build
```

### Prepared-Table Workflow

Use `prepared_table_map` to load canonical prepared tables directly. The run
does not do the raw prepare step.

```yaml
pipeline:
  steps: [summarize, dashboard]

runs:
  - label: Filtered Run
    prepared_table_map:
      households: C:\prepared\households.parquet
      persons: C:\prepared\persons.parquet
      tours: C:\prepared\tours.parquet
      trips: C:\prepared\trips.parquet
      land_use: C:\prepared\land_use.parquet
```

### Export Workflow

```yaml
pipeline:
  steps: [summarize, dashboard]
  dashboard_mode: export

dashboard:
  export:
    output_path: exports\dashboard.html
    dashboard:
      weighting: [weighted]
      values: [percent, count]
```

### Global And Run-Level Skimjoin

```yaml
pipeline:
  steps: [prepare, skimjoin, summarize, dashboard]

skimjoin:
  defaults:
    config_path: configs\skimjoin_default.yaml
    skim_files:
      - C:\skims\*.omx
    network_los_file: C:\skims\network_los.yaml

runs:
  - dir: C:\models\base\output
    label: Base
  - dir: C:\models\build\output
    label: Build
    skimjoin:
      skim_files:
        - C:\build_skims\*.omx
```

## Top-Level Fields

| Field | Type | Default | Impact | Purpose |
|---|---|---|---|---|
| `name` | string | `""` | Presentation | Human-readable config name. |
| `root` | path string | `artifacts/summary_cache` when omitted | Prepare, Summary, Presentation | Artifact root used by prepared caches, summary caches, and relative export paths. |
| `log_level` | string | `INFO` | Runtime | Logging verbosity. Allowed: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `pipeline` | mapping | `summarize`, `dashboard`, live dashboard | Runtime | Workflow step selection and dashboard mode. |
| `runs` | list of mappings | `[]` | Prepare, Summary | Model runs to process and compare. |
| `files` | mapping | ActivitySim `final_*` table stems | Prepare | Default raw input table stems. |
| `fallback_files` | mapping | `{}` | Prepare | Shared explicit optional files used when run-local optional files are absent. |
| `zones` | mapping | MAZ/TAZ defaults | Prepare, Summary | Zone-system behavior and land-use zone aliases. |
| `columns` | mapping | Built-in column aliases | Prepare, Summary | Source column aliases for non-standard ActivitySim outputs. |
| `prepare` | mapping | Built-in prepare defaults | Prepare | Prepared table format, validation, distance skims, VOT bins, and auto sufficiency. |
| `skimjoin` | mapping | disabled unless `pipeline.steps` includes `skimjoin` | Prepare, Summary | Optional wiring to a separate standalone skimjoin config. |
| `segment` | mapping | disabled | Summary, Presentation | Optional segmented summaries and dashboard segment controls. |
| `weighting` | mapping | `{}` | Summary, Presentation | Declarative named weighting modes backed by prepared source columns. |
| `summarize` | mapping | weighted and unweighted summaries | Summary | Summary weighting, purpose grouping, geography, and PNR mode behavior. |
| `dashboard` | mapping | live dashboard defaults | Presentation | Dashboard title, page selection, calculation notes, MAZ geography toggle, and export settings. |
| `display` | mapping | built-in labels and colors | Presentation | Dashboard labels, category order, and run colors. |
| `extensions` | mapping | `{}` | Summary, Presentation | Advanced importable weighting calculation modules and their settings. Extension code is trusted. |
| `modes` | mapping | `{}` | Summary, Presentation | Optional mode ordering and named summary mode groups. |

## `weighting`

`weighting.modes` defines named alternatives that use columns already present
in prepared household, person, or trip tables.

| Field | Type | Default | Impact | Notes |
|---|---|---|---|---|
| `modes` | mapping | `{}` | Summary, Presentation | Mode ID to a definition containing optional `label` and required non-empty `columns`. |
| `modes.<id>.label` | string | title-cased mode ID | Presentation | Unique dashboard/export label. |
| `modes.<id>.columns.households` | string | none | Summary | Household source column; propagates to dependent tables unless overridden. |
| `modes.<id>.columns.persons` | string | none | Summary | Person source column; propagates to trips, tours, and days unless overridden. |
| `modes.<id>.columns.trips` | string | none | Summary | Trip source column; tour weight becomes the mean selected trip weight by `tour_id`. |

```yaml
weighting:
  modes:
    calibrated:
      label: Calibrated
      columns:
        households: calibrated_hh_weight
        persons: calibrated_person_weight
        trips: calibrated_trip_weight

summarize:
  weighting_modes: [weighted, unweighted, calibrated]
```

Each definition requires at least one supported source table. The visualizer
validates named columns for each prepared run. See the
[weighting cookbook](43-weighting-hosting-extensions.md#worked-example-add-a-weighting-mode).

## `extensions`

Use this advanced method for calculations that `weighting.modes` column
selection cannot define.

| Field | Type | Default | Impact | Notes |
|---|---|---|---|---|
| `modules` | list of strings | `[]` | Summary | Importable modules that define `register_weighting_modes(registry)`. The loader finds installed weighting entry points separately. |
| `settings` | mapping | `{}` | Summary | Arbitrary YAML settings available to transforms as `config.extension_settings`. Included in summary cache identity. |

```yaml
extensions:
  modules: [my_project.weighting]
  settings:
    calibrated:
      multiplier: 1.0
```

See [Advanced: Custom Weight Calculations](43-weighting-hosting-extensions.md#advanced-custom-weight-calculations).

## `pipeline`

`pipeline` selects workflow steps and output mode.

| Field | Type | Default | Allowed values | Impact | Notes |
|---|---|---|---|---|---|
| `steps` | non-empty list of strings | `[summarize, dashboard]` | `prepare`, `skimjoin`, `segment`, `summarize`, `dashboard` | Runtime | Steps must be lowercase, unique, and valid. `skimjoin` requires `prepare`; `segment` requires `summarize`; `dashboard` must be last when present. |
| `dashboard_mode` | string | `live` | `none`, `live`, `export`, `host` | Runtime, Presentation | Controls the dashboard step. `host` writes a warning and uses the standard live server. It does not publish an application. |
| `refresh` | list of strings or `all` | `[]` | `prepare`, `skimjoin`, `summarize`, `all` | Runtime | Forces only the named stored stages to rebuild. An upstream refresh invalidates enabled downstream stages. Leave empty for standard cache-aware operation. |

```yaml
pipeline:
  steps: [prepare, skimjoin, segment, summarize, dashboard]
  dashboard_mode: export
  refresh: []
```

The visualizer stores `segment` output in summary bundles. Use
`refresh: [summarize]` to rebuild segmented output. Dashboard rendering does
not have a persistent processor cache, so dashboard is not a refresh target.

## `runs`

Each run entry describes one scenario. Set `label` whenever possible; it becomes
the display name and identifies the run in cache and debug output.

| Field | Type | Default | Impact | Notes |
|---|---|---|---|---|
| `dir` | path string | none | Prepare | Raw ActivitySim output directory. Set this field unless `prepared_table_map` or `summary_table_map` supplies the run. |
| `label` | string | folder name or `run` fallback | Summary, Presentation | Dashboard and cache-facing run name. Keep stable across reruns. |
| `file_map` | mapping | inherits top-level `files` | Prepare | Per-run raw file stem overrides. Cannot be combined with `prepared_table_map`. |
| `prepared_table_map` | mapping | none | Prepare, Summary | Explicit `.parquet` or `.csv` canonical prepared tables. Skips raw prepare for that run. |
| `summary_table_map` | mapping | none | Summary, Presentation | Maps registered summary IDs to dashboard-ready `.parquet` or `.csv` files. Use it alone or to replace generated summaries. |
| `skim_file` | path string | `prepare.distance_skim.file` | Prepare, Summary | Per-run legacy distance-skim override. Relative paths resolve from this run's `dir`. |
| `skimjoin` | mapping | inherits global `skimjoin` | Prepare | Per-run skimjoin path and hypothetical-sidecar overrides. |
| `hh_weight_col` | string | none | Prepare, Summary | Household source for the run's primary `weighted` mode. |
| `person_weight_col` | string | none | Prepare, Summary | Person source for the run's primary `weighted` mode. |
| `trip_weight_col` | string | none | Prepare, Summary | Trip source for the run's primary `weighted` mode. |

You can use these table IDs in `file_map` and `prepared_table_map`:

`households`, `persons`, `day`, `tours`, `trips`, `vehicles`,
`joint_tour_participants`, `land_use`.

Each `prepared_table_map` path must include `.parquet` or `.csv`. A relative
path starts from the configuration file directory.

`summary_table_map` uses registered IDs from the summary catalog. Each path must
end in `.parquet` or `.csv`. A relative path starts from the configuration file
directory.

### Run Labels And Run Keys

`label` is the dashboard name. The visualizer converts it to a lowercase,
file-system-safe run key. Cache directories, manifests, and settings use this
key. One example is
`prepare.vot_bins.mappings`:

| Label | Run key |
|---|---|
| `Base` | `base` |
| `Build Scenario` | `build-scenario` |
| `2026 / Toll Test` | `2026-toll-test` |

If normalized labels are equal, each key gets an ordered numeric suffix
(`build-1`, `build-2`). Keep labels unique and stable. If you change their
order, you can change the suffixes and the cache or mapping identity.

```yaml
runs:
  - dir: C:\models\base\output
    label: Base
  - dir: C:\models\build\output
    label: Build
    file_map:
      trips: final_trips_linked
```

## `files` And `fallback_files`

`files` maps logical table IDs to raw ActivitySim output file names. If a value
has no extension, the reader searches each run directory for `.parquet` first
and then `.csv`.

| Table id | Default stem |
|---|---|
| `households` | `final_households` |
| `persons` | `final_persons` |
| `day` | `final_day` |
| `tours` | `final_tours` |
| `trips` | `final_trips` |
| `vehicles` | `final_vehicles` |
| `joint_tour_participants` | `final_joint_tour_participants` |
| `land_use` | `final_land_use` |

`fallback_files` supports only these optional table IDs: `day`, `vehicles`,
`joint_tour_participants`, and `land_use`. Each value must be an explicit
`.parquet` or `.csv` path. Use `fallback_files` when multiple runs share input files.

```yaml
files:
  trips: trips_with_links

fallback_files:
  land_use: C:\shared_inputs\land_use.parquet
```

Impact: Prepare.

## `zones`

`zones` controls MAZ/TAZ normalization.

| Field | Type | Default | Impact | Notes |
|---|---|---|---|---|
| `use_maz` | boolean | `true` | Prepare, Summary | Set `false` for TAZ-only models. |
| `maz_col` | string or list of strings | `[MAZ, zone_id]` | Prepare | Ordered candidate columns for MAZ ids in land use. |
| `taz_col` | string or list of strings | `[TAZ, taz]` | Prepare | Ordered candidate columns for TAZ ids in land use. |

```yaml
zones:
  use_maz: false
  maz_col: zone_id
  taz_col: TAZ
```

## `columns`

Most `columns` values can be a single string or an ordered list of possible
source names. The visualizer uses the first available column and reads the
scalar fields at the start of the table as single names.

| Field | Default | Impact | Purpose |
|---|---|---|---|
| `ptype` | `ptype` | Prepare, Summary | Person type. |
| `hhsize` | `hhsize` | Prepare, Summary | Household size. |
| `auto_ownership` | `auto_ownership` | Prepare, Summary | Household vehicle ownership. |
| `num_workers` | `num_workers` | Prepare, Summary | Household workers. |
| `num_adults` | `num_adults` | Prepare, Summary | Household adults. |
| `sample_rate` | none | Prepare, Summary | Optional sample-rate source for weights. |
| `household_id` | `household_id` | Prepare | Household key. |
| `person_id` | `person_id` | Prepare | Person key. |
| `tour_id` | `tour_id` | Prepare | Tour key. |
| `trip_id` | `trip_id` | Prepare | Trip key. |
| `tour_purpose` | `tour_purpose`, `primary_purpose`, `tour_type`, `purpose` | Prepare, Summary | Tour purpose. |
| `trip_purpose` | `trip_purpose`, `purpose` | Prepare, Summary | Trip purpose. |
| `tour_mode` | `tour_mode` | Prepare, Summary | Tour mode. |
| `trip_mode` | `trip_mode` | Prepare, Summary | Trip mode. |
| `tour_category` | `tour_category` | Prepare, Summary | Mandatory, non-mandatory, at-work, or other tour category. |
| `tour_start` | `start`, `start_hour` | Prepare, Summary | Tour start period/hour. |
| `tour_end` | `end`, `end_hour` | Prepare, Summary | Tour end period/hour. |
| `tour_duration` | `duration`, `tourdur` | Prepare, Summary | Tour duration. |
| `trip_depart` | `depart`, `depart_hour` | Prepare, Summary | Trip departure period/hour. |
| `total_employment` | `EMP_TOTAL`, `EMP_Total`, `EMPLOY_TOT`, `TOTEMP`, `total_employment`, `employment` | Prepare, Summary | Land-use employment. |
| `income_segment` | `income_segment`, `income_broad`, `income` | Prepare, Summary | Household income segment. |
| `home_zone_id` | `home_zone_id` | Prepare | Home zone. |
| `workplace_zone_id` | `workplace_zone_id` | Prepare | Workplace zone. |
| `school_zone_id` | `school_zone_id` | Prepare | School zone. |
| `has_license` | `has_license` | Prepare | License flag. |
| `mandatory_tour_frequency` | `mandatory_tour_frequency` | Prepare, Summary | Mandatory tour frequency. |
| `is_student` | `is_student`, `student` | Prepare, Summary | Student flag. |
| `is_university` | `is_university`, `major_uni` | Prepare, Summary | University student flag. |
| `school_segment` | `school_segment` | Prepare, Summary | School segment. |
| `schg` | `SCHG` | Prepare, Summary | School grade/category. |
| `pstudent` | `pstudent` | Prepare, Summary | ActivitySim student category. |
| `tour_origin` | `origin` | Prepare | Tour origin. |
| `tour_destination` | `destination` | Prepare | Tour destination. |
| `trip_origin` | `origin` | Prepare | Trip origin. |
| `trip_destination` | `destination` | Prepare | Trip destination. |
| `stop_frequency` | `stop_frequency` | Prepare, Summary | Tour stop frequency. |
| `trip_outbound` | `outbound` | Prepare, Summary | Trip outbound/inbound flag. |
| `trip_num` | `trip_num` | Prepare | Trip sequence number. |
| `pnr_zone_id` | `pnr_zone_id` | Prepare, Skimjoin | Park-and-ride zone id. |
| `pnr_lot_capacity` | `PNR_SPACES` | Prepare, Summary | Park-and-ride lot capacity. |
| `is_worker` | `is_worker` | Prepare, Summary | Worker flag. |
| `adult` | `adult`, `is_adult` | Prepare, Summary | Adult flag. |
| `day_id` | `day_id` | Prepare, Summary | Day table id. |
| `day_weight` | `day_weight` | Prepare, Summary | Day-level weight. |
| `vehicle_id` | `vehicle_id` | Prepare, Summary | Vehicle id. |
| `vehicle_num` | `vehicle_num` | Prepare, Summary | Vehicle number. |
| `vehicle_type` | `vehicle_type` | Prepare, Summary | Vehicle type. |
| `school_esc_outbound` | `school_esc_outbound` | Prepare, Summary | School escort outbound indicator. |
| `school_esc_inbound` | `school_esc_inbound` | Prepare, Summary | School escort inbound indicator. |
| `num_escortees` | `num_escortees`, `num_escorted` | Prepare, Summary | Number of escortees. |
| `out_escorted_tour_ids` | `out_escorted_tour_ids` | Prepare, Summary | Outbound escorted tour ids. |
| `inb_escorted_tour_ids` | `inb_escorted_tour_ids` | Prepare, Summary | Inbound escorted tour ids. |
| `out_escorting_type` | `out_escorting_type` | Prepare, Summary | Outbound escorting type. |
| `inb_escorting_type` | `inb_escorting_type` | Prepare, Summary | Inbound escorting type. |
| `out_chauffeur_tour_id` | `out_chauffeur_tour_id` | Prepare, Summary | Outbound chauffeur tour id. |
| `inb_chauffeur_tour_id` | `inb_chauffeur_tour_id` | Prepare, Summary | Inbound chauffeur tour id. |

```yaml
columns:
  household_id: [household_id, hh_id]
  tour_purpose: [primary_purpose, purpose]
  trip_mode: mode
```

## `prepare`

`prepare` controls canonical prepared table output and enrichment.

| Field | Type | Default | Allowed values | Impact | Notes |
|---|---|---|---|---|---|
| `output.file_format` | string | `parquet` | `parquet`, `csv` | Prepare | File format for prepared cache tables. |
| `validation.relationship_checks` | string or `false` | `warn` | `off`, `warn`, `error`, or `false` for `off` | Prepare | Controls relationship-check failures during prepare. |
| `distance_skim.file` | path string | none | OMX path | Prepare, Summary | Optional distance skim used by prepare. |
| `distance_skim.matrix` | string | `SOV_DIST__MD` | matrix name | Prepare, Summary | Matrix read from `distance_skim.file`. |
| `auto_sufficiency_basis` | string | `licensed_drivers` | `licensed_drivers`, `workers`, `adults` | Prepare, Summary | Basis for household auto-sufficiency derivation. |
| `student_types` | list of mappings | `[]` | student-type definitions | Prepare, Summary | School/university enrollment definitions used by prepared fields and shadow-pricing summaries. |
| `time_periods` | mapping | disabled | ActivitySim `network_los.yaml` source | Prepare, Summary | Derives canonical period labels for prepared tours and trips. |
| `non_motorized_distance_skim` | mapping | disabled | configured lookup | Prepare, Summary | Optional non-motorized distance enrichment. |
| `vot_bins.source_column` | string | `income_segment` | any source column | Prepare, Skimjoin | Source value used to derive VOT bins. |
| `vot_bins.output_column` | string | `vot_bin` | any output column | Prepare, Skimjoin | Prepared column written for skimjoin dimensions. |
| `vot_bins.fallback_value` | scalar string | none | any value | Prepare, Skimjoin | Value used when no run-specific mapping applies. |
| `vot_bins.mappings` | mapping | `{}` | run key to value mapping | Prepare, Skimjoin | Enables VOT bin calculation. The loader normalizes run keys from run labels. |

```yaml
prepare:
  output:
    file_format: parquet
  validation:
    relationship_checks: warn
  distance_skim:
    file: C:\skims\auto.omx
    matrix: SOV_DIST__MD
  auto_sufficiency_basis: licensed_drivers
  vot_bins:
    source_column: income_segment
    output_column: vot_bin
    fallback_value: M
    mappings:
      base:
        1: L
        2: M
        3: H
```

`prepare.time_periods` accepts:

| Field | Type | Default | Notes |
|---|---|---|---|
| `network_los_file` | path string | required | ActivitySim YAML containing `skim_time_periods.periods` and `skim_time_periods.labels`. Relative paths resolve from the main config. |
| `trip_period_number_column` | string | `depart` | Prepared trip source used to write `trip_period`. |
| `tour_start_period_number_column` | string | `start` | Prepared tour source used to write `start_period`. |
| `tour_end_period_number_column` | string | `end` | Prepared tour source used to write `end_period`. |

The period breakpoint list must contain at least two integers. The label list
must contain one less entry. If trips contain `tour_id`, `outbound`, and the
derived `trip_period`, prepare also writes `first_inbound_trip_period` for each
tour. Prepare records missing configured source columns in the diagnostics. It
does not create values for missing columns.

`prepare.non_motorized_distance_skim` accepts:

| Field | Type | Default | Notes |
|---|---|---|---|
| `file` | path string | required | `.csv`, `.omx`, `.h5`, or `.hdf5` lookup. Relative paths resolve from the main config. |
| `matrix` | string or null | required for OMX/HDF5; `DISTWALK` for CSV | OMX matrix name. For CSV, names the value column; a `<file-stem>__` prefix is stripped when present. |

CSV lookup files must contain `OMAZ`, `DMAZ`, and the selected value column.
Prepared trips must contain `o_maz` and `d_maz`. OMX and HDF5 lookups use the
prepared `OTAZ` and `DTAZ` columns. Both methods write
`prepared_non_motorized_distance`. They record diagnostics for unresolved
lookups.

## `skimjoin`

The `skimjoin` section connects the visualizer runtime to a separate skimjoin
configuration file. See
[25 - Skimjoin Config Reference](25-skimjoin-config-reference.md) for the
lookup-rule schema.

```text
main visualizer config
  pipeline.steps: enables the integrated skimjoin stage
  skimjoin.defaults: selects the standalone config and optional path overrides
    -> standalone skimjoin config
       project/activitysim/defaults/modes: defines the actual lookup rules
```

Setting `skimjoin.defaults.config_path` does not start skimjoin; the
`pipeline.steps` list must also contain `prepare` and `skimjoin`.

| Field | Type | Default | Impact | Notes |
|---|---|---|---|---|
| `defaults.config_path` | path string | none | Prepare, Summary | Shared skimjoin config path. |
| `defaults.skim_files` | list of path strings | from skimjoin config | Prepare, Summary | Overrides `project.skim_files` in the skimjoin config for integrated runtime. |
| `defaults.network_los_file` | path string | from skimjoin config | Prepare, Summary | Overrides `project.network_los_file`. |
| `failure_policy` | string | `record` | Runtime, Prepare | `record` keeps a failed enrichment as diagnostics; `error` stops the run. |
| `create_hypothetical_skim_tables` | boolean | `false` | Prepare | Enables configured hypothetical skim tables. |

Run-level `runs[*].skimjoin` supports `config_path`, `skim_files`,
`network_los_file`, and `create_hypothetical_skim_tables`. If you omit the last
field, it uses the global value. To enable skimjoin, add it to `pipeline.steps`.
Do not use the removed `skimjoin.enabled` or `skimjoin.config_path` keys.

Integrated skim files must resolve to `.omx`, `.csv`, `.h5`, or `.hdf5`.

## `segment`

Use `segment` as the canonical section in user YAML. The loader converts it to
the segmentation runtime settings.

| Field | Type | Default | Allowed values | Impact | Notes |
|---|---|---|---|---|---|
| `dashboard.segmentation_type` | string | first configured definition | configured definition name | Presentation | Selected segment type shown in dashboard/export. |
| `dashboard.visibility` | string | `full_and_segments` | `full_only`, `segments_only`, `full_and_segments` | Presentation | Whether the dashboard shows full-run outputs, segmented outputs, or both. |
| `definitions` | mapping | required when you enable the segment step | path-safe lowercase names | Summary | Segment definitions. |
| `definitions.*.include_full` | boolean | `true` | `true`, `false` | Summary | Also build full-run summaries. |
| `definitions.*.persist_segmented_prepared_tables` | boolean | `false` | `true`, `false` | Prepare, Summary | Persist segment-specific prepared tables. |
| `definitions.*.allow_overlapping` | boolean | `false` | `true`, `false` | Summary | Allows one source value to appear in multiple segments. |
| `definitions.*.on_empty_segment` | string | `warn` | `error`, `warn`, `skip` | Summary | Behavior when a segment has no rows. |
| `definitions.*.source` | mapping | required | `prepared_column` or `csv_lookup` | Summary | Source of segment values. |
| `definitions.*.segments` | list | required | list of segment mappings | Summary, Presentation | Segment ids, labels, and matched values. |

Prepared-column source:

```yaml
segment:
  dashboard:
    segmentation_type: person_sex
    visibility: segments_only
  definitions:
    person_sex:
      source:
        type: prepared_column
        source_table: per
        column: sex
      segments:
        - id: female
          label: Female
          values: [2]
        - id: male
          label: Male
          values: [1]
```

`source_table` may be `hh`, `per`, `tours`, `trips`, or `land_use`.

CSV lookup source:

```yaml
segment:
  definitions:
    district:
      source:
        type: csv_lookup
        file: lookups\household_district.csv
        join:
          source_table: hh
          source_key_column: household_id
          csv_key_column: household_id
        segment_value_column: district
      segments:
        - id: north
          label: North
          values: [north]
```

## `summarize`

| Field | Type | Default | Allowed values | Impact | Notes |
|---|---|---|---|---|---|
| `weighting_modes` | list of strings | `[weighted, unweighted]` | built-in, declarative, or registered custom mode IDs | Summary, Presentation | Summary variants to build in the listed order. Empty lists use definitions with `default_enabled=True`. |
| `failure_policy` | string | `record` | `record`, `error` | Summary | Record failed summaries as diagnostics or stop on the first builder exception. |
| `category_normalization` | mapping | `{}` plus escort defaults | category definitions | Summary | Canonical summary-value normalization and regrouping; affects cache identity. |
| `pnr_tour_modes` | list of strings | `[PNR_TRANSIT]` | any mode names | Summary | Modes treated as park-and-ride tours. Must resolve to at least one mode. |
| `group_joint_tour_purposes` | boolean | `true` | `true`, `false` | Summary | Group joint tour purposes in summaries. |
| `group_atwork_tour_purposes` | boolean | `true` | `true`, `false` | Summary | Group at-work tour purposes in summaries. |
| `group_school_tour_purposes` | boolean | `true` | `true`, `false` | Summary | Group school tour purposes in summaries. |
| `geography.enabled` | boolean | `false` | `true`, `false` | Summary, Presentation | Enables custom geography mapping and aggregations. |
| `geography.landuse_col` | string | none | land-use column | Summary | Existing land-use geography column used for geography summaries. |
| `geography.mapping` | mapping | none | raw value to label | Summary, Presentation | Label mapping for geography values. |
| `geography.aggregations` | mapping | none | aggregation definitions | Summary, Presentation | Additional zone-to-geography lookup definitions. |

Each `geography.aggregations.*` entry requires these fields:

| Field | Type | Notes |
|---|---|---|
| `source_zone_system` | string | `maz` or `taz`. |
| `mapping` | mapping | Inline label to zone id or list of zone ids. Mutually exclusive with `file`. |
| `file` | path string | CSV lookup file. Mutually exclusive with `mapping`. |
| `zone_id_col` | string | Required with `file`. |
| `geography_col` | string | Required with `file`. |

```yaml
summarize:
  weighting_modes: [weighted, unweighted]
  pnr_tour_modes: [PNR_TRANSIT]
  geography:
    enabled: true
    aggregations:
      district:
        source_zone_system: maz
        file: C:\lookups\maz_district.csv
        zone_id_col: MAZ
        geography_col: DISTRICT
```

## `dashboard`

| Field | Type | Default | Allowed values | Impact | Notes |
|---|---|---|---|---|---|
| `title` | string | `ActivitySim Visualizer` | any string | Presentation | Dashboard title. |
| `include_notes` | boolean | `true` | `true`, `false` | Presentation | Show expandable calculation notes beneath annotated charts and tables. |
| `enable_maz_geographies` | boolean | `false` | `true`, `false` | Presentation | Enables MAZ geography options in dashboard pages that support them. |
| `live.pages` | list | all/default page registry behavior | page or group ids | Presentation | Live dashboard page selection. |
| `export.output_path` | path string | none | HTML path | Presentation | Relative paths resolve under `root`. |
| `export.dashboard.weighting` | string or list | `default` | `default`, `all`, or configured weighting modes | Presentation | Exported weighting states. |
| `export.dashboard.values` | string or list | `default` | `default`, `all`, `percent`, `count` | Presentation | Exported value-display states. |
| `export.dashboard.segmentation_type` | string | selected segment type | configured segment definition | Presentation | Exported segmentation type. |
| `export.dashboard.segmentation_visibility` | string | segment dashboard visibility | `full_only`, `segments_only`, `full_and_segments` | Presentation | Exported segment visibility. |
| `export.pages` | mapping | `{}` | page/group override mapping | Presentation | Export selector and part overrides. |
| `export.exclude_pages` | list of strings | `[]` | page ids | Presentation | Pages excluded from export. |
| `export.exclude_groups` | list of strings | `[]` | group ids | Presentation | Groups excluded from export. |

`dashboard.host` is a reserved configuration block. The schema accepts
`account`, `app_id`, `title`, and `verify`. The runtime does not normalize or
use these values. `pipeline.dashboard_mode: host` writes a warning to the log
and starts the standard live server. See the hosting extension procedure in
chapter 43.

`live.pages` entries may be strings or group mappings:

```yaml
dashboard:
  live:
    pages:
      - overview
      - long_term_choices
      - trip_summaries:
          - trip_mode
          - trip_stop_distance
```

Use a page ID or a nested group and page ID as an export page override key.
Selector keys depend on the page. A selector value can be `default`, `all`, one
string, or a list of strings. Set `parts.*.enabled` to hide named export parts.

Export starts with the page set from `dashboard.live.pages`.
`dashboard.export.pages` is an override mapping, not an allow-list, so an entry
for one page does not remove the others. To remove pages, set `enabled: false`
or use `exclude_pages` or `exclude_groups`. Export cannot add a page omitted by
the live configuration. Find valid IDs in these locations:

- page and group IDs: the generated catalog in chapter 31;
- selector IDs: `self.select(...)` and `self.selector(...)` calls on the page;
- part IDs: `self.section(...)` calls, including feature-prefixed IDs such as
  `comparison.body`; and
- current runtime expectations: `tests/test_page_registry_contract.py` and
  export payload tests.

```yaml
dashboard:
  export:
    output_path: exports\dashboard.html
    pages:
      long_term_choices:
        shadow_pricing:
          geography_level: [all]
          student_type: all
          parts:
            workplace_table:
              enabled: false
```

## `display`

| Field | Type | Default | Impact | Notes |
|---|---|---|---|---|
| `labels` | mapping | built-in defaults plus data values | Presentation | Category display labels and order. |
| `run_colors` | list of strings | default color cycle | Presentation | Dashboard run colors; reused cyclically. |
| `missing_data_display` | string | `card` | Presentation | `card` shows missing-data diagnostics; `blank` omits them. |
| `bar_hover_mode` | string | `closest` | Presentation | `closest` or `all` hover behavior for bar charts. |
| `density_hover_mode` | string | `closest` | Presentation | `closest` or `all` hover behavior for density plots. |

Each label category supports:

| Field | Type | Default | Notes |
|---|---|---|---|
| `mapping` | mapping | `{}` | Raw value to display label. Keys are compared as strings. |
| `order` | string | `data` | `data`, `ascending`, or `descending` for unmapped extra values. |

```yaml
display:
  labels:
    mode:
      mapping:
        SOV: Drive Alone
        WALK_TRANSIT: Walk-Transit
      order: data
  run_colors:
    - "#298c8c"
    - "#a00000"
```

## `modes`

`modes` supplies legacy mode order and summary groups. Use
`display.labels.mode.mapping` to define labels and order together.

| Field | Type | Default | Impact | Notes |
|---|---|---|---|---|
| `order` | list of strings | none | Presentation | Raw mode order used only when `display.labels.mode` is absent. |
| `groups` | mapping of lists | none | Summary | Named mode groups included in summary cache identity. The `Auto` group explicitly selects auto modes for `auto_vmt_totals` and segmented auto-VMT summaries; without it, those summaries use built-in name matching. |

```yaml
modes:
  order: [SOV, HOV2, HOV3, WALK, BIKE, WALK_TRANSIT]
  groups:
    Auto: [SOV, HOV2, HOV3, TAXI, TNC_SINGLE, TNC_SHARED]
```

## Advanced Category Config

`summarize.category_normalization` uses the same category format as
`display.labels`. It changes normalized values in summary output. Use it for
normalization or groups that change summaries. Do not use it only to change
display labels.

```yaml
summarize:
  category_normalization:
    geography:
      mapping:
        1: County 1
        2: County 2
```

Impact: Summary.

## `prepare.student_types`

`prepare.student_types` customizes school-related prepared fields and summaries.

| Field | Type | Default | Impact | Notes |
|---|---|---|---|---|
| `label` | string | required | Prepare, Summary | Display label for the student type. |
| `land_use_columns` | string or list | `[]` | Prepare, Summary | Land-use columns used for this student type. |
| `person` | mapping | optional | Prepare, Summary | Person-side selector. See the exact default and multi-entry rules below. |
| `person.is_university` | boolean | none | Prepare, Summary | Match university flag. |
| `person.school_segment` | scalar or list | none | Prepare, Summary | Match school segment values. |
| `person.SCHG` | scalar or list | none | Prepare, Summary | Match `SCHG` values. |
| `person.pstudent` | scalar or list | none | Prepare, Summary | Match `pstudent` values. |

```yaml
prepare:
  student_types:
    - label: K-12
      land_use_columns: [K12_ENROLL]
      person:
        school_segment: [K12]
    - label: University
      land_use_columns: [UNIV_ENROLL]
      person:
        is_university: true
```

The visualizer applies these rules in sequence:

1. When `prepare.student_types` is empty, prepare gets `School` from available
   `ENROLLGRADEKto8`/`ENROLLGRADE9to12` columns and `University` from
   `COLLEGEENROLL`.
2. When an entry omits `person`, prepare examines labels and land-use column
   names. Names that contain `univ` or `college` match `is_university`. Other
   entries match `is_student` and exclude university students.
3. If there are more than two entries, each non-university default entry must
   provide `person`. If it does not, configuration validation fails.
4. A `person` mapping combines all conditions with AND. You can use scalar or
   list values for `school_segment`, `SCHG`, and `pstudent`.
5. If multiple entries match one person, the visualizer uses the first entry.

For example, three school levels must select their person rows explicitly:

```yaml
prepare:
  student_types:
    - label: Elementary
      land_use_columns: [ELEM_ENROLL]
      person:
        SCHG: [1, 2]
    - label: High School
      land_use_columns: [HIGH_ENROLL]
      person:
        SCHG: [3]
    - label: University
      land_use_columns: [COLLEGEENROLL]
      person:
        is_university: true
```

## Related Chapters

- [11 - Configuring Your Data](11-configuring-your-data.md)
- [12 - Running Workflows](12-running-workflows.md)
- [21 - Prepared Tables](21-prepared-tables.md)
- [25 - Skimjoin Config Reference](25-skimjoin-config-reference.md)
