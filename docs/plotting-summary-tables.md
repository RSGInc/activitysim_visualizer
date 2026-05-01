# Plotting Summary Tables

This primer explains how to turn precomputed summary tables into the kinds of plots the dashboard already uses.

It is aimed at the common case where:

- the summary table already exists
- you want to add or adjust a chart on a dashboard page
- you want to follow the same patterns used in `dashboard/components.py` and `dashboard/pages/`

If you need to create the summary itself first, start with [adding-summaries.md](adding-summaries.md).

## Mental Model

In this codebase, plotting usually happens in two layers:

1. A page module fetches one or more summary tables and reshapes them into chart-ready data.
2. A shared helper in `dashboard/components.py` turns that prepared data into a `pn.pane.Plotly`.

The shared helpers expect data in this form:

```python
list[tuple[str, pl.DataFrame]]
```

Each tuple is:

- `run_label`: the visible label for one model run
- `pl.DataFrame`: the data for that run after any filtering, grouping, sorting, or renaming needed for plotting

That means pages should usually do business logic first, and plotting second.

## The Shared Plot Helpers

The main helpers live in `dashboard/components.py`:

- `bar_chart(...)`: grouped or stacked categorical comparisons across runs
- `line_chart(...)`: overlaid line profiles
- `density_chart(...)`: filled line charts used for distributions such as TLFD or time-of-day profiles

All three helpers:

- accept `list[tuple[str, pl.DataFrame]]`
- use consistent run colors
- apply shared layout and legend styling
- honor `as_percent=self.as_percent` so the same chart can flip between counts and percentages

## The Core Workflow

Most pages follow the same sequence:

1. Fetch summaries with `require_summary(...)` or `require_summaries(...)`.
2. Build chart-ready tables in small helper functions.
3. Cache selector-dependent reshaping with `get_filtered_view(...)` when useful.
4. Pass the prepared data into `bar_chart(...)` or `density_chart(...)`.

The dashboard examples in `dashboard/pages/overview.py`, `dashboard/pages/long_term.py`, `dashboard/pages/tour_mode.py`, and `dashboard/pages/tour_tod.py` all follow this pattern.

## Plot Type 1: Categorical Bar Charts

Use `bar_chart(...)` when you want to compare categories across runs.

Typical inputs:

- person type distributions
- household size distributions
- auto ownership
- mode shares
- stop frequency

Minimal example:

```python
chart = bar_chart(
    data_list,
    x_col="tour_mode",
    y_col="tour_count",
    title="Tour Mode",
    xaxis_title="Mode",
    yaxis_title="Tours",
    as_percent=self.as_percent,
)
```

### When the summary table is already chart-ready

Sometimes the summary already has one row per category and one value column you can plot directly. In that case, the page only needs light cleanup.

Example pattern from `dashboard/pages/overview.py`:

```python
def person_type_chart_data(
    pertype_list: list[tuple[str, pl.DataFrame]],
) -> list[tuple[str, pl.DataFrame]]:
    return [
        (label, df.with_columns(pl.col("person_type_label").cast(pl.Utf8)))
        for label, df in pertype_list
    ]
```

This is a good fit when you only need to:

- cast labels to strings
- select a subset of columns
- preserve the existing category rows

### When you need to filter by a selector

If a page has a selector such as purpose or geography, filter the table before plotting.

Example pattern from `dashboard/pages/tour_mode.py`:

```python
df.filter(pl.col("tour_purpose").cast(pl.Utf8) == purpose).select(
    ["tour_mode", column]
).sort("tour_mode")
```

This is the standard approach when the summary is long-form and one selector value corresponds to one chart.

### When the "Total" option is not stored directly

Some pages define a synthetic "Total" by filtering out pre-aggregated rows and summing the detailed rows.

Example pattern from `dashboard/pages/tour_mode.py`:

```python
purpose_col = pl.col("tour_purpose").cast(pl.Utf8)
(
    df.filter(~purpose_col.is_in(["all_tour_purposes", "Total"]))
    .group_by("tour_mode")
    .agg(pl.col(column).sum().alias(column))
    .sort("tour_mode")
)
```

Use this pattern when:

- the table stores both detailed rows and rolled-up labels
- you want a "Total" chart built from the detailed rows only

### Optional percent values in hover

`bar_chart(...)` supports `pct_col=...`.

Example:

```python
bar_chart(
    auto_own_list,
    x_col="household_vehicle_count",
    y_col="household_count",
    pct_col="pct",
    as_percent=self.as_percent,
)
```

This is useful when the summary already contains both:

- an absolute measure such as `household_count`
- a percentage column such as `pct`

The chart still plots `y_col`, but the hover text also shows `pct_col`.

## Plot Type 2: Distribution and Profile Charts

Use `density_chart(...)` for ordered x-axes where the shape of the distribution matters more than discrete bars.

Typical inputs:

- trip length frequency distributions
- distance distributions
- departure and arrival profiles
- duration distributions

Minimal example:

```python
density_chart(
    data_list,
    x_col="distance_bin",
    y_col="person_count",
    title="Work TLFD",
    xaxis_title="Distance (miles)",
    yaxis_title="Persons",
    as_percent=self.as_percent,
)
```

### Sort the x-axis deliberately

Unlike simple bar charts, distribution plots usually need a meaningful order. The page should sort before passing data to the chart helper.

Example pattern from `dashboard/pages/long_term.py`:

```python
df.filter(pl.col("geography") == geography).select(
    pl.col("distance_bin"),
    pl.col("person_count"),
).sort("distance_bin")
```

