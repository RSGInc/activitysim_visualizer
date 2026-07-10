# Summary Comparison Plan

## Goal
Systematically compare every summary table written by `point_of_comparison/SummarizeABM.R` to the Python summary functions in `processor/summarize/summaries/` and record:

1. Whether a Python summary function exists for the R output.
2. Whether the Python implementation matches the R implementation, or where it differs.

## Method

1. Inventory all `write.csv()` and `write.table()` outputs in `point_of_comparison/SummarizeABM.R`.
2. Group the R outputs by topic:
   - long-term / geography
   - daily activity
   - tours
   - trips / stops
   - joint travel
   - escorting
   - validation / totals / exports
3. Inventory summary functions in `processor/summarize/summaries/`.
4. For each R output, assign one of these statuses:
   - `Implemented`: clear Python analog exists.
   - `Partial`: Python analog exists, but scope, schema, weighting, grouping, or business logic differs.
   - `Missing`: no clear Python summary function exists.
5. For `Implemented` and `Partial` items, compare the logic directly:
   - filters and universe
   - weighting vs raw counts
   - bins / categories / labels
   - totals / margins
   - geography dimensions
   - special handling for joint tours, escorting, or transit access
6. Write the findings into `point_of_comparison/comparison_notes.md` as a compact table with notes and code references.

## Expected Deliverable

`comparison_notes.md` will include:

- a short methodology note
- a systematic table of R outputs and Python analogs
- explicit callouts for missing summaries
- explicit callouts for implementation differences where the Python logic does not match the R logic

## Important Comparison Risks To Watch

- Many Python summaries are weighted by `finalweight`, while some R outputs appear to be simple counts.
- Some Python summaries roll up to configurable geography types, while the R script is often district- or county-specific.
- Some Python summaries combine multiple R visualizer tables into one normalized output.
- Several R outputs look like one-off exports/debug files rather than dashboard summaries; these still need to be cataloged, but they may not have Python analogs by design.
