# 23 - Summary Functions

Summary functions turn prepared `RunData` into dashboard-ready Polars
`DataFrame`s. A summary's identity, prerequisites, output schema, cache name,
and builder are declared together.

## Mental Model

```text
RunData + Config
  -> @summary declaration and builder
  -> validated Polars DataFrame
  -> weighted/unweighted summary cache
  -> dashboard page
```

Builders live under [`processor/summarize/summaries`](../processor/summarize/summaries).
`processor.summarize.catalog` explicitly imports those owning modules and
discovers their declarations. There is no separate summary-spec registry to
edit.

## Summary Declaration

Use `@summary(...)` from `processor.summarize`. The declaration provides:

- the stable summary ID and optional cache filename
- an ordered Polars output schema
- required prepared tables and columns
- a typed empty result
- strict result validation
- whether the summary is built by default

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

Successful builders must return exactly the declared columns, in the declared
order and with the declared dtypes. Missing declared inputs are handled before
the builder runs and produce its typed empty result.

Use `required_tables` only when the presence of an entire table or `skim` is
enough to express the prerequisite. Use `required_columns` for ordinary table
dependencies; it also implies that the named runtime table must exist. Table
names here are `RunData` names (`hh`, `per`, `tours`, `trips`,
`joint_participants`, `land_use`), not config IDs such as `households` or
`persons`.

## Weighting

Builders aggregate `finalweight`; they do not branch on weighting mode. The
summary workflow supplies the appropriate prepared data for weighted and
unweighted builds.

## Adding A Summary Function

For a complete calculation, contract test, catalog, and page-wiring example,
follow the [Summary Function Cookbook](44-summary-function-cookbook.md).

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
9. Run `uv run python scripts/generate_wiki_catalogs.py`.

The catalog import rejects duplicate IDs. Ordinary summarize workflows build
every declaration with `build_by_default=True`; enabled page requirements do
not narrow or expand that build set. `build_by_default=False` registers a
contract without adding it to ordinary generated builds. In the current public
workflow this is the external-table pattern: provide the table through
`summary_table_map`. Merely listing a non-default ID in a page declaration does
not cause its builder to run.

## Summary CSV Boundary

Summary caches are the dashboard input and their registered tables are already
stored as CSV files under each run and weighting mode. Normal summarize runs
write missing or stale cache tables unless `--skip-summary-cache-write` is used.

For a developer diagnostic, this command bypasses reusable summary caches,
rebuilds the configured summaries, and forces the cache CSVs/manifests to be
written:

```bash
uv run activitysim-viz --config local_config.yaml --summarize --write-csvs
```

It does not create a second export format or a separate calibration directory.
`processor.summarize.csv_export.write_summary_csvs()` is the shared low-level
writer used by cache storage. Dashboard pages load registered summaries through
`self.data`; they do not open those CSVs directly.

To register a new dashboard-ready table produced outside the visualizer, use
the [outside summary table recipe](41-data-extension-cookbook.md#worked-example-add-an-outside-summary-table).

## Segmentation

Segmentation runs inside the summarize workflow and builds the same declarations
for configured slices of the prepared data. Segment sources may be a prepared
column or a CSV lookup. Dashboard visibility is controlled by
`segment.dashboard`.

## Summary Catalog

The generated [24 - Summary Catalog](24-summary-catalog.md) lists every current
declaration, output filename, builder, schema, and prerequisite. Regenerate it
after summary declarations change.

## Related Chapters

- [20 - Output Processor](20-output-processor.md)
- [21 - Prepared Tables](21-prepared-tables.md)
- [31 - Dashboard Pages](31-dashboard-pages.md)
- [44 - Summary Function Cookbook](44-summary-function-cookbook.md)
