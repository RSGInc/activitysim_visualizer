# 27 - Geography

The geography feature adds consistent spatial groupings to prepared tables and
summary output. Use it to report the same measures by districts, counties,
subregions, or other zone-based systems without adding regional logic to each
summary builder.

## Geography Layers

The visualizer can use several kinds of geography at the same time:

1. **Canonical zones** come from `zones`. Prepare creates MAZ and TAZ fields
   such as `home_zone_id`, `home_taz`, `OTAZ`, and `DTAZ`.
2. **Native home geographies** such as `home_county` and `home_mpo` are retained
   when they already exist in model output.
3. **A legacy land-use geography** can use `summarize.geography.landuse_col` to
   create the compatibility fields `HGEO` and `WGEO`.
4. **Named aggregations** under `summarize.geography.aggregations` map MAZ or TAZ
   IDs to any number of custom geography systems.

Named aggregations are the preferred method for new custom geography work.
They keep geography IDs and source zone systems explicit and can support
several systems in one run.

## Data Flow

```text
inline mapping or CSV zone lookup
  -> validate one geography label per zone
  -> prepare role-specific geography columns
  -> summary builders emit geography_type and geography_id
  -> dashboard pages expose available geography options
```

Although the configuration lives under `summarize`, named geography mappings
also change prepared tables. Their normalized lookup rows are part of the
prepare and summary cache identities.

## File-Based Example

Given this CSV:

```csv
MAZ,district
101,North
102,North
201,South
```

configure a named aggregation as follows:

```yaml
zones:
  use_maz: true
  maz_col: [MAZ, zone_id]
  taz_col: [TAZ, taz]

summarize:
  geography:
    enabled: true
    aggregations:
      district:
        source_zone_system: maz
        file: lookups\maz_district.csv
        zone_id_col: MAZ
        geography_col: district
```

Relative file paths start from the main configuration directory. The file must
be CSV and contain both named columns. Zone IDs must be integers, geography
labels cannot be blank, and one zone cannot map to different labels.

## Inline Example

For a small, stable mapping, list zone IDs directly:

```yaml
summarize:
  geography:
    enabled: true
    aggregations:
      market_area:
        source_zone_system: taz
        mapping:
          Core: [1, 2, 3]
          Suburban: [4, 5, 6]
          External: [99]
```

The mapping direction is `geography label -> zone ID or list of zone IDs`.
Use either `mapping` or `file` for one aggregation, never both.

## Settings

| Field | Default | Behavior |
|---|---|---|
| `summarize.geography.enabled` | `false` | Enables the legacy geography and all named aggregations. When `false`, aggregation definitions are ignored. |
| `summarize.geography.landuse_col` | none | Names one existing land-use column used to create compatibility `HGEO` and `WGEO` fields. |
| `summarize.geography.mapping` | none | Maps raw values from `landuse_col` to normalized labels for the legacy geography. |
| `summarize.geography.aggregations` | `{}` | Defines one or more named MAZ- or TAZ-based lookups. |
| `dashboard.enable_maz_geographies` | `false` | Allows MAZ options on dashboard pages that support them. This is a presentation setting and does not create geography columns. |
| `display.labels.geography` | none | Changes display labels for geography type IDs, such as displaying `district` as `School District`. It does not remap zone membership. |

Each named aggregation requires `source_zone_system: maz` or `taz` and exactly
one lookup form:

| Lookup form | Required fields |
|---|---|
| Inline | `mapping` |
| CSV | `file`, `zone_id_col`, `geography_col` |

Use a short, stable aggregation name such as `district` or `county`. That name
becomes the `geography_type` value in summaries and part of each prepared column
name.

## Prepared Outputs

For an aggregation named `district`, prepare can create:

| Prepared table | Output columns |
|---|---|
| households | `home_geo__district` |
| persons | `home_geo__district`, `work_geo__district`, `school_geo__district` |
| tours | `origin_geo__district`, `destination_geo__district` |
| trips | `origin_geo__district`, `destination_geo__district` |
| land use | `land_use_geo__district` |

The source columns depend on `source_zone_system`:

| Role | MAZ source | TAZ source |
|---|---|---|
| household/person home | `home_zone_id` | `home_taz` |
| person work | `workplace_zone_id` | `work_taz` |
| person school | `school_zone_id` | `school_taz` |
| tour/trip origin | `origin` | `OTAZ` |
| tour/trip destination | `destination` | `DTAZ` |
| land use | `MAZ` | `TAZ` |

Prepare first resolves the canonical MAZ and TAZ fields from `zones`. A named
aggregation can therefore fail to populate if the corresponding zone system is
missing or misconfigured. Zones absent from the lookup receive null geography
values; geography-specific summaries generally exclude those null rows.

## Summary And Dashboard Outputs

Summary tables that support geography use a long-form pair:

- `geography_type` identifies the system, such as `maz`, `home_taz`,
  `home_county`, or `district`.
- `geography_id` contains the zone or mapped label within that system.

The exact supported roles vary by summary. For example, population summaries
use home geography, mandatory-location summaries can use work or school
geography, and destination summaries use destination geography. Check the
[Summary Catalog](26-summary-catalog.md) for each table's meaning and required
prepared columns.