If you do not sort, Plotly will use the row order it receives.

### Rename value columns to a common plotting column

When several charts use different measure columns from the same summary, it is often easier to rename the selected measure to one shared plotting name.

Example pattern from `dashboard/pages/tour_tod.py`:

```python
df.filter(pl.col("tour_purpose").cast(pl.Utf8) == purpose).select(
    ["time_bin", val_col]
).rename({val_col: "freq"})
```

This makes the chart call simpler because every downstream chart can use `y_col="freq"`.

### Convert coded bins into display labels

Many summary tables use coded bins that should not be shown directly.

Example pattern from `dashboard/pages/tour_tod.py`:

```python
selected.with_columns(
    pl.col("time_bin")
    .map_elements(lambda tb: _time_label(int(tb), maxbin), return_dtype=pl.Utf8)
    .alias("clock_time")
)
```

Other examples include:

- converting integer household-size bins to strings
- converting auto ownership counts to display labels
- converting duration bins into hours

The key idea is that the page owns display-friendly reshaping, while `density_chart(...)` stays generic.

## Plot Type 3: Multi-Chart Views From One Summary

Sometimes one summary table powers several related charts. In those cases, prepare all chart datasets in one helper and return them together.

Example pattern from `dashboard/pages/tour_tod.py`:

```python
def chart_data(tod_list, purpose):
    dep_data = [...]
    arr_data = [...]
    dur_data = [...]
    return dep_data, arr_data, dur_data
```

This pattern works well when:

- the same selector drives several plots
- several plots share the same filtering logic
- you want to cache the reshaping once with `get_filtered_view(...)`

Example:

```python
dep_data, arr_data, dur_data = self.get_filtered_view(
    "tour_tod",
    raw_purpose,
    factory=lambda: chart_data(tod_list, raw_purpose),
)
```

Use this whenever selector-driven reshaping would otherwise be repeated several times across section render functions.

## Common Reshaping Patterns

These are the most common ways summary tables become chart-ready.

### 1. Cast category columns to strings

Useful for discrete labels such as household size or person type.

```python
df.with_columns(pl.col("household_size").cast(pl.Utf8))
```

### 2. Select only the columns the chart needs

Useful when the summary carries extra metadata.

```python
df.select(
    pl.col("geography"),
    pl.col("work_from_home_worker_count"),
)
```

### 3. Filter to one selector value

Useful for purpose, geography, tour mode, or person type views.

```python
df.filter(pl.col("geography") == geography)
```

### 4. Group and aggregate

Useful when a "Total" option should be built dynamically.

```python
df.group_by("tour_mode").agg(pl.col(column).sum().alias(column))
```

### 5. Sort into display order

Useful for distributions, ordered categories, and numeric bins.

```python
df.sort("distance_bin")
```

### 6. Rename the plotted value column

Useful when several summaries expose different measure names.

```python
df.rename({val_col: "freq"})
```

## Choosing the Right Plot

A quick rule of thumb:

- Use `bar_chart(...)` for discrete categories like mode, purpose, household size, or auto ownership.
- Use `density_chart(...)` for ordered bins like distance, time, or duration.
- Use `line_chart(...)` when you want the same ordered comparison without filled areas.

If the x-axis has a natural progression, a line-style chart is usually the better fit. If the x-axis is a set of labeled buckets with no continuous feel, a bar chart is usually clearer.

## Practical Guidelines

Keep the following habits when adding a chart:

- Do chart-specific reshaping in page helper functions, not inside `dashboard/components.py`.
- Keep shared helpers generic and presentation-focused.
- Filter out `None` or empty data frames when a summary may be absent for some runs.
- Sort ordered x-axes before plotting.
- Prefer small helpers with names like `chart_data(...)`, `purpose_options(...)`, or `*_chart_data(...)`.
- Use `get_filtered_view(...)` when a selector-dependent reshape is reused or expensive.
- Pass `as_percent=self.as_percent` so the chart respects the page-wide count/percent toggle.

## A Good Starting Template

This is a solid pattern for a new chart on a page:

```python
def my_chart_data(
    summary_list: list[tuple[str, pl.DataFrame]],
    selected_value: str | None,
) -> list[tuple[str, pl.DataFrame]]:
    out = []
    for label, df in summary_list:
        if df is None or len(df) == 0:
            continue
        chart_df = (
            df.filter(pl.col("segment").cast(pl.Utf8) == selected_value)
            .select(["category", "count"])
            .sort("category")
        )
        out.append((label, chart_df))
    return out


data = self.get_filtered_view(
    "my_chart",
    selected_value,
    factory=lambda: my_chart_data(summary_list, selected_value),
)

chart = bar_chart(
    data,
    x_col="category",
    y_col="count",
    title="My Summary Chart",
    xaxis_title="Category",
    yaxis_title="Count",
    as_percent=self.as_percent,
)
```

That template matches the structure already used across the dashboard.

## Examples to Revisit in the Repo

These files are especially useful references:

- `dashboard/components.py`: shared chart APIs and layout behavior
- `dashboard/pages/overview.py`: simple chart-ready summary tables
- `dashboard/pages/long_term.py`: geography filtering and TLFD plots
- `dashboard/pages/tour_mode.py`: selector-driven filtering and dynamic totals
- `dashboard/pages/tour_tod.py`: profile plots, relabeling bins, and multi-chart caching

If you are deciding where a transformation belongs, a good rule is:

- page modules own meaning
- shared chart helpers own appearance
