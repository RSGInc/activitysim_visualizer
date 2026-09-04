# 24 - Segmentation

Segmentation runs the standard summary catalog for selected subsets of a model
run. For example, it can produce the same summaries for urban and rural
households, for income groups, or for people in different survey samples.

Segmentation does not add a grouping column to one summary. It creates a
related `RunData` slice for each configured segment, then runs every registered
default summary against that slice.

## Runtime Placement

```text
raw or prepared input
  -> prepare
  -> optional skimjoin
  -> resolve segment membership
  -> slice related prepared tables in memory
  -> summarize the full run and each segment
  -> write full and segmented summary caches
  -> show the selected segmentation in the dashboard
```

Segmentation is part of the summarize workflow. Enable it by adding `segment`
to `pipeline.steps`; a `segment` configuration block does not enable the step
by itself. The step also requires `summarize`.

```yaml
pipeline:
  steps: [segment, summarize, dashboard]
  dashboard_mode: live
  refresh: []
```

Add `prepare` when you want cache creation to be explicit. If the workflow also
uses skimjoin, include both `prepare` and `skimjoin` before `segment`.

## Complete Prepared-Column Example

This example divides each run by a canonical person column:

```yaml
pipeline:
  steps: [segment, summarize, dashboard]
  dashboard_mode: live
  refresh: []

segment:
  dashboard:
    segmentation_type: person_sex
    visibility: full_and_segments
  definitions:
    person_sex:
      source:
        type: prepared_column
        source_table: per
        column: sex
      allow_overlapping: false
      on_empty_segment: warn
      segments:
        - id: female
          label: Female
          values: [2]
        - id: male
          label: Male
          values: [1]
```

`person_sex` is the segmentation type. Each segment selects source rows whose
`sex` value appears in its `values` list. The dashboard presents the results as
series such as `Base (Female)` and `Base (Male)`.

## How Table Slicing Works

The source table is the anchor for membership. After matching its rows, the
runtime follows canonical IDs to create a consistent set of related tables:

| Source table | Membership starts with | Related data retained |
|---|---|---|
| `hh` | matching households | Their people, days, vehicles, tours, trips, and joint tours. |
| `per` | matching people | Their households, days, tours, trips, vehicles, and joint participation rows. |
| `day` | matching day rows | Related people or households, then their tours, trips, vehicles, and joint tours. |
| `tours` | matching tours | Their people, households, trips, participants, days, and vehicles. |
| `trips` | matching trips | Their tours, people, households, participants, days, and vehicles. |
| `vehicles` | matching vehicles | Their households and all related household records. |
| `joint_participants` | matching participation rows | Their joint tours, tour owners and participants, households, trips, days, and vehicles. |
| `land_use` | matching MAZ or TAZ rows | Households whose home zone matches, then their related records. |

This relationship expansion is important when interpreting totals. A
trip-based segment contains only matching trips, but its household total counts
households associated with those trips. It is not a household classification
unless the source itself is a household field.

The relationship keys must be present. Vehicle sources need `household_id`;
joint-participant sources need `tour_id` and `person_id`; day sources need
`person_id` or `household_id`; and land-use sources need a resolved `MAZ` or
`TAZ` key.

## Source Types

### Prepared Column

Use `prepared_column` when the segment value already exists in a prepared
table:

```yaml
source:
  type: prepared_column
  source_table: hh
  column: income_segment
```

`source_table` accepts `households`, `persons`, `day`, `tours`, `trips`,
`vehicles`, `joint_tour_participants`, and `land_use`, along with their runtime
aliases `hh`, `per`, and `joint_participants`.

You can omit `source_table` if the column occurs in exactly one segmentable
table. Set it explicitly when the name is absent or appears in more than one
table.

### CSV Lookup

Use `csv_lookup` when membership comes from an external classification:

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
          values: [North]
        - id: south
          label: South
          values: [South]
```

Relative lookup paths start from the main configuration directory. The CSV
must contain the join key and segment-value columns. Keys and values cannot be
blank, and one CSV key cannot map to multiple segment values. The join must not
duplicate rows in the anchor table.

## Definition And Segment Settings

| Field | Default | Behavior |
|---|---|---|
| `source` | required | Selects a prepared column or CSV lookup and its anchor table. |
| `segments` | required | Defines the path-safe lowercase `id`, display `label`, and matched `values` for each segment. |
| `allow_overlapping` | `false` | When `false`, one source value cannot appear in more than one segment in the same definition. When `true`, the same row can contribute to multiple segments. |
| `on_empty_segment` | `warn` | `error` stops the run, `skip` omits the analysis unit, and `warn` keeps an empty analysis unit so its summaries can report empty or unavailable results. |
| `include_full` | `true` | Accepted by the schema. The current runtime always builds one full-run analysis unit, regardless of this value. Control dashboard visibility with `segment.dashboard.visibility`. |
| `persist_segmented_prepared_tables` | `false` | Accepted by the schema. The current runtime keeps segment slices in memory and does not write separate prepared-table directories. |

Segment IDs and definition names become path components, so they must already
be lowercase and path-safe. The exact accepted form is one or more lowercase
letters, digits, periods, underscores, or hyphens (`[a-z0-9._-]+`), with no
leading or trailing period, underscore, or hyphen. Names can start with a
digit. Spaces, slashes, uppercase letters, and characters outside that set are
rejected rather than normalized for you.

Value typing is source-specific:

- `prepared_column` compares each YAML value to the prepared column using its
  existing type. Use numbers for numeric columns, booleans for Boolean columns,
  and quoted strings when a numeric-looking code is stored as text.
- `csv_lookup` trims and stores lookup segment values as strings. The
  corresponding `segments[*].values` should therefore be strings too. For
  example, use `values: ["1"]`, not `values: [1]`, for CSV value `1`.
- CSV join keys are trimmed as strings during config normalization, then cast
  to the prepared anchor key's type for the join. Values that cannot be cast do
  not match.

A segment can combine several source values:

```yaml
- id: low_and_medium
  label: Low and Medium Income
  values: [low, medium]
