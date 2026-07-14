# Adding Summary Tables

A summary is declared once, beside its builder, with `@summary(...)`. The
declaration supplies its registry identity, cache filename, input prerequisites,
typed empty result, and strict output contract.

## Minimal summary

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
        .sort("trip_mode")
    )
```

No second registry edit is required. `processor.summarize.catalog` explicitly
imports the owning domain modules and collects their declarations. Duplicate ids
fail during catalog import.

## Declaration fields

- `id` is the stable cache and dashboard identifier. It defaults to the function
  name when that name is already appropriate.
- `schema` is ordered. Successful results must contain exactly these columns, in
  this order, with these Polars dtypes.
- `required_columns` maps a `RunData` table name to its mechanical prerequisites.
- `required_tables` is for prerequisites where table presence alone is enough;
  use `"skim"` for a required skim matrix.
- `filename` defaults to `id`. Set it only for a current external cache-file
  contract.
- `build_by_default=False` registers an optional summary without adding it to an
  ordinary full build.

## Missing input and empty results

The decorator performs the same prerequisite preflight for direct calls and
bulk builds. If a declared table or column is unavailable, the builder is not
called and its typed empty result is returned.

For domain-specific empty conditions inside the builder, use the declaration's
empty result:

```python
@summary(id="example", schema={"value": pl.Float64})
def example(run: RunData, config: Config) -> pl.DataFrame:
    filtered = run.trips.filter(pl.col("od_dist") >= 0)
    if filtered.is_empty():
        return example.empty()
    ...
```

Do not repeat simple declared column checks inside a new builder. Internal
guards should represent domain meaning the decorator cannot express.

## Strict successful results

The wrapper rejects:

- non-DataFrame results;
- missing or unexpected columns;
- columns in a different order; and
- dtypes that differ from the declaration.

Cast and select explicitly at the end of a builder. The framework does not
silently coerce a result because that can hide an aggregation or schema bug.

## Shared computations

Keep shared calculations as ordinary functions and declare each persisted
output with a small `@summary(...)` wrapper in its owning domain module. Avoid a
general summary DSL and avoid facade modules whose only purpose is re-exporting
builders.

## Calibration CSV boundary

Summary CSVs are a supported output, not a second summary API. The summarize
workflow writes each declared table to its manifest-controlled filename under
`summary_tables/<weighting mode>/`. Use:

```bash
python run.py --config local_config.yaml --summarize --write-csvs
```

`processor.summarize.csv_export.write_summary_csvs()` is the narrow writer
boundary. It accepts a mapping of plain filename stems to Polars DataFrames.
Pages should read summaries through `self.data.summary(...)`; they should not
open these CSVs directly.

## Checklist

- Put the builder in the domain module that owns the calculation.
- Declare identity, ordered schema, and prerequisites with `@summary(...)`.
- Aggregate `finalweight`; weighting mode is applied before the builder runs.
- Return one long-form `pl.DataFrame`; pivot only for display.
- Use `builder.empty()` only for domain-specific empty conditions.
- Add focused tests for the calculation and its declared result contract.

Fast checks:

```bash
pytest tests/test_summary_declarations.py tests/test_summary_csv_export.py
```
