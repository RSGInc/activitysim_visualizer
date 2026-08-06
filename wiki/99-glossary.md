# 99 - Glossary

| Term | Meaning |
|---|---|
| ActivitySim output | Raw model output tables such as households, persons, tours, trips, and land use. |
| Analysis unit | One full run or one related segment slice passed to the standard summary builders. |
| Availability state | Stored table or summary status: `available`, `empty`, `unavailable`, or `failed`. Dashboard selections add `missing` and `schema_mismatch` when inspecting a requested input. |
| Cache identity | Normalized input, configuration, upstream-manifest, and implementation information used to decide whether an artifact is reusable. It is recorded in manifests and is not the same as write time. |
| Dashboard page | One registered visualizer page with a stable `page_id`. |
| Dashboard page group | Registered navigation container with a stable group ID, ordered child pages, a default child, and default-enabled behavior. |
| Dashboard state | Shared visualizer state such as weighting mode, value mode, segmentation, and loaded runs. |
| Export | Standalone HTML dashboard output that does not require a Python server. |
| Extension | Trusted importable code or external data that adds weighting behavior, summaries, prepared fields/tables, pages, or hosting integration through a documented boundary. |
| Failure policy | Config choice that either records a stage/builder failure as diagnostics and continues (`record`) or raises it and stops (`error`). Not every subsystem exposes both choices. |
| `file_map` | Run override for raw ActivitySim output file names. |
| `finalweight` | Canonical prepared weight column aggregated by summary builders. |
| Geography aggregation | Named mapping from MAZ or TAZ IDs to a custom spatial system, such as a district or subregion. |
| Live mode | Local Panel dashboard that uses a Python server. |
| MAZ | Micro analysis zone. |
| OMX | Open Matrix file format commonly used for skims. |
| Output Processor | Prepare, skimjoin, segmentation, and summarize workflows. |
| Output Visualizer | Live dashboard and HTML export workflows. |
| Page feature | Page-local object that namespaces a related set of selectors and sections under one feature ID. It is composition within a page, not a discoverable page. |
| Page section | Registered stable page region with a section ID, declared selector dependencies, renderer, and export/data behavior. Selector changes mark only dependent sections stale. |
| Prepared cache | Per-run cache of canonical prepared tables. |
| Prepared-data mode | Page declaration value `none`, `optional`, or `required` that controls whether live prepared caches are requested and whether the page's feature is expected to need them. |
| Prepared table | Normalized table used by summaries and prepared-data pages. |
| `prepared_table_map` | Config mapping that supplies canonical prepared tables directly and skips raw prepare. |
| Run | One ActivitySim scenario/output set shown in the dashboard. |
| `RunData` | Processor dataclass containing one run's canonical prepared tables, optional skim state, table availability, prepare diagnostics, and skimjoin artifacts. Summary builders receive it. |
| Run key | Cache-directory identifier made from a run label. For example, `Build 2035` becomes `build-2035`. Duplicate normalized labels get order-dependent suffixes such as `-1` and `-2`. |
| `RunTables` | Dashboard multi-run table value that keeps usable `(label, DataFrame)` pairs together with exclusions and source IDs while applying fluent Polars operations. |
| Segment | Configured part of prepared data that the workflow summarizes separately. |
| Segmentation type | Named segment definition containing one source and one or more segment IDs. |
| Selector | Registered page-local widget that can refresh sections and participate in export. |
| Skim | Matrix or lookup data that supplies level-of-service values to trips or tours. |
| Skimjoin | Optional processor step that joins skim-derived values to prepared trips and tours. |
| Summary builder | Function that converts `RunData` and `Config` into one summary `DataFrame`. |
| Summary cache | Per-run, per-weighting-mode CSV summary tables consumed by dashboard pages. |
| Summary contract | Builder metadata defining output schema and required inputs. |
| `summary_table_map` | Config mapping from registered summary IDs to dashboard-ready CSV/Parquet files. Mapped tables can replace generated IDs but cannot be reweighted or segmented from aggregate rows. |
| TAZ | Traffic analysis zone. |
| Weighting mode | Registered transform with a version. It supplies prepared `finalweight` values under one cache and dashboard mode ID. Summary builders and prepared-data pages use the values. |

## How The Terms Connect

For a run labeled `Build`, prepare converts raw `final_trips.csv` into the
prepared `trips` table. A summary builder aggregates the canonical `finalweight`
column and writes a registered summary to the run key's weighted and unweighted
cache directories. A dashboard page declares that summary ID and reads it
through `self.data`, while registered selectors refresh its sections. Export
turns the same declared page states into HTML.
