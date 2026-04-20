# Adding Summary Tables

This guide is for contributors adding a new summary table to the `summarize/` package and, optionally, exposing it in the dashboard.

The short version is:

1. Add or update a builder function in `summarize/`.
2. Register it in `summarize/cache.py`.
3. Add or update canonical output schema metadata when the table is part of the reusable dashboard contract.
4. Wire it into a dashboard page through `required_summary_ids` if a page needs it.
5. Add tests.

## Mental Model

A summary builder is a pure data step:

- input: prepared `RunData` plus normalized `Config`
- output: one Polars `DataFrame`

The builder should not know whether the dashboard is in live mode or export mode. It should also not special-case weighted vs unweighted logic; the cache layer handles that by swapping `finalweight`.

## Step 1: Choose the Right Module

Add the summary to the most relevant existing topic module when possible:

- `summarize/demographics.py`
- `summarize/mandatory.py`
- `summarize/tours.py`
- `summarize/tour_mode.py`
- `summarize/tour_tod.py`
- `summarize/stops.py`
- `summarize/trips.py`
- `summarize/totals.py`
- `summarize/destination.py`

Create a new module only when the summary is a distinct topic area rather than just another table in an existing topic.

## Step 2: Write the Builder Function

New summary builders should follow this signature:

```python
def my_summary(rd: RunData, config: Config) -> pl.DataFrame:
    ...
```

Expectations:

- Read from the prepared runtime tables on `RunData`.
- Aggregate `pl.col("finalweight").sum()` instead of counting rows directly.
- Return a plain `pl.DataFrame`.
- If required columns are missing, return an empty typed frame with the expected columns.
- Keep domain-specific reshaping in the summary layer only if it is part of the table contract. Page-specific chart shaping belongs in the dashboard page.

Example skeleton:

```python
def trip_distance_by_mode(rd: RunData, config: Config) -> pl.DataFrame:
    if "trip_mode" not in rd.trips.columns or "distance" not in rd.trips.columns:
        return pl.DataFrame(
            schema={
                "trip_mode": pl.Utf8,
                "distance_bin": pl.Int64,
                "freq": pl.Float64,
            }
        )

    return (
        rd.trips
        .filter(pl.col("trip_mode").is_not_null())
        .with_columns((pl.col("distance") / 5).floor().cast(pl.Int64).mul(5).alias("distance_bin"))
        .group_by(["trip_mode", "distance_bin"])
        .agg(pl.col("finalweight").sum().alias("freq"))
        .sort(["trip_mode", "distance_bin"])
    )
```

## Step 3: Register the Summary in `summarize/cache.py`

Registration happens in the `SUMMARY_SPECS` tuple:

```python
SummarySpec("trip_distance_by_mode", "tripDistanceByMode", trips.trip_distance_by_mode)
```

Each `SummarySpec` defines:

- `summary_id`: stable id used by dashboard pages and tests
- `filename`: CSV filename stem written under each weighting mode directory
- `builder`: function that returns the summary table

The cache module derives these related structures from `SUMMARY_SPECS`:

- `SUMMARY_SPEC_BY_ID`
- `SUMMARY_FILENAME_BY_ID`
- `DEFAULT_SUMMARY_IDS`

If the summary is not in `SUMMARY_SPECS`, it does not exist to the rest of the application.

## Step 4: Add Canonical Output Schema Metadata When Needed

If the new table is a reusable dashboard-facing contract, add its canonical output columns to `summarize/schema.py`.

Do this when:

- dashboard pages depend on a stable shape
- the summary has fallback or empty-frame behavior that should keep the same columns
- you want `tests/test_runtime_canonical_columns.py` to enforce the contract

Skip it when the table is private, transitional, or not yet used as a stable dashboard input.

## Step 5: Wire It Into a Dashboard Page

If a page should consume the summary:

1. Add the summary id to the page's `PAGE.required_summary_ids`.
2. Use `require_summary(...)` or `require_summaries(...)` in `_refresh()`.
3. Keep page-specific filtering and chart shaping in the page module.

Example:

```python
PAGE = DashboardPageDefinition(
    page_id="trip_distance",
    title="Trip Distance",
    controller_cls=TripDistancePage,
    required_summary_ids=("trip_distance_by_mode",),
)
```

This is what makes the summary available through `DashboardState` and keeps live mode, export mode, and validation aligned.

## End-to-End Example

Use this order when adding a new summary that will appear in the dashboard:

1. Add `trip_distance_by_mode()` to `summarize/trips.py`.
2. Register it in `summarize/cache.py` with a stable `summary_id`.
3. Add its column contract to `summarize/schema.py` if the page will treat it as a stable reusable table.
4. Add a new page or update an existing page in `dashboard/pages/`.
5. Declare the page dependency in `PAGE.required_summary_ids`.
6. Add export selector metadata only if the page has page-local controls that must work in HTML export.
7. Add tests covering the summary output shape and the page wiring.

## Testing Checklist

### Summary-focused tests

Prefer adding or extending:

- `tests/test_runtime_canonical_columns.py` for canonical prepared-column usage and output shape
- `tests/test_summary_cache.py` for cache-layer registration or manifest behavior

Test at least:

- weighted and unweighted paths behave through `finalweight`
- missing-column fallback returns the expected empty schema
- output columns remain stable

### Dashboard-facing tests

If the summary is used by a page, add or extend:

- `tests/test_dashboard_live.py`
- `tests/test_export_html.py`

Test at least:

- the page validates and refreshes using the new summary id
- export works if the page participates in HTML export
- page selectors still serialize correctly if the new summary changes available options

## Common Mistakes

- counting rows instead of summing `finalweight`
- reading raw ActivitySim column names directly when `prepare_data()` already provides canonical aliases
- registering the builder locally but forgetting to add it to `SUMMARY_SPECS`
- returning different columns from the empty-data path and the populated-data path
- putting chart-specific reshaping into the summary table when it belongs in the page

## Good Files to Read Before Editing

- `summarize/cache.py` for registration and weighting behavior
- `runtime/models.py` for the prepared `RunData` contract
- `runtime/run_data.py` for canonical column preparation
- `summarize/schema.py` for dashboard-facing output contracts
- `tests/test_runtime_canonical_columns.py` for the expected testing style
- [adding-dashboard-pages.md](adding-dashboard-pages.md) if the summary will be displayed in the UI
