"""Generate drift-prone wiki catalog sections from runtime registries."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
WIKI = ROOT / "wiki"

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


def build_summary_catalog() -> str:
    from processor.summarize.catalog import SUMMARY_DEFINITIONS

    lines: list[str] = [
        "_Generated from `processor.summarize.catalog.SUMMARY_DEFINITIONS`._",
        "",
        f"Total registered summaries: **{len(SUMMARY_DEFINITIONS)}**",
        "",
        "| Summary ID | Filename | Default build | Builder | Output schema | Required inputs |",
        "|---|---|---|---|---|---|",
    ]

    for definition in sorted(
        SUMMARY_DEFINITIONS, key=lambda item: item.summary_id
    ):
        contract = definition.contract
        builder_name = (
            f"{definition.builder.__module__}."
            f"{getattr(definition.builder, '__name__', '<callable>')}"
        )
        schema = "<br>".join(
            f"`{_escape_cell(name)}: {_escape_cell(_type_name(dtype))}`"
            for name, dtype in contract.schema.items()
        ) or "-"
        required_parts: list[str] = []
        if contract.required_tables:
            required_parts.append("tables: " + _inline_list(contract.required_tables))
        for table_name, columns in sorted(contract.required_columns.items()):
            required_parts.append(
                f"{_escape_cell(table_name)}: " + _inline_list(columns)
            )
        required = "<br>".join(required_parts) if required_parts else "-"

        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{_escape_cell(definition.summary_id)}`",
                    f"`{_escape_cell(definition.filename)}.csv`",
                    "yes" if definition.build_by_default else "no",
                    f"`{_escape_cell(builder_name)}`",
                    schema,
                    required,
                ]
            )
            + " |"
        )

    return "\n".join(lines)


def _validate_summary_reference() -> None:
    """Keep the hand-written analytical reference aligned with declarations."""
    from processor.summarize.catalog import SUMMARY_DEFINITIONS

    path = WIKI / "26-summary-catalog.md"
    reference = path.read_text(encoding="utf-8").split(
        "<!-- GENERATED:SUMMARY-CATALOG START -->",
        1,
    )[0]
    missing: list[str] = []
    for definition in SUMMARY_DEFINITIONS:
        prefix = f"| `{definition.summary_id}` |"
        row = next(
            (line for line in reference.splitlines() if line.startswith(prefix)),
            "",
        )
        if not row:
            missing.append(definition.summary_id)
            continue
        absent_fields = [
            field_name
            for field_name in definition.contract.schema
            if field_name and f"`{field_name}`" not in row
        ]
        if absent_fields:
            missing.append(
                f"{definition.summary_id} fields: {', '.join(absent_fields)}"
            )

    if missing:
        raise ValueError(
            "Summary analytical reference is incomplete: " + "; ".join(missing)
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
