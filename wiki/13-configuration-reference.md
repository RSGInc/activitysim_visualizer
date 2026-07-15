# 13 - Configuration Reference

This page is the field-by-field reference for the main ActivitySim Visualizer
config file. For a shorter orientation, start with
[11 - Configuring Your Data](11-configuring-your-data.md). The canonical
example is [`config.yaml`](../config.yaml).

This page documents the current canonical config layout. Unknown and removed
keys fail validation and, where possible, name their canonical replacement.

## Reading This Reference

Path resolution depends on the field:

| Field family | Relative to | Notes |
|---|---|---|
| `root` | main config directory | Becomes an absolute artifact/cache root during config loading. |
| `runs[*].dir` | main config directory | Raw ActivitySim output directory. |
| `files.*`, `runs[*].file_map.*` | the resolved run directory | File stems may omit `.parquet` or `.csv`; Parquet is tried before CSV. |
| `fallback_files.*`, `prepared_table_map.*`, `summary_table_map.*` | main config directory | Values must include `.parquet` or `.csv`. |
| main-config skim, lookup, and skimjoin override paths | main config directory | Includes `prepare.distance_skim.file`, segmentation CSVs, and `skimjoin.defaults.*`. |
| paths inside the standalone skimjoin config | standalone skimjoin config directory | See chapter 25. |
| `dashboard.export.output_path` | resolved `root` | Absolute output paths remain absolute. |

Cache impact uses these labels:

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

Use `prepared_table_map` when a run should skip raw prepare and load canonical
prepared tables directly.

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
| `summarize` | mapping | weighted and unweighted summaries | Summary | Summary weighting, purpose grouping, geography, and PNR mode behavior. |
| `dashboard` | mapping | live dashboard defaults | Presentation | Dashboard title, page selection, MAZ geography toggle, and export settings. |
| `display` | mapping | built-in labels and colors | Presentation | Dashboard labels, category order, and run colors. |
| `extensions` | mapping | `{}` | Summary, Presentation | Importable weighting extension modules and their settings. Extension code is trusted. |
| `modes` | mapping | `{}` | Presentation | Optional mode ordering used when `display.labels.mode` is absent. |

## `extensions`

| Field | Type | Default | Impact | Notes |
|---|---|---|---|---|
| `modules` | list of strings | `[]` | Summary | Importable modules that define `register_weighting_modes(registry)`. Installed weighting entry points are discovered separately. |
| `settings` | mapping | `{}` | Summary | Arbitrary YAML settings available to transforms as `config.extension_settings`. Included in summary cache identity. |

```yaml
extensions:
  modules: [my_project.weighting]
  settings:
    calibrated:
      multiplier: 1.0
```

