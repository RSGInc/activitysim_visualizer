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
| Run key | Stable cache-facing identifier derived from a run entry. |
| Segment | Configured slice of prepared data summarized separately. |
| Selector | Registered page-local widget that can refresh sections and participate in export. |
| Skim | Matrix or lookup data used to attach level-of-service values to trips/tours. |
| Skimjoin | Optional processor step that joins skim-derived values to prepared trips and tours. |
| Summary builder | Function that converts `RunData` and `Config` into one summary `DataFrame`. |
| Summary cache | Per-run, per-weighting-mode CSV summary tables consumed by dashboard pages. |
| Summary contract | Builder metadata defining output schema and required inputs. |
| TAZ | Traffic analysis zone. |
| Weighting mode | Dashboard/cache mode such as weighted or unweighted. |