```

Segments do not have to cover every source value. Unmatched rows remain in the
full-run summaries but do not appear in any configured segment. If overlapping
is enabled, do not add segment totals together unless double counting is
intentional.

## Dashboard And Export Settings

`segment.dashboard` selects which stored series the live dashboard shows:

| Field | Default | Behavior |
|---|---|---|
| `segmentation_type` | first definition by name | Selects one configured definition for presentation. Other definitions can still exist in the cache. |
| `visibility` | `full_and_segments` | `full_only`, `segments_only`, or `full_and_segments`. |

HTML export inherits these values. Override them for one export with:

```yaml
dashboard:
  export:
    dashboard:
      segmentation_type: district
      segmentation_visibility: segments_only
```

An export can only use segmentation types and segments already present in the
summary cache.

## Outputs And Cache Behavior

Full-run summaries keep their standard paths:

```text
<root>/<run-key>/summary_tables/<weighting>/<summary>.csv
```

Segmented summaries use:

```text
<root>/<run-key>/summary_tables/<weighting>/segments/
  <segmentation-type>/<segment-id>/<summary>.csv
```

The run-level summary manifest records each type and segment, including its
label, source, matched values, summary states, diagnostics, and digests. The
prepared cache remains at the normal run path.

One shortened manifest entry looks like this:

```json
{
  "segmentation_type": "district",
  "source_type": "csv_lookup",
  "segment_column": "district",
  "source_table": "hh",
  "source_key_column": "household_id",
  "csv_file": "C:\\lookups\\household_district.csv",
  "csv_key_column": "household_id",
  "csv_segment_value_column": "district",
  "include_full": false,
  "segments": [
    {
      "segmentation_type": "district",
      "segment_id": "north",
      "segment_label": "North",
      "is_full": false,
      "source_type": "csv_lookup",
      "segment_column": "district",
      "segment_values": ["North"],
      "summary_roots": {
        "weighted": "summary_tables/weighted/segments/district/north"
      },
      "summary_states": {},
      "summary_diagnostics": {},
      "summary_digests": {}
    }
  ]
}
```

The stored `include_full` value on the type entry describes the segmented tree,
not the accepted config field. The full run remains at the standard summary
root and is always built by the current runtime.

With `refresh: []`, cache validation is independent for the full run and each
segment. Adding or changing one segment rebuilds that segment while compatible
full-run and other segment summaries remain reusable. Removing a segment prunes
its obsolete summary directory on the next cache write. Use
`refresh: [summarize]` to rebuild all full and segmented summaries while keeping
prepared data.

Segmentation requires raw or prepared rows. A run supplied only through
`summary_table_map` cannot be segmented because its tables are already
aggregated. If a run combines raw or prepared input with `summary_table_map`,
the mapped external table is overlaid unchanged on every full and segmented
analysis unit. Do not use that pattern for a measure that must vary by segment.

## Implementation And Extension Points

| Task | Start here |
|---|---|
| Config validation and normalization | `runtime/config/normalize_segmentation.py` |
| Relationship slicing and analysis units | `processor/segmentation.py` |
| Segment identity and metadata | `processor/analysis_units.py` |
| Summary workflow integration | `runtime/workflows/summarize.py` |
| Cache paths and manifests | `processor/summarize/cache.py` and `cache_storage.py` |
| Dashboard series selection | `dashboard/state.py` |

Summary builders normally need no segment-specific code. They receive a sliced
`RunData` object and use the same declaration, schema, and weighting logic as
the full run.

## Troubleshooting

| Symptom | Check |
|---|---|
| No segmented output | Make sure `pipeline.steps` contains both `segment` and `summarize`. |
| Source column not found | Set the correct runtime `source_table` and inspect the prepared schema. |
| CSV lookup fails | Check path resolution, required columns, blank values, duplicate keys, and join-key types. |
| A segment is empty | Compare its `values` with the prepared or lookup values and review `on_empty_segment`. |
| Totals overlap | Check `allow_overlapping` and whether the selected anchor represents the population being counted. |
| Dashboard shows only full or only segmented series | Check `segment.dashboard.visibility` and the selected `segmentation_type`. |
| Old segment remains on disk | Run summarize so the next cache write can prune obsolete units. |

## Related Chapters

- [12 - Running Workflows](12-running-workflows.md)
- [13 - Configuration Reference](13-configuration-reference.md#segment)
- [21 - Prepared Tables](21-prepared-tables.md)
- [25 - Summary Functions](25-summary-functions.md)
- [42 - Config, Columns, And Labels](42-config-column-label-cookbook.md)
- [90 - Troubleshooting](90-troubleshooting.md)