See the complete [weighting plugin cookbook](43-weighting-hosting-extensions.md#worked-example-add-a-weighting-mode).

## `pipeline`

`pipeline` selects workflow steps and output mode.

| Field | Type | Default | Allowed values | Impact | Notes |
|---|---|---|---|---|---|
| `steps` | non-empty list of strings | `[summarize, dashboard]` | `prepare`, `skimjoin`, `segment`, `summarize`, `dashboard` | Runtime | Steps must be lowercase, unique, and valid. `skimjoin` requires `prepare`; `segment` requires `summarize`; `dashboard` must be last when present. |
| `dashboard_mode` | string | `live` | `none`, `live`, `export`, `host` | Runtime, Presentation | Controls what the dashboard step does. `host` is reserved and currently warns, then falls back to the ordinary live server; it does not publish an application. |
| `overwrite` | boolean | `false` | `true`, `false` | Runtime | Bypasses reusable prepared/summary caches for configured processor steps and writes rebuilt artifacts. Return it to `false` after a forced rebuild. |

```yaml
pipeline:
  steps: [prepare, skimjoin, segment, summarize, dashboard]
  dashboard_mode: export
  overwrite: false
```

## `runs`

Each run entry describes one scenario. `label` is strongly recommended because
it becomes the display name and helps cache/debug output remain understandable.

| Field | Type | Default | Impact | Notes |
|---|---|---|---|---|
| `dir` | path string | none | Prepare | Raw ActivitySim output folder. Required unless the run is supplied by `prepared_table_map`, by `summary_table_map` alone, or both. |
| `label` | string | folder name or `run` fallback | Summary, Presentation | Dashboard and cache-facing run name. Keep stable across reruns. |
| `file_map` | mapping | inherits top-level `files` | Prepare | Per-run raw file stem overrides. Cannot be combined with `prepared_table_map`. |
| `prepared_table_map` | mapping | none | Prepare, Summary | Explicit `.parquet` or `.csv` canonical prepared tables. Skips raw prepare for that run. |
| `summary_table_map` | mapping | none | Summary, Presentation | Registered summary IDs mapped to dashboard-ready `.parquet` or `.csv` files. May be used alone or override generated summaries. |
| `skimjoin` | mapping | inherits global `skimjoin` | Prepare | Per-run skimjoin `config_path`, `skim_files`, and `network_los_file` overrides. |
| `hh_weight_col` | string | none | Prepare, Summary | Explicit household weight source column. |
| `person_weight_col` | string | none | Prepare, Summary | Explicit person weight source column. |
| `trip_weight_col` | string | none | Prepare, Summary | Explicit trip weight source column. |

Allowed `file_map` and `prepared_table_map` table ids are:

`households`, `persons`, `day`, `tours`, `trips`, `vehicles`,
`joint_tour_participants`, `land_use`.

`prepared_table_map` paths must include `.parquet` or `.csv`. Relative paths are
resolved relative to the config file.

`summary_table_map` uses registered IDs from the summary catalog. Its paths must
also end in `.parquet` or `.csv` and are resolved relative to the config file.

### Run Labels And Run Keys

`label` is the dashboard name. Its filesystem-safe lowercase slug is the run
key used by cache directories, manifests, and settings such as
`prepare.vot_bins.mappings`:

| Label | Run key |
|---|---|
| `Base` | `base` |
| `Build Scenario` | `build-scenario` |
| `2026 / Toll Test` | `2026-toll-test` |

If normalized labels collide, every colliding key receives an ordered numeric
suffix (`build-1`, `build-2`). Keep labels unique and stable: changing their
order can change those suffixes and therefore cache/mapping identity.

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

`files` maps logical table ids to raw ActivitySim output file stems. If the value
has no extension, the reader tries `.parquet` first, then `.csv`, inside each
run directory.

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

`fallback_files` supports optional table ids only: `day`, `vehicles`,
`joint_tour_participants`, and `land_use`. Values must be explicit `.parquet` or
`.csv` paths.

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

Most `columns` values may be a string or an ordered list of candidate source
column names. The first available candidate is used. The few scalar fields
listed first are read as single names.

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
| `time_periods` | mapping | built-in periods | period definitions or ActivitySim config source | Prepare, Summary | Canonical time-period labels used by prepared tours and trips. |
| `non_motorized_distance_skim` | mapping | disabled | configured lookup | Prepare, Summary | Optional non-motorized distance enrichment. |
| `vot_bins.source_column` | string | `income_segment` | any source column | Prepare, Skimjoin | Source value used to derive VOT bins. |
| `vot_bins.output_column` | string | `vot_bin` | any output column | Prepare, Skimjoin | Prepared column written for skimjoin dimensions. |
| `vot_bins.fallback_value` | scalar string | none | any value | Prepare, Skimjoin | Value used when no run-specific mapping applies. |
| `vot_bins.mappings` | mapping | `{}` | run key to value mapping | Prepare, Skimjoin | Enables VOT bin derivation. Run keys are normalized from run labels. |

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

## `skimjoin`

The main config `skimjoin` section wires the visualizer runtime to a separate
skimjoin config file. See
[25 - Skimjoin Config Reference](25-skimjoin-config-reference.md) for the
lookup-rule schema.

```text
main visualizer config
  pipeline.steps: enables the integrated skimjoin stage
  skimjoin.defaults: selects the standalone config and optional path overrides
    -> standalone skimjoin config
       project/activitysim/defaults/modes: defines the actual lookup rules
```

Merely providing `skimjoin.defaults.config_path` does not run skimjoin;
`pipeline.steps` must also contain both `prepare` and `skimjoin`.

| Field | Type | Default | Impact | Notes |
|---|---|---|---|---|
| `defaults.config_path` | path string | none | Prepare, Summary | Shared skimjoin config path. |
| `defaults.skim_files` | list of path strings | from skimjoin config | Prepare, Summary | Overrides `project.skim_files` in the skimjoin config for integrated runtime. |
| `defaults.network_los_file` | path string | from skimjoin config | Prepare, Summary | Overrides `project.network_los_file`. |
| `failure_policy` | string | `record` | Runtime, Prepare | `record` keeps a failed enrichment as diagnostics; `error` stops the run. |
| `create_hypothetical_skim_tables` | boolean | `false` | Prepare | Enables configured hypothetical skim tables. |

Run-level `runs[*].skimjoin` supports `config_path`, `skim_files`, and
`network_los_file`. Enable skimjoin by including it in `pipeline.steps`;
top-level `skimjoin.enabled` and `skimjoin.config_path` are removed keys.

Integrated skim files must resolve to `.omx`, `.csv`, `.h5`, or `.hdf5`.

## `segment`

`segment` config is canonical in user YAML. Internally it is normalized to the
segmentation runtime settings.

| Field | Type | Default | Allowed values | Impact | Notes |
|---|---|---|---|---|---|
| `dashboard.segmentation_type` | string | first configured definition | configured definition name | Presentation | Selected segment type shown in dashboard/export. |
| `dashboard.visibility` | string | `full_and_segments` | `full_only`, `segments_only`, `full_and_segments` | Presentation | Whether the dashboard shows full-run outputs, segmented outputs, or both. |
| `definitions` | mapping | required when segment step is enabled | path-safe lowercase names | Summary | Segment definitions. |
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
| `weighting_modes` | list of strings | `[weighted, unweighted]` | registered mode IDs | Summary, Presentation | Summary variants to build in the listed order. Empty lists use definitions with `default_enabled=True`. |
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

Each `geography.aggregations.*` entry requires:

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

Export page overrides are keyed by page id or by nested group/page id. Selector
keys depend on the page. Selector values may be `default`, `all`, a single
string, or a list of strings. `parts.*.enabled` can hide named export parts.

Export starts from `dashboard.live.pages`, so it can narrow the live page set
but cannot add a page that live configuration did not select. Find valid IDs in:

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

## Advanced Category Config

`summarize.category_normalization` uses the same category shape as
`display.labels`, but changes normalized values written into summary outputs.
Use it for summary-affecting normalization or grouping, not cosmetic relabeling.

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

Matching rules are deterministic:

1. When `prepare.student_types` is empty, prepare infers `School` from available
   `ENROLLGRADEKto8`/`ENROLLGRADE9to12` columns and `University` from
   `COLLEGEENROLL`.
2. When a configured entry omits `person`, labels or land-use column names
   containing `univ` or `college` match `is_university`; other entries match
   `is_student` and exclude university students.
3. With more than two configured entries, every non-university-defaulting entry
   must provide `person`; otherwise config validation fails.
4. A `person` mapping combines all supplied conditions with AND. Scalar and
   list values are both accepted for `school_segment`, `SCHG`, and `pstudent`.
5. If multiple entries match one person, the first configured entry wins.

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