Native `home_county` and `home_mpo` columns can appear in supported summaries
without a named aggregation. `dashboard.enable_maz_geographies` controls only
whether supporting pages expose MAZ-level choices; it does not affect TAZ,
native, or named aggregation columns.

To relabel geography type IDs in the dashboard:

```yaml
display:
  labels:
    geography:
      mapping:
        district: School District
        home_county: County
        home_taz: TAZ
```

Keep membership changes under `summarize.geography`. Display labels do not
change joins, cache data, or geography IDs.

## Compatibility Matrix

Configuring a named aggregation creates every role column in the prepared
output, but a summary uses that aggregation only when its implementation
requests the corresponding role. The main supported paths are:

| Geography role | Prepared source | Summary families that use it | Dashboard pages |
|---|---|---|---|
| Home | household/person home zone and `home_geo__<name>` | worker internal/external status, work/school/university distance, work from home, telecommuting, average tour distance, internal/external non-mandatory tours, personal-auto and non-motorized VMT | Mandatory Location Choice, Tour Distance, Internal vs. External Tours, VMT Validation |
| Work | person workplace zone and `work_geo__<name>` | workplace/employment comparison, workplace shadow-price residuals, commuting flows, external workplace locations | Mandatory Location Choice, Employment/Enrollment Match, Regional Validation |
| School | person school zone and `school_geo__<name>` | school/enrollment comparison and school shadow-price residuals | Mandatory Location Choice, Employment/Enrollment Match |
| Tour/trip origin and destination | `origin_geo__<name>`, `destination_geo__<name>` | commuting flow matrices and external destination summaries | Mandatory Location Choice, Internal vs. External Tours, Regional Validation |
| Land use | `land_use_geo__<name>` | employment/enrollment targets, shadow-price comparisons, and PNR capacity comparisons when the owning summary joins land use | Employment/Enrollment Match, Park-and-Ride Location |
| Parking location | `parking_zone` base zone only | `parking_locations` | Parking Location |

Important limits:

- Overview, generic household/person distributions, Tour Purpose/Mode/Time,
  and most Trip Purpose/Mode/Time summaries do not gain a geography dimension
  merely because an aggregation is configured.
- `parking_locations` currently reports its base MAZ or TAZ parking zone. The
  prepare step does not create `parking_geo__<name>`, so named aggregations do
  not automatically appear on that page.
- Regional Validation uses only modeled geography types that agree with the
  configured outside flow contract, such as `district`/`home_district` or
  `county`/`home_county`.
- A page option is present only when at least one usable run contains non-null
  rows for that geography type. Configuration alone does not force an empty
  option into the selector.

For an exact output, find its ID in chapter 26 and confirm that the schema has
`geography_type`/`geography_id` (or origin/destination geography pairs). Then
inspect the summary's prepared requirements and the relevant page declaration
in chapter 31.

## Cache And Refresh Behavior

The normalized mapping rows contribute to prepare and summary identity. A
change to a lookup file, inline mapping, aggregation name, or source zone system
invalidates incompatible prepared and summary caches automatically. For a
repeatable manual rebuild, include `prepare` in `pipeline.steps` and use
`refresh: [prepare]`; this also rebuilds later skimjoin and summary output.

Setting `summarize.geography.enabled: false` disables both the legacy mapping
and named aggregations. Definitions left below the disabled setting do not
affect cache identity.

## Implementation And Extension Points

| Task | Start here |
|---|---|
| Config and lookup validation | `runtime/config/normalize_geography.py` |
| Cache identity | `runtime/config/signatures.py` |
| Zone context and lookup joins | `processor/prepare/enrichment/zones.py` |
| Household/person role columns | `processor/prepare/enrichment/households_persons.py` |
| Tour and trip role columns | `processor/prepare/enrichment/tours.py` and `trips.py` |
| Summary geography helpers | `processor/summarize/summaries/summary_helpers.py` |
| Dashboard geography options | `dashboard/helpers/geography_helpers.py` |

## Troubleshooting

| Symptom | Check |
|---|---|
| No custom geography columns | `summarize.geography.enabled`, prepared cache identity, and the aggregation name. |
| All mapped values are null | `source_zone_system`, `zones`, the prepared source columns, and lookup zone IDs. |
| CSV fails during config load | File path, required column names, integer zone IDs, blank labels, and conflicting duplicate zones. |
| Geography missing from a page | Whether that summary supports the role and whether any usable run has non-null data. |
| MAZ option missing | `dashboard.enable_maz_geographies` and the page's supported geography levels. |
| Labels are wrong but membership is correct | `display.labels.geography`, not the aggregation lookup. |

## Related Chapters

- [11 - Configuring Your Data](11-configuring-your-data.md)
- [13 - Configuration Reference](13-configuration-reference.md#summarize)
- [21 - Prepared Tables](21-prepared-tables.md)
- [26 - Summary Catalog](26-summary-catalog.md)
- [42 - Config, Columns, And Labels](42-config-column-label-cookbook.md)
- [90 - Troubleshooting](90-troubleshooting.md)
