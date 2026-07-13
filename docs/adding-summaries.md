# Adding Summary Tables

This guide is for contributors adding a new summary table to the `processor/summarize/` package and, optionally, exposing it in the dashboard.

The short version is:

1. Add or update a builder function in `processor/summarize/summaries/`.
2. Register it in `processor/summarize/summary_specs.py`.
3. Declare the builder contract once so summarize can derive empty fallback schema and dashboard-facing columns from the builder itself.
4. Wire it into a dashboard page through `required_summary_ids` or `optional_summary_ids` if a page needs it.
5. Add tests.

## Mental Model

A summary builder is a pure data step:

- input: prepared `RunData` plus normalized `Config`
- output: one Polars `DataFrame`

The builder should not know whether the dashboard is in live mode or export mode. It should also not special-case weighted vs unweighted logic; the cache layer handles that by swapping `finalweight`.

Each registered builder should also own its summary contract through `processor/summarize/contracts.py`. That contract is the single source of truth for:

- the typed empty fallback frame
- safe preflight prerequisites used by resilient summarize execution
- exported output-column metadata derived by `processor/summarize/schema.py`

## Step 1: Choose the Right Module

Add the summary to the most relevant existing topic module when possible:

- `processor/summarize/summaries/demographics.py`
- `processor/summarize/summaries/daily_travel.py`
- `processor/summarize/summaries/joint_travel.py`
- `processor/summarize/summaries/long_term.py`
- `processor/summarize/summaries/tour.py`
- `processor/summarize/summaries/trip.py`
- `processor/summarize/summaries/validation.py`
- `processor/summarize/summaries/legacy.py`

Create a new module only when the summary is a distinct topic area rather than just another table in an existing topic.

## Step 2: Write the Builder Function

New summary builders should follow this signature and declare a contract:

```python
@summary_contract(
    schema={
        "trip_mode": pl.Utf8,
        "distance_bin": pl.Int64,
        "freq": pl.Float64,
    },
    required_columns={"trips": ("trip_mode", "distance", "finalweight")},
)
def my_summary(rd: RunData, config: Config) -> pl.DataFrame:
    ...
```

Expectations:

- Read from the prepared runtime tables on `RunData`.
- Aggregate `pl.col("finalweight").sum()` instead of counting rows directly.
- Return a plain `pl.DataFrame`.
- Let the contract define the typed empty fallback schema once.
- If the builder has more nuanced missing-data logic than the contract can express, return `empty_summary_frame(my_summary)` or an equivalent typed empty frame with the same schema.
- Keep domain-specific reshaping in the summary layer only if it is part of the table contract. Page-specific chart shaping belongs in the dashboard page.

Example skeleton:

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
    if "distance" not in rd.trips.columns:
        return empty_summary_frame(trip_distance_by_mode)

    return (
        rd.trips
        .filter(pl.col("trip_mode").is_not_null())
        .with_columns((pl.col("distance") / 5).floor().cast(pl.Int64).mul(5).alias("distance_bin"))
        .group_by(["trip_mode", "distance_bin"])
        .agg(pl.col("finalweight").sum().alias("freq"))
        .sort(["trip_mode", "distance_bin"])
    )
```

## Step 3: Register the Summary in `processor/summarize/summary_specs.py`

Registration still happens in the `SUMMARY_SPECS` tuple:

```python
SummarySpec("trip_distance_by_mode", "tripDistanceByMode", trips.trip_distance_by_mode)
```

`SummarySpec` stays intentionally small:

- `summary_id`: stable id used by dashboard pages and tests
- `filename`: CSV filename stem written under each weighting mode directory
- `builder`: function that returns the summary table
- `build_by_default`: whether raw/prepared runs generate this summary automatically

The cache module derives these related structures from `SUMMARY_SPECS`:

- `SUMMARY_SPEC_BY_ID`
- `SUMMARY_FILENAME_BY_ID`
- `DEFAULT_SUMMARY_IDS`

Registered summaries are valid IDs for dashboard pages, cache filenames,
contracts, and `runs[*].summary_table_map`. Default-built summaries are the
registered subset generated automatically for normal raw/prepared runs. Use
`build_by_default=False` for external or validation-scaffold summaries that
should be loaded through `summary_table_map` without producing `__empty__`
cache CSVs for normal runs.

If the summary is not in `SUMMARY_SPECS`, it does not exist to the rest of the
application.

## Step 4: Use Derived Output Schema Metadata When Needed

If the new table is a reusable dashboard-facing contract, make sure its builder contract schema is correct. `processor/summarize/schema.py` now derives canonical output columns from the registered builders instead of maintaining a separate hand-written column map.

Do this when:

- dashboard pages depend on a stable shape
- the summary has fallback or empty-frame behavior that should keep the same columns
- you want `tests/test_runtime_canonical_columns.py` to enforce the contract

Skip it when the table is private, transitional, or not yet used as a stable dashboard input.

## Step 5: Wire It Into a Dashboard Page

If a page should consume the summary:

1. Add the summary id to the page's `@dashboard_page` `required_summary_ids`, or to `optional_summary_ids` when the page can still render without it.
2. Use `require_summary(...)` or `require_summaries(...)` in a section render function.
3. Keep page-specific filtering and chart shaping in the page module.

Example:

```python
@dashboard_page(
    page_id="trip_distance",
    title="Trip Distance",
    required_summary_ids=("trip_distance_by_mode",),
)
class TripDistancePage(DashboardPage):
    ...
```

This is what makes the summary available through `DashboardState` and keeps live mode, export mode, and validation aligned.

## End-to-End Example

Use this order when adding a new summary that will appear in the dashboard:

1. Add `trip_distance_by_mode()` to `processor/summarize/summaries/trip.py`.
2. Register it in `processor/summarize/summary_specs.py` with a stable `summary_id`.
3. Add or update the builder contract schema if the page will treat it as a stable reusable table.
4. Add a new page or update an existing page in `dashboard/pages/`.
5. Declare the page dependency in `@dashboard_page` `required_summary_ids` or `optional_summary_ids`.
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
- unavailable and failed summaries are recorded with explicit manifest state
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
- duplicating output schema in both the builder and `processor/summarize/schema.py`
- returning different columns from the empty-data path and the populated-data path
- putting chart-specific reshaping into the summary table when it belongs in the page

## Good Files to Read Before Editing

- `processor/summarize/cache.py` for registration and weighting behavior
- `processor/summarize/contracts.py` for builder contracts and typed empty fallback helpers
- `processor/models.py` for the prepared `RunData` contract
- `processor/prepare/enrichment/pipeline.py` for the `prepare_data()` entrypoint
- `processor/prepare/enrichment/canonicalize.py` and `processor/prepare/enrichment/columns.py` for canonical column preparation helpers
- `processor/summarize/schema.py` for dashboard-facing output contracts
- `tests/test_runtime_canonical_columns.py` for the expected testing style
- [adding-dashboard-pages.md](adding-dashboard-pages.md) if the summary will be displayed in the UI
