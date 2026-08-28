# 25 - Summary Functions

Summary functions convert prepared `RunData` into Polars `DataFrame` objects
for the dashboard. Each function keeps its identity, requirements, output
schema, cache name, and builder in one declaration.

## Data flow

```text
RunData + Config
  -> @summary declaration and builder
  -> validated Polars DataFrame
  -> weighted/unweighted summary cache
  -> dashboard page
```

Builders live under [`processor/summarize/summaries`](../processor/summarize/summaries).
`processor.summarize.catalog` imports those modules and discovers their
declarations, so there is no separate summary specification registry to edit.

## Summary Declaration

Use `@summary(...)` from `processor.summarize`. The declaration provides:

- the stable summary ID and optional cache file name
- an ordered Polars output schema
- required prepared tables and columns
- a typed empty result
- strict result validation
- default build status

```python
import polars as pl

from processor.models import RunData
from processor.summarize import summary
from runtime.config import Config


@summary(
    id="trip_distance_by_mode",
    schema={
        "trip_mode": pl.Utf8,
        "trip_count": pl.Float64,
        "average_distance": pl.Float64,
    },
    required_columns={
        "trips": ("trip_mode", "od_dist", "finalweight"),
    },
)
def trip_distance_by_mode(run: RunData, config: Config) -> pl.DataFrame:
    return (
        run.trips.group_by("trip_mode")
        .agg(
            trip_count=pl.col("finalweight").sum(),
            average_distance=(
                (pl.col("od_dist") * pl.col("finalweight")).sum()
                / pl.col("finalweight").sum()
            ),
        )
        .with_columns(
            pl.col("trip_mode").cast(pl.Utf8),
            pl.col("trip_count").cast(pl.Float64),
            pl.col("average_distance").cast(pl.Float64),
        )
        .select("trip_mode", "trip_count", "average_distance")
    )
```

A successful builder must return the declared columns, in order, with the
declared data types. Before running the builder, the workflow checks for missing
declared input and returns the typed empty result if any input is unavailable.

Use `required_tables` only when a complete table or `skim` is enough to state
the requirement. For standard table dependencies, use `required_columns`,
which also requires the named runtime table. Specify `RunData` names such as
`hh`, `per`, `tours`, `trips`, `joint_participants`, and `land_use`, not
configuration IDs such as `households` or `persons`.

## Weighting

Builders aggregate `finalweight`. They do not select a weighting mode. The
summary workflow supplies the required prepared data for weighted and
unweighted builds.

### Weight Resolution And Edge Cases

The primary weighted mode is prepared as follows:

1. An explicit run-level household/person/trip weight column is cast to
   `Float64` on its table.
2. If no explicit household, person, or trip run weight is supplied, a
   household `sample_rate` produces `1 / sample_rate`. `day_weight_col` does
   not disable this household expansion.
3. Otherwise, household weight defaults to `1.0` when no household source was
   selected. Supplying only a person or trip weight therefore disables
   household sample-rate expansion.
4. Missing lower-level sources inherit through household/person/tour
   relationships. An unmatched inherited row normally falls back to `1.0`.
5. When an explicit trip weight is used, tour weight is the mean trip weight
   for that `tour_id`.
6. `day_weight_col` defaults to `day_weight`. A non-null day source is
   authoritative; missing values inherit person weight, then household weight,
   then `1.0`. Set the field to null to ignore the source for every day row.

The unweighted mode changes existing `finalweight` columns to `1.0`; it does
not add that column to a custom prepared table that omitted it. Named column
modes follow the propagation rules in chapter 43.

The runtime casts weights but does not apply a universal quality rule for
zero, negative, null, infinite, or extreme values. Consequences are
calculation-specific:

- a null weight is ignored by a Polars sum and can remove that row's
  contribution;
- zero weights contribute no count and can create a zero denominator;
- negative weights subtract from totals;
- `sample_rate: 0` can produce an infinite expansion weight; and
- a weighted average with a zero or invalid denominator can return null, NaN,
  or infinity unless that builder handles the case.

Validate source weights before production use. A practical contract is finite,
non-null, nonnegative weights and strictly positive sample rates. If zero
weights are intentional, test every rate and average that consumes them.

### Units

The visualizer does not maintain a separate unit registry or automatically
convert source values. Units are part of the source/prepared/summary contract:

