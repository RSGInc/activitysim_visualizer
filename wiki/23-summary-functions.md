# 23 - Summary Functions

Summary functions turn prepared `RunData` into dashboard-ready Polars
`DataFrame`s. They should be independent of live dashboard behavior and HTML
export behavior.

## Mental Model

```text
RunData + Config
  -> summary builder
  -> one Polars DataFrame
  -> weighted/unweighted cache directories
  -> dashboard page
```

Builders live under [`processor/summarize/summaries`](../processor/summarize/summaries)
and are registered in
[`processor/summarize/summary_specs.py`](../processor/summarize/summary_specs.py).

## Summary Contracts

New builders should declare a contract with
`processor.summarize.contracts.summary_contract`.

The contract is the source of truth for:

- typed empty fallback output
- required prepared tables
- required prepared columns
- generated summary catalog columns

Example:

```python
@summary_contract(
    schema={
        "trip_mode": pl.Utf8,
        "distance_bin": pl.Int64,
        "freq": pl.Float64,
    },
    required_columns={"trips": ("trip_mode", "distance", "finalweight")},
)
def trip_distance_by_mode(rd: RunData, config: Config) -> pl.DataFrame:
    ...
```

## Weighting

Builders should aggregate `finalweight`. They should not branch on weighted vs
unweighted mode. The cache layer creates unweighted summaries by resetting
`finalweight` to `1.0` before invoking the same builders.

## Adding A Summary Function

Checklist:

1. Choose the best topical module:
   - `demographics.py`
   - `long_term.py`
   - `daily_travel.py`
   - `joint_travel.py`
   - `tour.py`
   - `trip.py`
   - `validation.py`
   - `skimjoin.py`
   - `legacy.py`
2. Add a builder with the standard signature:

   ```python
   def my_summary(rd: RunData, config: Config) -> pl.DataFrame:
       ...
   ```

3. Add `@summary_contract(...)` with schema and prerequisites.
4. Read from prepared `RunData` tables, not raw files.
5. Aggregate with `finalweight`.
6. Return stable columns in stable order.
7. Register the builder in `SUMMARY_SPECS`.
8. Add tests for normal input and missing optional inputs.
9. If a dashboard page needs it, add the summary ID to
   `DashboardPageDefinition.required_summary_ids`.
10. Run `python scripts/generate_wiki_catalogs.py`.

## Builder Pattern

```python
@summary_contract(
    schema={
        "category": pl.Utf8,
        "value": pl.Float64,
    },
    required_columns={"trips": ("some_column", "finalweight")},
)
def my_summary(rd: RunData, config: Config) -> pl.DataFrame:
    if "some_column" not in rd.trips.columns:
        return empty_summary_frame(my_summary)

    return (
        rd.trips
        .filter(pl.col("some_column").is_not_null())
        .group_by("some_column")
        .agg(pl.col("finalweight").sum().alias("value"))
        .rename({"some_column": "category"})
        .select("category", "value")
        .sort("category")
    )
```

## Segmentation

Segmentation runs inside the summarize workflow. It builds the same summary set
for configured slices of the prepared data.

Segment sources can be:

- a prepared-table column
- a CSV lookup joined to a prepared table

Dashboard segment visibility is controlled under `segment.dashboard`.

## Summary Catalog

The generated [24 - Summary Catalog](24-summary-catalog.md) lists every
registered summary ID, output filename, builder, schema, and contract
requirements. Regenerate it whenever `SUMMARY_SPECS` or summary contracts
change.

## Related Chapters

- [20 - Output Processor](20-output-processor.md)
- [21 - Prepared Tables](21-prepared-tables.md)
- [31 - Dashboard Pages](31-dashboard-pages.md)

