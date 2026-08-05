# 99 - Glossary

| Term | Meaning |
|---|---|
| ActivitySim output | Raw model output tables such as households, persons, tours, trips, and land use. |
| Dashboard page | One registered visualizer page with a stable `page_id`. |
| Dashboard state | Shared visualizer state such as weighting mode, value mode, segmentation, and loaded runs. |
| Export | Standalone HTML dashboard output that does not require a Python server. |
| `file_map` | Run override for raw ActivitySim output file names. |
| `finalweight` | Canonical prepared weight column aggregated by summary builders. |
| Live mode | Local Panel dashboard that uses a Python server. |
| MAZ | Micro analysis zone. |
| OMX | Open Matrix file format commonly used for skims. |
| Output Processor | Prepare, skimjoin, segmentation, and summarize workflows. |
| Output Visualizer | Live dashboard and HTML export workflows. |
| Prepared cache | Per-run cache of canonical prepared tables. |
| Prepared table | Normalized table used by summaries and prepared-data pages. |
| `prepared_table_map` | Config mapping that supplies canonical prepared tables directly and skips raw prepare. |
| Run | One ActivitySim scenario/output set shown in the dashboard. |
| Run key | Cache-directory identifier made from a run label. For example, `Build 2035` becomes `build-2035`. Duplicate normalized labels get order-dependent suffixes such as `-1` and `-2`. |
| Segment | Configured part of prepared data that the workflow summarizes separately. |
| Selector | Registered page-local widget that can refresh sections and participate in export. |
| Skim | Matrix or lookup data that supplies level-of-service values to trips or tours. |
| Skimjoin | Optional processor step that joins skim-derived values to prepared trips and tours. |
| Summary builder | Function that converts `RunData` and `Config` into one summary `DataFrame`. |
| Summary cache | Per-run, per-weighting-mode CSV summary tables consumed by dashboard pages. |
| Summary contract | Builder metadata defining output schema and required inputs. |
| TAZ | Traffic analysis zone. |
| Weighting mode | Registered transform with a version. It supplies prepared `finalweight` values under one cache and dashboard mode ID. Summary builders and prepared-data pages use the values. |

## How The Terms Connect

For a run labeled `Build`, prepare converts raw `final_trips.csv` to the
prepared `trips` table. A summary builder aggregates the canonical `finalweight`
column. It writes a registered summary in the weighted and unweighted cache
directories for the run key. A dashboard page declares the summary ID and reads
it through `self.data`. Registered selectors refresh its sections. Export
converts the same declared page states to HTML.