| Output kind | Unit rule |
|---|---|
| Counts and totals | `finalweight` expansion units; unweighted mode is row counts unless a builder applies occupancy/party logic. |
| Rates and shares | Ratio of the builder's declared numerator and denominator; dimensionless unless the label states a per-person or per-day basis. |
| Distance and VMT | Uses prepared distance values as supplied. Existing dashboard labels assume miles. Convert upstream or in prepare if the model uses another unit. |
| Time | Uses prepared time/hour/period fields and configured time-period mapping. Skim time components keep the skim's unit. |
| Cost and other skim components | Keeps the matrix or sidecar unit; skimjoin does not convert cents, dollars, minutes, seconds, or generalized cost. |
| Geography IDs and categories | Labels/identifiers, not measured units. |

When you add a summary, state the unit in its column name, page axis/tooltip, or
calculation note. Do not combine runs whose underlying distance, time, or cost
units differ without normalizing them first.

### Joint travel and tour-distance conventions

Legacy-compatible summaries distinguish person travel from unique travel
records:

- every eligible source row contributes under its active weight; builders do
  not discard repeated rows merely because identifiers match;
- person-level tour/trip rates, mode counts, and population travel totals
  expand only records categorized as joint;
- when joint-participant rows are available, person-tour and person-trip
  summaries use the sum of every matching participant's person weight; valid
  scalar party-size expansion is only the fallback;
- household-tour summaries (including tour purpose/category, joint party and
  composition, stop frequency, time-of-day, duration, and distance) do not
  expand joint tours by party size. When a verified survey group stores one row
  per participant, every row is retained with `1 / party size` representation
  weight so the complete group contributes one household tour; and
- a usable participant count is greater than zero and less than `995`.
  Invalid, missing, and sentinel counts fall back to one when a person-level
  record must still be counted, while party-size descriptive summaries exclude
  them.

This fractional household-tour representation is not record deduplication: the
source rows and their attributes remain in the calculation. If participant rows
report different time or distance values for the same joint-tour identifier,
the histogram shows their fractional mixture rather than silently selecting one
participant as the canonical record.

Daily tour rates exclude at-work subtours. The tour-distance histogram and
nonmandatory average both use prepared `SKIMDIST` for every run. They do not
fall back to `tour_distance` or generic `distance_miles`, because either can
represent full traveled tour length instead of origin-to-primary-destination
distance.

Both builders currently check for `SKIMDIST` inside the function but omit it
from their `@summary(required_columns=...)` declarations. Chapter 26 therefore
under-reports that prerequisite. Treat this as a summary-contract
implementation gap until the declarations include the field.

The generated Required Inputs column contains declared mechanical
prerequisites, not every builder-level condition. For example, the joint-tour
composition builders need `composition` or `tour_composition`; the
composition-by-party-size builder also needs `number_of_participants` or
`NUMBER_HH`; and person participation by household size needs `HHSIZE` or
`hhsize`. These alternative requirements are resolved inside their builders.

Daily tour and trip rate denominators use every attributable day row when a
nonempty day table with `person_id` is available, and their numerators retain
only travelers whose `person_id` occurs in that exposure set. A false
`surveyable` value excludes a person even when a day table is present. Without
day rows, every remaining prepared person represents one modeled day.

The current numerator gate uses `person_id`, not `(person_id, day_id)`. It can
therefore retain activity from a different day for a person who has at least
one eligible day. This is an implementation gap for multi-day inputs that reuse
person identifiers; inputs with a unique person identifier per day do not
expose it.

Daily activity summaries use a non-null person-table DAP or mandatory-frequency
choice for that person, then fall back only for remaining persons to all
eligible day rows and their day weights. Nonmandatory frequency is classified
per person-day for genuinely multi-day inputs only when all individual tours
and joint participations can be assigned to a day without guessing. If those
keys are incomplete or ambiguous, the summary retains the one-day/person
fallback rather than discarding unmatched rows.

Joint-tour frequency and household participation use household observations.
For a genuinely multi-day diary, the observation key is
`(household_id, day_num)` when tours carry the matching day column. The current
implementation does not validate those tour days against the day table: null
or unmatched values simply do not contribute. Repeated records collapse first
by a valid `joint_tour_id`, then a valid `tour_id`; a row with neither becomes
its own identity. If the tour day column is absent, the result is empty rather
than pooling a week into one choice. One-day inputs continue to use one
observation per household.

The legacy JTF labels use minimum thresholds for only shopping, maintenance,
eating out, visiting/social, and other discretionary. Joint purposes outside
those five counters are ignored, and a count above a threshold can still
receive its two-tour label. A household-day with only an outside purpose can
therefore appear as `No Joint Tours`. These are current implementation gaps,
not documented recoding rules for new inputs.

