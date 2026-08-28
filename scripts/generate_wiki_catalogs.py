"""Generate drift-prone documentation catalogs from runtime registries."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable

import yaml


ROOT = Path(__file__).resolve().parents[1]
WIKI = ROOT / "wiki"
REFERENCE = ROOT / "reference"
SUMMARY_CATALOG_METADATA = Path(__file__).with_name("summary_catalog_metadata.yaml")
PROCESSOR_OUTPUT_CATALOG_METADATA = Path(__file__).with_name(
    "processor_output_catalog_metadata.yaml"
)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _escape_cell(value: object) -> str:
    text = str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def _inline_list(values: Iterable[object]) -> str:
    items = [f"`{_escape_cell(value)}`" for value in values if str(value)]
    return ", ".join(items) if items else "-"


def _replace_generated_section(
    path: Path,
    *,
    marker: str,
    generated: str,
) -> None:
    start = f"<!-- GENERATED:{marker} START -->"
    end = f"<!-- GENERATED:{marker} END -->"
    text = path.read_text(encoding="utf-8")
    if start not in text or end not in text:
        raise ValueError(f"{path} is missing generated markers for {marker}.")
    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)
    next_text = before + start + "\n" + generated.rstrip() + "\n" + end + after
    if next_text != text:
        path.write_text(next_text, encoding="utf-8")


def _type_name(dtype: object) -> str:
    return str(dtype).replace("Datetime(", "Datetime(")


def _summary_catalog_metadata() -> dict[str, object]:
    return yaml.safe_load(SUMMARY_CATALOG_METADATA.read_text(encoding="utf-8"))


def _processor_output_catalog_metadata() -> dict[str, object]:
    return yaml.safe_load(
        PROCESSOR_OUTPUT_CATALOG_METADATA.read_text(encoding="utf-8")
    )


def _output_fields(definition, metadata: dict[str, object]) -> str:
    return "<br>".join(
        f"`{_escape_cell(name or chr(34) * 2)}` "
        f"(`{_escape_cell(_type_name(dtype))}`): "
        f"{_escape_cell(metadata['fields'][name])}"
        for name, dtype in definition.contract.schema.items()
    ) or "-"


def _required_inputs(definition, input_metadata: dict[str, object]) -> str:
    contract = definition.contract
    table_names = list(contract.required_tables)
    table_names.extend(
        table_name
        for table_name in contract.required_columns
        if table_name not in table_names
    )
    if not table_names:
        return "None declared."

    rendered_tables: list[str] = []
    for table_name in table_names:
        table_metadata = input_metadata[table_name]
        parts = [
            f"`{_escape_cell(table_name)}`: "
            f"{_escape_cell(table_metadata['description'])}"
        ]
        for field_name in contract.required_columns.get(table_name, ()):
            field_metadata = table_metadata["fields"][field_name]
            parts.append(
                f"&bull; `{_escape_cell(field_name)}` "
                f"(`{_escape_cell(field_metadata['type'])}`): "
                f"{_escape_cell(field_metadata['description'])}"
            )
        rendered_tables.append("<br>".join(parts))
    return "<br><br>".join(rendered_tables)


def _summary_function(definition) -> str:
    builder_name = (
        f"{definition.builder.__module__}."
        f"{getattr(definition.builder, '__name__', '<callable>')}"
    )
    default = "yes" if definition.build_by_default else "no"
    return f"`{_escape_cell(builder_name)}`<br>Default build: **{default}**"


def _category_dashboard_pages(summary_ids: set[str]) -> list[str]:
    from dashboard.page_registry import all_page_definitions

    titles: list[str] = []
    for page in all_page_definitions():
        page_summary_ids = {
            *page.required_summary_ids,
            *page.optional_summary_ids,
        }
        if summary_ids.intersection(page_summary_ids) and page.title not in titles:
            titles.append(page.title)
    return titles


def _sidecar_fields(schema, descriptions: dict[str, str]) -> str:
    return "<br>".join(
        f"`{_escape_cell(name)}` (`{_escape_cell(_type_name(dtype))}`): "
        f"{_escape_cell(descriptions[name])}"
        for name, dtype in schema.items()
    )


def build_summary_catalog() -> str:
    from processor.summarize.catalog import SUMMARY_DEFINITIONS

    catalog_metadata = _summary_catalog_metadata()
    definitions = {
        definition.summary_id: definition for definition in SUMMARY_DEFINITIONS
    }
    default_count = sum(
        definition.build_by_default for definition in SUMMARY_DEFINITIONS
    )
    lines: list[str] = [
        "_Generated from `processor.summarize.catalog.SUMMARY_DEFINITIONS` and "
        "`scripts/summary_catalog_metadata.yaml`._",
        "",
        f"Registered summaries: **{len(SUMMARY_DEFINITIONS)}**; "
        f"built by default: **{default_count}**.",
        "",
    ]

    for category in catalog_metadata["categories"]:
        lines.extend([f"### {category['name']}", ""])
        dashboard_pages = _category_dashboard_pages(
            {summary["id"] for summary in category["summaries"]}
        )
        if dashboard_pages:
            pages = ", ".join(_escape_cell(title) for title in dashboard_pages)
            lines.extend(
                [
                    "_Related dashboard pages: "
                    f"{pages}. See the "
                    "[Dashboard User Guide](16-dashboard-user-guide.md#page-by-page-guide)._",
                    "",
                ]
            )
        lines.extend(
            [
                "| Summary Table | Information and Analytical Use | Required Tables/Fields | Output Fields | Summary Function |",
                "|---|---|---|---|---|",
            ]
        )
        for metadata in category["summaries"]:
            definition = definitions[metadata["id"]]
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{_escape_cell(definition.summary_id)}`<br>"
                        f"`{_escape_cell(definition.filename)}.csv`",
                        _escape_cell(metadata["description"]),
                        _required_inputs(
                            definition,
                            catalog_metadata["required_inputs"],
                        ),
                        _output_fields(definition, metadata),
                        _summary_function(definition),
                    ]
                )
                + " |"
            )
        lines.append("")

    return "\n".join(lines)


def build_processor_output_reference() -> str:
    from processor.summarize.catalog import SUMMARY_DEFINITIONS
    from processor.skimjoin.hypothetical_sidecars import (
        TOUR_HYPOTHETICAL_SIDECAR_SCHEMA,
        TRIP_HYPOTHETICAL_SIDECAR_SCHEMA,
    )

    catalog_metadata = _summary_catalog_metadata()
    output_metadata = _processor_output_catalog_metadata()
    definitions = {
        definition.summary_id: definition for definition in SUMMARY_DEFINITIONS
    }
    external_category = next(
        category
        for category in catalog_metadata["categories"]
        if category["name"] == "Externally Supplied Validation Contracts"
    )
    processor_categories = [
        category
        for category in catalog_metadata["categories"]
        if category is not external_category
    ]
    processor_summary_ids = {
        summary["id"]
        for category in processor_categories
        for summary in category["summaries"]
    }
    default_count = sum(
        definition.build_by_default
        for definition in SUMMARY_DEFINITIONS
        if definition.summary_id in processor_summary_ids
    )
    lines: list[str] = [
        "_Generated from the ActivitySim Visualizer processor contracts and "
        "analytical metadata._",
        "",
        "## 1. Prepared Output Tables",
        "",
        "Prepared caches contain eight canonical tables in the configured "
        "Parquet or CSV format. Each file is named "
        "`<prepared_table>.<parquet|csv>`. Prepare preserves the source columns "
        "described earlier in the Model Outputs documentation; the field tables "
        "below list the stable canonical and processor-derived additions. "
        "Configuration-specific category mappings and skim outputs can add "
        "further columns.",
        "",
    ]
    for output in output_metadata["prepared_outputs"]:
        shared_fields = catalog_metadata["required_inputs"].get(
            output["runtime_name"], {}
        ).get("fields", {})
        fields = {**shared_fields, **output["fields"]}
        lines.extend(
            [
                f"### `{_escape_cell(output['table_id'])}` Prepared Table",
                "",
                f"_Processor runtime name: "
                f"`{_escape_cell(output['runtime_name'])}`._",
                "",
                f"**Information and analytical use.** "
                f"{_escape_cell(output['description'])}",
                "",
                "Retained source fields keep their source meaning and generally "
                "keep their source type.",
                "",
                "| Field | Type | Description |",
                "|---|---|---|",
            ]
        )
        for name, field_metadata in fields.items():
            lines.append(
                f"| `{_escape_cell(name)}` | "
                f"`{_escape_cell(field_metadata['type'])}` | "
                f"{_escape_cell(field_metadata['description'])} |"
            )
        lines.append("")
    lines.extend(
        [
            "",
            "## 2. Summary Output Tables",
            "",
            f"The processor calculates **{len(processor_summary_ids)}** summary "
            f"contracts: **{default_count}** in the standard workflow and "
            f"**{len(processor_summary_ids) - default_count}** optional skim ECDF "
            "tables. The same schemas apply to weighted, unweighted, and "
            "segmented cache variants.",
            "",
            "Every summary table is saved as a CSV file named "
            "`<summary_table>.csv`.",
            "",
        ]
    )
    for category in processor_categories:
        lines.extend(
            [
                f"### {category['name']}",
                "",
                "| Summary Table | Information and Analytical Use | Fields |",
                "|---|---|---|",
            ]
        )
        for metadata in category["summaries"]:
            definition = definitions[metadata["id"]]
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{_escape_cell(definition.summary_id)}`",
                        _escape_cell(metadata["description"]),
                        _output_fields(definition, metadata),
                    ]
                )
                + " |"
            )
        lines.append("")

    sidecar_schemas = {
        "trip_hypothetical_skims": TRIP_HYPOTHETICAL_SIDECAR_SCHEMA,
        "tour_hypothetical_skims": TOUR_HYPOTHETICAL_SIDECAR_SCHEMA,
    }
    lines.extend(
        [
            "## 3. Hypothetical All-Modes Skim Tables",
            "",
            "These optional long-form tables evaluate skim components for all "
            "configured modes, not only the observed mode. Each file uses the "
            "prepared-cache format and is named "
            "`<hypothetical_skim_table>.<parquet|csv>`. Operational skimjoin QA "
            "report CSVs are outside the scope of this reference.",
            "",
            "| Hypothetical Skim Table | Information and Analytical Use | Fields |",
            "|---|---|---|",
        ]
    )
    for sidecar in output_metadata["conditional_sidecars"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{_escape_cell(sidecar['attribute'])}`",
                    _escape_cell(sidecar["description"]),
                    _sidecar_fields(
                        sidecar_schemas[sidecar["attribute"]],
                        sidecar["fields"],
                    ),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## 4. Externally Supplied Table Schemas",
            "",
            "**These tables are not created by the processor.** They are "
            "registered schemas for validation files supplied through "
            "`summary_table_map`. A mapped file can be CSV or Parquet and its "
            "configured filename does not need to match the schema name.",
            "",
            "| Externally Supplied Table Schema | Information and Analytical Use | Fields |",
            "|---|---|---|",
        ]
    )
    for metadata in external_category["summaries"]:
        definition = definitions[metadata["id"]]
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{_escape_cell(definition.summary_id)}`",
                    _escape_cell(metadata["description"]),
                    _output_fields(definition, metadata),
                ]
            )
            + " |"
        )
    lines.append("")

    return "\n".join(lines)


def _validate_summary_reference() -> None:
    """Keep the analytical metadata aligned with runtime declarations."""
    from processor.summarize.catalog import SUMMARY_DEFINITIONS

    definitions = {
        definition.summary_id: definition for definition in SUMMARY_DEFINITIONS
    }
    catalog_metadata = _summary_catalog_metadata()
    metadata = [
        summary
        for category in catalog_metadata["categories"]
        for summary in category["summaries"]
    ]
    metadata_ids = [summary["id"] for summary in metadata]
    problems: list[str] = []
    duplicate_ids = sorted(
        summary_id
        for summary_id in set(metadata_ids)
        if metadata_ids.count(summary_id) > 1
    )
    if duplicate_ids:
        problems.append("duplicate summaries: " + ", ".join(duplicate_ids))

    missing_ids = sorted(set(definitions) - set(metadata_ids))
    extra_ids = sorted(set(metadata_ids) - set(definitions))
    if missing_ids:
        problems.append("missing summaries: " + ", ".join(missing_ids))
    if extra_ids:
        problems.append("unknown summaries: " + ", ".join(extra_ids))

    for summary in metadata:
        definition = definitions.get(summary["id"])
        if definition is None:
            continue
        documented_fields = tuple(summary["fields"])
        declared_fields = tuple(definition.contract.schema)
        if documented_fields != declared_fields:
            problems.append(f"{summary['id']} fields do not match its schema")

        contract = definition.contract
        required_tables = {
            *contract.required_tables,
            *contract.required_columns,
        }
        for table_name in sorted(required_tables):
            table_metadata = catalog_metadata["required_inputs"].get(table_name)
            if table_metadata is None:
                problems.append(f"{summary['id']} missing input table {table_name}")
                continue
            for field_name in contract.required_columns.get(table_name, ()):
                if field_name not in table_metadata["fields"]:
                    problems.append(
                        f"{summary['id']} missing input field "
                        f"{table_name}.{field_name}"
                    )

    if problems:
        raise ValueError(
            "Summary analytical reference is incomplete: " + "; ".join(problems)
        )


def _validate_processor_output_reference() -> None:
    """Keep prepared and sidecar metadata aligned with runtime cache contracts."""
    from processor.prepare.cache import PREPARED_TABLE_ATTRS, SIDECAR_TABLE_ATTRS
    from processor.skimjoin.hypothetical_sidecars import (
        TOUR_HYPOTHETICAL_SIDECAR_SCHEMA,
        TRIP_HYPOTHETICAL_SIDECAR_SCHEMA,
    )

    metadata = _processor_output_catalog_metadata()
    shared_input_metadata = _summary_catalog_metadata()["required_inputs"]
    prepared = {
        output["runtime_name"]: output for output in metadata["prepared_outputs"]
    }
    declared_prepared = {
        attr_name: (table_id, filename)
        for attr_name, table_id, filename in PREPARED_TABLE_ATTRS
    }
    problems: list[str] = []
    if set(prepared) != set(declared_prepared):
        problems.append("prepared table inventory does not match the cache contract")
    for runtime_name, (table_id, filename) in declared_prepared.items():
        output = prepared.get(runtime_name)
        if output is None:
            continue
        if output["table_id"] != table_id or output["filename"] != filename:
            problems.append(f"{runtime_name} prepared table identity does not match")
        shared_fields = shared_input_metadata.get(runtime_name, {}).get("fields", {})
        duplicated_fields = set(shared_fields).intersection(output["fields"])
        if duplicated_fields:
            problems.append(
                f"{runtime_name} duplicates shared field metadata: "
                + ", ".join(sorted(duplicated_fields))
            )

    sidecars = {
        output["attribute"]: output
        for output in metadata["conditional_sidecars"]
    }
    declared_sidecars = dict(SIDECAR_TABLE_ATTRS)
    if set(sidecars) != set(declared_sidecars):
        problems.append("sidecar table inventory does not match the cache contract")
    schemas = {
        "trip_hypothetical_skims": TRIP_HYPOTHETICAL_SIDECAR_SCHEMA,
        "tour_hypothetical_skims": TOUR_HYPOTHETICAL_SIDECAR_SCHEMA,
    }
    for attribute, filename in declared_sidecars.items():
        output = sidecars.get(attribute)
        if output is None:
            continue
        if output["filename"] != filename:
            problems.append(f"{attribute} sidecar filename does not match")
        if tuple(output["fields"]) != tuple(schemas[attribute]):
            problems.append(f"{attribute} fields do not match its schema")

    if problems:
        raise ValueError(
            "Processor output reference is incomplete: " + "; ".join(problems)
        )


def build_dashboard_page_catalog() -> str:
    from dashboard.page_registry import all_group_definitions, all_page_definitions

    groups = {group.group_id: group for group in all_group_definitions()}
    pages = sorted(
        all_page_definitions(),
        key=lambda page: (
            groups[page.group_id].order if page.group_id in groups else page.order,
            page.order,
            page.page_id,
        ),
    )

    lines: list[str] = [
        "_Generated from the dashboard page registry._",
        "",
        f"Total registered pages: **{len(pages)}**",
        "",
        "| Page ID | Title | Group | Default | Prepared data | Required summaries | Optional summaries | Required prepared tables |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for page in pages:
        group_title = groups[page.group_id].title if page.group_id in groups else "-"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{_escape_cell(page.page_id)}`",
                    _escape_cell(page.title),
                    _escape_cell(group_title),
                    "yes" if page.default_enabled else "no",
                    f"`{_escape_cell(page.prepared_data_mode)}`",
                    _inline_list(page.required_summary_ids),
                    _inline_list(page.optional_summary_ids),
                    _inline_list(page.required_prepared_tables),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Registered Page Groups",
            "",
            "| Group ID | Title | Default page | Default enabled |",
            "|---|---|---|---|",
        ]
    )
    for group in sorted(groups.values(), key=lambda item: (item.order, item.group_id)):
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{_escape_cell(group.group_id)}`",
                    _escape_cell(group.title),
                    f"`{_escape_cell(group.default_page_id)}`"
                    if group.default_page_id
                    else "-",
                    "yes" if group.default_enabled else "no",
                ]
            )
            + " |"
        )

    return "\n".join(lines)


def main() -> None:
    _validate_summary_reference()
    _validate_processor_output_reference()
    _replace_generated_section(
        WIKI / "26-summary-catalog.md",
        marker="SUMMARY-CATALOG",
        generated=build_summary_catalog(),
    )
    _replace_generated_section(
        WIKI / "31-dashboard-pages.md",
        marker="DASHBOARD-PAGE-CATALOG",
        generated=build_dashboard_page_catalog(),
    )
    _replace_generated_section(
        REFERENCE / "processor-output-table-reference.md",
        marker="PROCESSOR-OUTPUT-REFERENCE",
        generated=build_processor_output_reference(),
    )


if __name__ == "__main__":
    main()
