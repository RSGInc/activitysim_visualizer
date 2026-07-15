# 99 - Glossary

| Term | Meaning |
|---|---|
| ActivitySim output | Raw model output tables such as households, persons, tours, trips, and land use. |
| Dashboard page | One registered visualizer page with a stable `page_id`. |
| Dashboard state | Shared visualizer state such as weighting mode, value mode, segmentation, and loaded runs. |
| Export | Standalone HTML dashboard output that does not require a Python server. |
| `file_map` | Per-run override for raw ActivitySim output filenames. |
| `finalweight` | Canonical prepared weight column aggregated by summary builders. |
| Live mode | Python-backed Panel dashboard served locally. |
| MAZ | Micro analysis zone. |
| OMX | Open Matrix file format commonly used for skims. |
| Output Processor | Prepare, skimjoin, segmentation, and summarize workflows. |
| Output Visualizer | Live dashboard and HTML export workflows. |
| Prepared cache | Per-run cache of canonical prepared tables. |
| Prepared table | Normalized table used by summaries and prepared-data pages. |
| `prepared_table_map` | Config mapping that supplies canonical prepared tables directly and skips raw prepare. |
| Run | One ActivitySim scenario/output set shown in the dashboard. |
| Run key | Cache-directory identifier made by slugifying a run label, such as `Build 2035` to `build-2035`; duplicate normalized labels receive order-dependent `-1`, `-2`, and later suffixes. |
| Segment | Configured slice of prepared data summarized separately. |
| Selector | Registered page-local widget that can refresh sections and participate in export. |
| Skim | Matrix or lookup data used to attach level-of-service values to trips/tours. |
| Skimjoin | Optional processor step that joins skim-derived values to prepared trips and tours. |
| Summary builder | Function that converts `RunData` and `Config` into one summary `DataFrame`. |
| Summary cache | Per-run, per-weighting-mode CSV summary tables consumed by dashboard pages. |
| Summary contract | Builder metadata defining output schema and required inputs. |
| TAZ | Traffic analysis zone. |
| Weighting mode | Dashboard/cache mode such as weighted or unweighted. |

## How The Terms Connect

For a run labeled `Build`, raw `final_trips.csv` is normalized into the
prepared `trips` table. A summary builder aggregates its canonical
`finalweight` column and writes a registered summary under the run key's
weighted and unweighted cache directories. A dashboard page declares that
summary ID, reads it through `self.data`, and lets registered selectors refresh
its sections. Export serializes those same declared page states into HTML.
