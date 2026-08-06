# 44 - Summary Function Cookbook

This chapter shows how to create and test one dashboard summary. Use it with the
short contract reference in chapter 25.

## Worked Example: Trips By Mode

In this example, a page requires total trips by canonical `trip_mode`. The
output has one row for each mode, run, and weighting mode:

| trip_mode | trip_count |
|---|---:|
| DRIVEALONE | 14230.0 |
| WALK | 3180.0 |

First, define what one row represents because that decision controls grouping
keys, schema, tests, and figure axes.

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

A pure transform is easy to test without setting up caches or a dashboard. Use
canonical prepared columns rather than searching for raw aliases here.

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

The declaration does four tasks:

1. gives the table a stable config/cache ID;
2. prevents the builder from running when inputs are unavailable;
3. supplies a correctly typed empty result; and
4. rejects successful results with wrong columns, order, or dtypes.

The uniform builder interface includes `config` even when this example does not
use it. If configuration changes the calculation, use the argument and include
the setting in the summary signature.

## 3. Let The Workflow Handle Weighting

Always aggregate `finalweight`. The workflow supplies standard weights for the
weighted build. It replaces them for the unweighted build. Do not add a
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

Define the result for zero total weight and test it.

## 4. Register A New Owning Module Only Once

Adding a function to an existing module in `SUMMARY_MODULES` requires no catalog
change. If you create `processor/summarize/summaries/emissions.py`, import it and
add it to `SUMMARY_MODULES` in `processor/summarize/catalog.py`.

Do not keep a second list of functions. Catalog discovery reads decorated
functions from the imported modules. It rejects duplicate IDs.

## 5. Test Calculation And Contract Separately

Test the numbers with a small frame:

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

Then test the declaration boundary with a small `RunData`:

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

Also add a catalog assertion when you add a module. The shared declaration
tests cover general incorrect-schema behavior. Domain tests must test the
calculation and requirements.

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

Read the table through page data access. Specify the columns that the view uses:

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

The page declaration controls the removal of unused cache data and startup
requirements. The `columns=` check gives a page diagnostic if a cache does not
supply the view. This can occur with an old or external cache.

## 7. Regenerate And Verify

Use these commands:

```bash
uv run python scripts/generate_wiki_catalogs.py
uv run --with pytest pytest --basetemp .pytest_tmp tests/test_summary_declarations.py tests/test_page_registry_contract.py
```

Make sure the new ID appears in chapter 26. After connecting it to a page, make
sure it also appears in the chapter 31 page catalog.

## Variations

### Optional Summary

Use `optional_summary_ids` when the page has a useful primary view without the
new table. Show an unavailable card only for the optional section.

### External-Only Summary

Use `build_by_default=False` and a typed builder that does not calculate values.
Use this configuration for a registered table from `summary_table_map`. Follow
the external-table procedure in chapter 41.

### Segmented Summary

Usually, the builder does not require a change. Segmentation divides prepared
`RunData` before it calls the same declaration. Segmentation can remove a
required table or column. In this condition, the declared requirements must
make the summary unavailable. The builder must not fail.

## Review Checklist

- The documentation defines the row type and value meaning.
- Grouping uses canonical prepared fields.
- Counts, totals, and averages apply `finalweight` correctly.
- The schema is ordered and explicitly cast.
- Mechanical prerequisites are in the decorator.
- Domain-specific empty conditions return `builder.empty()`.
- Pure calculation and declaration behavior have focused tests.
- The consuming page declares the ID.
- Generated catalogs are current.

## Related Chapters

- [21 - Prepared Tables](21-prepared-tables.md)
- [25 - Summary Functions](25-summary-functions.md)
- [26 - Summary Catalog](26-summary-catalog.md)
- [41 - Data Extension Cookbook](41-data-extension-cookbook.md)
- [45 - Dashboard Extension Cookbook](45-dashboard-extension-cookbook.md)
