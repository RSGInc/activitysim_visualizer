# 44 - Summary Function Cookbook

This chapter follows one new summary from a question to a tested dashboard
dependency. Use it with the shorter contract reference in chapter 23.

## Worked Example: Trips By Mode

Suppose a page needs total trips by canonical `trip_mode`. The output grain is
one row per mode, per run, per weighting mode:

| trip_mode | trip_count |
|---|---:|
| DRIVEALONE | 14230.0 |
| WALK | 3180.0 |

Write the grain down first. It determines the grouping keys, schema, tests, and
figure axes.

## 1. Put Pure Calculation Before Registration

Add the calculation to the domain owner, such as
`processor/summarize/summaries/trip.py`:

```python
import polars as pl


def trips_by_mode_frame(trips: pl.DataFrame) -> pl.DataFrame:
    return (
        trips.drop_nulls("trip_mode")
        .group_by("trip_mode")
        .agg(pl.col("finalweight").sum().alias("trip_count"))
        .with_columns(
            pl.col("trip_mode").cast(pl.Utf8),
            pl.col("trip_count").cast(pl.Float64),
        )
        .sort("trip_mode")
        .select("trip_mode", "trip_count")
    )
```

Keeping the transform pure makes the calculation easy to test without cache or
dashboard setup. Use canonical prepared columns; do not probe raw aliases here.

## 2. Declare The Runtime Contract

Wrap the transform with `@summary` in the same module:

```python
from processor.models import RunData
from processor.summarize import summary
from runtime.config import Config


@summary(
    id="trips_by_mode",
    schema={
        "trip_mode": pl.Utf8,
        "trip_count": pl.Float64,
    },
    required_columns={
        "trips": ("trip_mode", "finalweight"),
    },
)
def trips_by_mode(run: RunData, config: Config) -> pl.DataFrame:
    return trips_by_mode_frame(run.trips)
```

The declaration does four jobs:

1. gives the table a stable config/cache ID;
2. prevents the builder from running when inputs are unavailable;
3. supplies a correctly typed empty result; and
4. rejects successful results with wrong columns, order, or dtypes.

The unused `config` argument is still part of the uniform builder interface. If
config changes the calculation, use it here and ensure the setting belongs to
the summary signature.

## 3. Let The Workflow Handle Weighting

Always aggregate `finalweight`. The workflow supplies ordinary weights for the
weighted build and replaces them for the unweighted build. Do not add a
`weighted` branch to the builder.

For an average, use a weighted numerator and denominator:

```python
.agg(
    average_distance=(
        (pl.col("od_dist") * pl.col("finalweight")).sum()
        / pl.col("finalweight").sum()
    )
)
```

Decide how zero total weight should behave and test it explicitly.

## 4. Register A New Owning Module Only Once

Adding a function to an existing module in `SUMMARY_MODULES` needs no catalog
edit. If you create `processor/summarize/summaries/emissions.py`, import that
module and add it to `SUMMARY_MODULES` in `processor/summarize/catalog.py`.

Do not maintain a second list of individual functions. Catalog discovery reads
decorated functions from the explicitly imported owning modules and rejects
duplicate IDs.

## 5. Test Calculation And Contract Separately

Test the numbers with a tiny frame:

```python
def test_trips_by_mode_frame_uses_finalweight():
    trips = pl.DataFrame(
        {
            "trip_mode": ["WALK", "WALK", "DRIVEALONE"],
            "finalweight": [1.0, 2.5, 4.0],
        }
    )

    result = trips_by_mode_frame(trips)

    assert result.to_dicts() == [
        {"trip_mode": "DRIVEALONE", "trip_count": 4.0},
        {"trip_mode": "WALK", "trip_count": 3.5},
    ]
    assert result.schema == {
        "trip_mode": pl.Utf8,
        "trip_count": pl.Float64,
    }
```

Then test the declaration boundary with a minimal `RunData`:

```python
def test_trips_by_mode_preflights_missing_columns():
    empty_run = RunData(
        label="Test",
        run_dir="C:/runs/test",
        skim_file=None,
        hh=pl.DataFrame(),
        per=pl.DataFrame(),
        tours=pl.DataFrame(),
        trips=pl.DataFrame(),
        joint_participants=pl.DataFrame(),
        land_use=pl.DataFrame(),
        skim_matrix=None,
    )

    # Config is not read because prerequisite checking returns first.
    result = trips_by_mode(empty_run, None)

    assert result.is_empty()
    assert result.schema == {
        "trip_mode": pl.Utf8,
        "trip_count": pl.Float64,
    }
```

Also add a catalog assertion when a new module is introduced. The shared
declaration tests already cover generic wrong-schema behavior; domain tests
should focus on your calculation and prerequisites.

## 6. Wire It To A Page

Declare the dependency on the page:

```python
@dashboard_page(
    page_id="trip_mode_totals",
    title="Trip Mode Totals",
    group_id="trip_summaries",
    required_summary_ids=("trips_by_mode",),
)
class TripModeTotalsPage(DashboardPage):
    ...
```

Read the table through page data access and state the columns the view uses:

```python
data = self.data.summary(
    "trips_by_mode",
    columns=("trip_mode", "trip_count"),
)
if not data:
    return self.summary_only_unavailable_card()
return self.plot.bar(
    data,
    x="trip_mode",
    y="trip_count",
    title="Trips By Mode",
    x_title="Trip Mode",
    y_title="Trips",
)
```

The page declaration controls cache pruning and startup requirements. The
`columns=` check provides a useful page-level diagnostic if an old or external
cache does not satisfy the view.

## 7. Regenerate And Verify

Run:

```bash
python scripts/generate_wiki_catalogs.py
pytest tests/test_summary_declarations.py tests/test_page_registry_contract.py
```

Confirm the new ID appears in chapter 24 and, once wired to a page, in the page
catalog in chapter 31.

## Variations

### Optional Summary

Use `optional_summary_ids` when the page retains a meaningful primary view
without the new table. Render an unavailable card only for the optional
section.

### External-Only Summary

Use `build_by_default=False` and a typed no-op builder for a registered table
that must come from `summary_table_map`. Follow the outside-table recipe in
chapter 41.

### Segmented Summary

Usually no builder change is needed. Segmentation slices prepared `RunData`
before invoking the same declaration. A summary that depends on a table or
column removed by segmentation should become unavailable through its declared
prerequisites, not fail inside the builder.

## Review Checklist

- The row grain and value meaning are written down.
- Grouping uses canonical prepared fields.
- Counts, totals, and averages apply `finalweight` deliberately.
- The schema is ordered and explicitly cast.
- Mechanical prerequisites are in the decorator.
- Domain-specific empty conditions return `builder.empty()`.
- Pure calculation and declaration behavior have focused tests.
- The consuming page declares the ID.
- Generated catalogs are current.

## Related Chapters

- [21 - Prepared Tables](21-prepared-tables.md)
- [23 - Summary Functions](23-summary-functions.md)
- [24 - Summary Catalog](24-summary-catalog.md)
- [41 - Data Extension Cookbook](41-data-extension-cookbook.md)
- [45 - Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md)
