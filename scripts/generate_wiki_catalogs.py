"""Generate drift-prone wiki catalog sections from runtime registries."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable

import yaml


ROOT = Path(__file__).resolve().parents[1]
WIKI = ROOT / "wiki"
SUMMARY_CATALOG_METADATA = Path(__file__).with_name("summary_catalog_metadata.yaml")

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


def _summary_catalog_metadata() -> list[dict[str, object]]:
    payload = yaml.safe_load(SUMMARY_CATALOG_METADATA.read_text(encoding="utf-8"))
    return payload["categories"]


def build_summary_catalog() -> str:
    from processor.summarize.catalog import SUMMARY_DEFINITIONS

    definitions = {
        definition.summary_id: definition for definition in SUMMARY_DEFINITIONS
    }
    lines: list[str] = [
        "_Generated from `processor.summarize.catalog.SUMMARY_DEFINITIONS` and "
        "`scripts/summary_catalog_metadata.yaml`._",
        "",
        f"Total registered summaries: **{len(SUMMARY_DEFINITIONS)}**",
        "",
        "| Category | Summary / output file | Information and analytical use | Output schema and field definitions | Build / builder | Required inputs |",
        "|---|---|---|---|---|---|",
    ]

    for category in _summary_catalog_metadata():
        for metadata in category["summaries"]:
            definition = definitions[metadata["id"]]
            contract = definition.contract
            builder_name = (
                f"{definition.builder.__module__}."
                f"{getattr(definition.builder, '__name__', '<callable>')}"
            )
            schema = "<br>".join(
                f"`{_escape_cell(name or chr(34) * 2)}` "
                f"(`{_escape_cell(_type_name(dtype))}`): "
                f"{_escape_cell(metadata['fields'][name])}"
                for name, dtype in contract.schema.items()
            ) or "-"
            required_parts: list[str] = []
            if contract.required_tables:
                required_parts.append(
                    "tables: " + _inline_list(contract.required_tables)
                )
            for table_name, columns in sorted(contract.required_columns.items()):
                required_parts.append(
                    f"{_escape_cell(table_name)}: " + _inline_list(columns)
                )
            required = "<br>".join(required_parts) if required_parts else "-"
            build = (
                "Default: "
                + ("yes" if definition.build_by_default else "no")
                + f"<br>`{_escape_cell(builder_name)}`"
            )

            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape_cell(category["name"]),
                        f"`{_escape_cell(definition.summary_id)}`<br>"
                        f"`{_escape_cell(definition.filename)}.csv`",
                        _escape_cell(metadata["description"]),
                        schema,
                        build,
                        required,
                    ]
                )
                + " |"
            )

    return "\n".join(lines)


def _validate_summary_reference() -> None:
    """Keep the analytical metadata aligned with runtime declarations."""
    from processor.summarize.catalog import SUMMARY_DEFINITIONS

    definitions = {
        definition.summary_id: definition for definition in SUMMARY_DEFINITIONS
    }
    metadata = [
        summary
        for category in _summary_catalog_metadata()
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

    if problems:
        raise ValueError(
            "Summary analytical reference is incomplete: " + "; ".join(problems)
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


if __name__ == "__main__":
    main()