The JTF summary declaration requires only the household table. On a one-day
input, an unavailable or zero-column tour table can therefore produce a
plausible all-`No Joint Tours` result instead of an unavailable summary. Check
tour availability before accepting that distribution.

Person joint-tour participation similarly uses person-days when the day table
identifies household, person, and day and every unique joint tour maps to one
day. It uses the day weight when available and otherwise the person weight. An
absent or ambiguous tour-day mapping produces an empty result. If the day table
lacks household, person, or day fields, the existing person-level participation
fallback remains. Once the multi-day branch is selected, it also assumes a
schemaful joint-participant table: a zero-column table can fail the builder and
a schemaful empty table yields zero participating person-days instead of using
the person-level fallback.

The Joint Travel page currently labels these charts as households or people
even when a multi-day run contributes household-day or person-day
observations. The Daily Activity Pattern page likewise labels person-day
frequency distributions as persons. Treat those static axes as a dashboard UI
gap and use the catalog's unit description when interpreting multi-day runs.

## Adding A Summary Function

For an example with a calculation, contract test, catalog, and page connection,
use the [Summary Function Cookbook](44-summary-function-cookbook.md).

1. Put the builder in the domain module that owns the calculation.
2. Decorate it with `@summary(...)` and declare identity, ordered schema, and
   mechanical prerequisites.
3. Read prepared `RunData` tables, not raw files.
4. Aggregate `finalweight` and return one long-form `pl.DataFrame`.
5. Cast and select explicitly at the end of the builder.
6. Use `builder.empty()` only for domain-specific empty conditions that the
   declared prerequisites cannot express.
7. Add focused calculation and contract tests.
8. Add the summary ID to a page's required or optional summaries when needed.
9. Add the analytical and output-field descriptions to
   `scripts/summary_catalog_metadata.yaml`. Add shared required-input metadata
   there when the declaration introduces a new prepared table or field.
10. Use `uv run python scripts/generate_wiki_catalogs.py`.

The catalog import rejects duplicate IDs. Standard summarize workflows build
every declaration with `build_by_default=True`, regardless of enabled page
requirements. Setting `build_by_default=False` registers the contract without
adding it to standard builds. Use this setting for an external table in the
public workflow and supply the table through `summary_table_map`. Referencing a
non-default ID in a page declaration does not start its builder.

## Summary CSV Boundary

Summary caches are the dashboard input. The visualizer stores registered tables
as CSV files for each run and weighting mode, and standard summarize workflows
write any that are missing or stale. Use `--skip-summary-cache-write` to prevent
these writes.

For a developer diagnostic, the following command ignores reusable summary
caches, rebuilds the configured summaries, and writes their CSV files and
manifests:

```bash
uv run activitysim-viz --config local_config.yaml --summarize --write-csvs
```

The command does not create a second export format or a separate calibration
directory. Cache storage uses the shared
`processor.summarize.csv_export.write_summary_csvs()` writer. Dashboard pages
load registered summaries through `self.data`. They do not open the CSV files
directly.

To register a new dashboard-ready table produced outside the visualizer, use
the [outside summary table recipe](41-data-extension-cookbook.md#worked-example-add-an-outside-summary-table).

## Segmentation

Segmentation runs in the summarize workflow and builds the same declarations
for related subsets of prepared data. A source can be a prepared column or a
CSV lookup. The runtime slices `RunData`, applies the normal weighting modes,
and writes each result below the segment's summary-cache path. See
[24 - Segmentation](24-segmentation.md) for source-table relationships, settings,
outputs, cache behavior, and dashboard selection.

## Summary Catalog

The generated [26 - Summary Catalog](26-summary-catalog.md) combines each current
declaration with the analytical descriptions in
`scripts/summary_catalog_metadata.yaml`. The same generator combines those
summaries with prepared-output metadata and sidecar contracts in the portable
`reference/processor-output-table-reference.md`. Regenerate both references
after you change any of those sources.

## Related Chapters

- [20 - Output Processor](20-output-processor.md)
- [21 - Prepared Tables](21-prepared-tables.md)
- [24 - Segmentation](24-segmentation.md)
- [27 - Geography](27-geography.md)
- [31 - Dashboard Page Contract](31-dashboard-pages.md)
- [44 - Summary Function Cookbook](44-summary-function-cookbook.md)
