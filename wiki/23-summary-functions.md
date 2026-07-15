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

## Weighting

Builders aggregate `finalweight`; they do not branch on weighting mode. The
summary workflow supplies the appropriate prepared data for weighted and
unweighted builds.

## Adding A Summary Function

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
9. Run `python scripts/generate_wiki_catalogs.py`.

The catalog import rejects duplicate IDs. `build_by_default=False` registers an
external or optional summary without adding it to an ordinary full build.

## Summary CSV Boundary

Summary caches are the dashboard input. Calibration-friendly CSVs can also be
written with:

```bash
python run.py --config local_config.yaml --summarize --write-csvs
```

`processor.summarize.csv_export.write_summary_csvs()` is the narrow CSV writer
boundary. Dashboard pages load registered summaries through `self.data`; they
do not open cache CSVs directly.

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
