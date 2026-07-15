"""Central registry helpers for dashboard page and group definitions."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import importlib
import pkgutil

from runtime.logging import get_logger
import dashboard.pages as dashboard_pages_package
from dashboard import DashboardState
from dashboard.data_access import DashboardPreparedRunProvider
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import (
    DashboardDataRequirements,
    DashboardGroupDefinition,
    DashboardPageDefinition,
    PreparedDataMode,
)
from processor.models import PREPARED_TABLE_NAMES, PreparedTableName, RunData
from processor.summarize.catalog import SUMMARY_BY_ID
from runtime.config import Config
from runtime.config.models import DashboardPageConfigEntry

LOGGER = get_logger("dashboard.page_registry")
VALID_PREPARED_DATA_MODES: tuple[PreparedDataMode, ...] = (
    "none",
    "optional",
    "required",
)


@dataclass(frozen=True)
class DashboardNavigationEntry:
    """Resolved top-level dashboard navigation item."""

    entry_id: str
    title: str
    page_definitions: tuple[DashboardPageDefinition, ...]
    group_definition: DashboardGroupDefinition | None = None


def _load_discovered_modules() -> tuple[
    tuple[object, ...],
    tuple[tuple[DashboardGroupDefinition, tuple[object, ...]], ...],
]:
    """Return discovered standalone modules and grouped child modules."""
    package_name = dashboard_pages_package.__name__
    standalone_modules: list[object] = []
    grouped_modules: list[tuple[DashboardGroupDefinition, tuple[object, ...]]] = []

    for module_info in pkgutil.iter_modules(dashboard_pages_package.__path__):
        if module_info.name.startswith("_"):
            continue
        module_name = f"{package_name}.{module_info.name}"
        if not module_info.ispkg:
            standalone_modules.append(importlib.import_module(module_name))
            continue

        package_module = importlib.import_module(module_name)
        group_definition = getattr(package_module, "GROUP", None)
        if not isinstance(group_definition, DashboardGroupDefinition):
            raise TypeError(
                f"{module_name}.GROUP must be a DashboardGroupDefinition instance."
            )
        child_modules: list[object] = []
        for child_info in pkgutil.iter_modules(package_module.__path__):
            if child_info.name.startswith("_"):
                continue
            child_modules.append(
                importlib.import_module(f"{module_name}.{child_info.name}")
            )
        if not child_modules:
            raise ValueError(
                f"Dashboard page group {group_definition.group_id!r} does not contain any child page modules."
            )
        grouped_modules.append((group_definition, tuple(child_modules)))

    return tuple(standalone_modules), tuple(grouped_modules)


@lru_cache(maxsize=1)
def all_group_definitions() -> tuple[DashboardGroupDefinition, ...]:
    """Return all registered top-level dashboard page groups."""
    _, grouped_modules = _load_discovered_modules()
    group_definitions = [group_definition for group_definition, _ in grouped_modules]
    seen_group_ids: set[str] = set()
    seen_titles: set[str] = set()
    for group_definition in group_definitions:
        if group_definition.group_id in seen_group_ids:
            raise ValueError(
                f"Duplicate dashboard page group id discovered: {group_definition.group_id!r}."
            )
        if group_definition.title in seen_titles:
            raise ValueError(
                f"Duplicate dashboard page group title discovered: {group_definition.title!r}."
            )
        seen_group_ids.add(group_definition.group_id)
        seen_titles.add(group_definition.title)
    return tuple(
        sorted(
            group_definitions,
            key=lambda group_definition: (
                group_definition.order,
                group_definition.group_id,
            ),
        )
    )


@lru_cache(maxsize=1)
def all_page_definitions() -> tuple[DashboardPageDefinition, ...]:
    """Return all registered dashboard leaf pages in the current default order."""
    standalone_modules, grouped_modules = _load_discovered_modules()
    page_definitions: list[DashboardPageDefinition] = []

    for module in standalone_modules:
        page_definition = _page_definition_from_module(module)
        _validate_page_definition(page_definition)
        page_definitions.append(page_definition)

    group_lookup = {
        group_definition.group_id: group_definition
        for group_definition in all_group_definitions()
    }
    for group_definition, child_modules in grouped_modules:
        for module in child_modules:
            page_definition = _page_definition_from_module(module)
            if page_definition.group_id != group_definition.group_id:
                raise ValueError(
                    f"Dashboard page {page_definition.page_id!r} must declare group_id={group_definition.group_id!r}."
                )
            _validate_page_definition(page_definition)
            if page_definition.group_id not in group_lookup:
                raise ValueError(
                    f"Dashboard page {page_definition.page_id!r} declares unknown group_id {page_definition.group_id!r}."
                )
            page_definitions.append(page_definition)

    unique_page_definitions: list[DashboardPageDefinition] = []
    seen_definition_objects: set[int] = set()
    for page_definition in page_definitions:
        definition_id = id(page_definition)
        if definition_id in seen_definition_objects:
            continue
        seen_definition_objects.add(definition_id)
        unique_page_definitions.append(page_definition)
    page_definitions = unique_page_definitions

    seen_page_ids: set[str] = set()
    seen_titles: set[str] = set()
    for page_definition in page_definitions:
        if page_definition.page_id in seen_page_ids:
            raise ValueError(
                f"Duplicate dashboard page id discovered: {page_definition.page_id!r}."
            )
        if page_definition.title in seen_titles:
            raise ValueError(
                f"Duplicate dashboard page title discovered: {page_definition.title!r}."
            )
        seen_page_ids.add(page_definition.page_id)
        seen_titles.add(page_definition.title)

    return tuple(
        sorted(
            page_definitions,
            key=lambda page_definition: (
                _page_sort_order(page_definition),
                page_definition.order,
                page_definition.page_id,
            ),
        )
    )


def _page_definition_from_module(module: object) -> DashboardPageDefinition:
    page_classes = [
        value
        for value in vars(module).values()
        if isinstance(value, type)
        and issubclass(value, DashboardPage)
        and value is not DashboardPage
        and value.__module__ == module.__name__
    ]
    if not page_classes:
        raise ValueError(
            f"{module.__name__} must declare one @dashboard_page class."
        )
    if len(page_classes) > 1:
        raise ValueError(
            f"{module.__name__} declares multiple DashboardPage classes; "
            "each page module must contain exactly one."
        )
    page_definition = page_classes[0].definition
    if not isinstance(page_definition, DashboardPageDefinition):
        raise TypeError(
            f"{module.__name__}.{page_classes[0].__name__} must use @dashboard_page."
        )
    page_cls = page_definition.page_cls
    if page_cls is None:
        raise ValueError(
            f"Dashboard page {page_definition.page_id!r} does not declare a page class."
        )
    return page_definition


def _page_sort_order(page_definition: DashboardPageDefinition) -> int:
    if not page_definition.group_id:
        return page_definition.order
    group_definition = group_definition_by_id(page_definition.group_id)
    if group_definition is None:
        return page_definition.order
    return group_definition.order


def _validate_page_definition(page_definition: DashboardPageDefinition) -> None:
    """Validate one discovered dashboard page definition."""
    if page_definition.prepared_data_mode not in VALID_PREPARED_DATA_MODES:
        raise ValueError(
            f"Dashboard page {page_definition.page_id!r} declares invalid prepared_data_mode "
            f"{page_definition.prepared_data_mode!r}."
        )

    required_summary_ids = page_definition.required_summary_ids
    optional_summary_ids = page_definition.optional_summary_ids
    if len(set(required_summary_ids)) != len(required_summary_ids):
        raise ValueError(
            f"Dashboard page {page_definition.page_id!r} declares duplicate required_summary_ids."
        )
    if len(set(optional_summary_ids)) != len(optional_summary_ids):
        raise ValueError(
            f"Dashboard page {page_definition.page_id!r} declares duplicate optional_summary_ids."
        )
    summary_id_overlap = sorted(set(required_summary_ids).intersection(optional_summary_ids))
    if summary_id_overlap:
        raise ValueError(
            f"Dashboard page {page_definition.page_id!r} declares summary ids as both required and optional: "
            + ", ".join(repr(summary_id) for summary_id in summary_id_overlap)
        )
    required_prepared_tables = page_definition.required_prepared_tables
    if len(set(required_prepared_tables)) != len(required_prepared_tables):
        raise ValueError(
            f"Dashboard page {page_definition.page_id!r} declares duplicate required_prepared_tables."
        )
    unknown_prepared_tables = [
        table_name
        for table_name in required_prepared_tables
        if table_name not in PREPARED_TABLE_NAMES
    ]
    if unknown_prepared_tables:
        raise ValueError(
            f"Dashboard page {page_definition.page_id!r} declares unknown prepared tables: "
            + ", ".join(repr(table_name) for table_name in unknown_prepared_tables)
        )
    if page_definition.prepared_data_mode == "none" and required_prepared_tables:
        raise ValueError(
            f"Dashboard page {page_definition.page_id!r} declares required_prepared_tables "
            "but prepared_data_mode is 'none'."
        )
    unknown_summary_ids = [
        summary_id
        for summary_id in (*required_summary_ids, *optional_summary_ids)
        if summary_id not in SUMMARY_BY_ID
    ]
    if unknown_summary_ids:
        raise ValueError(
            f"Dashboard page {page_definition.page_id!r} declares unknown summary ids: "
            + ", ".join(repr(summary_id) for summary_id in unknown_summary_ids)
        )

def _validate_selected_page_definitions(
    page_definitions: (
        list[DashboardPageDefinition] | tuple[DashboardPageDefinition, ...]
    ),
) -> None:
    for page_definition in page_definitions:
        _validate_page_definition(page_definition)


def page_definition_by_id(page_id: str) -> DashboardPageDefinition | None:
    """Look up a registered leaf page definition by stable page id."""
    for page_definition in all_page_definitions():
        if page_definition.page_id == page_id:
            return page_definition
    return None


def group_definition_by_id(group_id: str) -> DashboardGroupDefinition | None:
    """Look up a registered page-group definition by stable group id."""
    for group_definition in all_group_definitions():
        if group_definition.group_id == group_id:
            return group_definition
    return None


def page_definitions_for_group(group_id: str) -> tuple[DashboardPageDefinition, ...]:
    """Return the leaf pages that belong to one group."""
    return tuple(
        page_definition
        for page_definition in all_page_definitions()
        if page_definition.group_id == group_id
    )


def default_page_definitions() -> tuple[DashboardPageDefinition, ...]:
    """Return the default dashboard leaf page set used when config omits `dashboard_pages`."""
    default_pages: list[DashboardPageDefinition] = []
    included_group_ids: set[str] = set()
    for page_definition in all_page_definitions():
        if page_definition.group_id:
            group_definition = group_definition_by_id(page_definition.group_id)
            if group_definition is None or not group_definition.default_enabled:
                continue
            if not page_definition.default_enabled:
                continue
            included_group_ids.add(page_definition.group_id)
            default_pages.append(page_definition)
        elif page_definition.default_enabled:
            default_pages.append(page_definition)
    return tuple(default_pages)


def default_navigation_entries() -> tuple[DashboardNavigationEntry, ...]:
    """Return the default top-level dashboard navigation entries."""
    return navigation_entries_for_pages(default_page_definitions())


def navigation_entries_for_pages(
    page_definitions: (
        list[DashboardPageDefinition] | tuple[DashboardPageDefinition, ...]
    ),
) -> tuple[DashboardNavigationEntry, ...]:
    """Group leaf pages into top-level navigation entries."""
    grouped: list[DashboardNavigationEntry] = []
    seen_entry_ids: set[str] = set()

    for page_definition in page_definitions:
        if not page_definition.group_id:
            grouped.append(
                DashboardNavigationEntry(
                    entry_id=page_definition.page_id,
                    title=page_definition.title,
                    page_definitions=(page_definition,),
                )
            )
            continue

        group_definition = group_definition_by_id(page_definition.group_id)
        if group_definition is None:
            raise ValueError(
                f"Dashboard page {page_definition.page_id!r} declares unknown group_id {page_definition.group_id!r}."
            )
        if group_definition.group_id in seen_entry_ids:
            for index, entry in enumerate(grouped):
                if entry.entry_id == group_definition.group_id:
                    grouped[index] = DashboardNavigationEntry(
                        entry_id=entry.entry_id,
                        title=entry.title,
                        page_definitions=entry.page_definitions + (page_definition,),
                        group_definition=entry.group_definition,
                    )
                    break
            continue

        grouped.append(
            DashboardNavigationEntry(
                entry_id=group_definition.group_id,
                title=group_definition.title,
                page_definitions=(page_definition,),
                group_definition=group_definition,
            )
        )
        seen_entry_ids.add(group_definition.group_id)

    return tuple(grouped)


def _resolve_group_children(
    group_definition: DashboardGroupDefinition,
    entry,
    *,
    error_field_name: str,
) -> list[DashboardPageDefinition]:
    available_children = list(page_definitions_for_group(group_definition.group_id))
    if not available_children:
        raise ValueError(
            f"Dashboard page group {group_definition.group_id!r} does not contain any leaf pages."
        )
    child_by_page_id = {
        page_definition.page_id: page_definition
        for page_definition in available_children
    }

    if entry.mode == "all":
        return available_children
    if entry.mode == "default":
        default_children = [
            page_definition
            for page_definition in available_children
            if page_definition.default_enabled
        ]
        if default_children:
            return default_children
        if group_definition.default_page_id:
            default_child = child_by_page_id.get(group_definition.default_page_id)
            if default_child is None:
                raise ValueError(
                    f"Dashboard page group {group_definition.group_id!r} declares unknown default_page_id {group_definition.default_page_id!r}."
                )
            return [default_child]
        return [available_children[0]]

    if not entry.page_ids:
        default_children = [
            page_definition
            for page_definition in available_children
            if page_definition.default_enabled
        ]
        return default_children or [available_children[0]]

    selected_children: list[DashboardPageDefinition] = []
    unknown_page_ids: list[str] = []
    for child_page_id in entry.page_ids:
        child_definition = child_by_page_id.get(child_page_id)
        if child_definition is None:
            unknown_page_ids.append(child_page_id)
            continue
        if child_definition not in selected_children:
            selected_children.append(child_definition)
    if unknown_page_ids:
        raise ValueError(
            f"Unsupported {error_field_name}.{group_definition.group_id} page entries: "
            + ", ".join(repr(page_id) for page_id in unknown_page_ids)
        )
    return selected_children


def _resolve_page_definitions_from_entries(
    entries: list[DashboardPageConfigEntry],
    *,
    error_field_name: str,
) -> list[DashboardPageDefinition]:
    resolved_pages: list[DashboardPageDefinition] = []
    seen_page_ids: set[str] = set()

    for entry in entries:
        leaf_page = page_definition_by_id(entry.page_id)
        if leaf_page is not None:
            if leaf_page.page_id not in seen_page_ids:
                resolved_pages.append(leaf_page)
                seen_page_ids.add(leaf_page.page_id)
            continue

        group_definition = group_definition_by_id(entry.page_id)
        if group_definition is None:
            raise ValueError(f"Unsupported {error_field_name}: {entry.page_id!r}")
        for child_page in _resolve_group_children(
            group_definition,
            entry,
            error_field_name=error_field_name,
        ):
            if child_page.page_id in seen_page_ids:
                continue
            resolved_pages.append(child_page)
            seen_page_ids.add(child_page.page_id)

    _validate_selected_page_definitions(resolved_pages)
    return resolved_pages


def resolve_live_page_definitions(config: Config) -> list[DashboardPageDefinition]:
    """Resolve the live dashboard leaf pages in display order."""
    if config.dashboard_pages is None:
        page_definitions = list(default_page_definitions())
        _validate_selected_page_definitions(page_definitions)
        return page_definitions
    return _resolve_page_definitions_from_entries(
        config.dashboard_pages,
        error_field_name="dashboard.live.pages entries",
    )


def resolve_live_navigation_entries(config: Config) -> list[DashboardNavigationEntry]:
    """Resolve the live dashboard top-level navigation entries."""
    return list(navigation_entries_for_pages(resolve_live_page_definitions(config)))


def resolve_export_page_definitions(config: Config) -> list[DashboardPageDefinition]:
    """Resolve the export HTML leaf pages in display order."""
    resolved_pages = list(resolve_live_page_definitions(config))
    if not (
        config.export_html.pages_configured
        or config.export_html.exclude_groups
        or config.export_html.exclude_pages
    ):
        return resolved_pages
    export_pages: list[DashboardPageDefinition] = []
    configured_pages = set(config.export_html.pages)
    excluded_groups = set(config.export_html.exclude_groups)
    excluded_pages = set(config.export_html.exclude_pages)
    for page_definition in resolved_pages:
        if config.export_html.pages_configured:
            qualified_page_id = (
                f"{page_definition.group_id}.{page_definition.page_id}"
                if page_definition.group_id
                else page_definition.page_id
            )
            if not (
                page_definition.page_id in configured_pages
                or page_definition.group_id in configured_pages
                or qualified_page_id in configured_pages
            ):
                continue
        if page_definition.group_id and page_definition.group_id in excluded_groups:
            continue
        if page_definition.page_id in excluded_pages:
            continue
        override = config.export_html.page_override(
            page_definition.page_id,
            group_id=page_definition.group_id,
        )
        if override.enabled is False:
            continue
        export_pages.append(page_definition)
    return export_pages


def resolve_export_navigation_entries(config: Config) -> list[DashboardNavigationEntry]:
    """Resolve the export top-level navigation entries."""
    return list(navigation_entries_for_pages(resolve_export_page_definitions(config)))


def enabled_prepared_data_mode_for_pages(
    page_definitions: (
        list[DashboardPageDefinition] | tuple[DashboardPageDefinition, ...]
    ),
) -> PreparedDataMode:
    """Return the strongest prepared-data requirement across a page definition set."""
    mode: PreparedDataMode = "none"
    for page_definition in page_definitions:
        if page_definition.prepared_data_mode == "required":
            return "required"
        if page_definition.prepared_data_mode == "optional":
            mode = "optional"
    return mode


def data_requirements_for_pages(
    page_definitions: (
        list[DashboardPageDefinition] | tuple[DashboardPageDefinition, ...]
    ),
) -> DashboardDataRequirements:
    """Return the summary/prepared-table requirements for a page definition set."""
    required_summary_ids: list[str] = []
    optional_summary_ids: list[str] = []
    required_prepared_tables: list[PreparedTableName] = []
    seen_summary_ids: set[str] = set()
    seen_optional_summary_ids: set[str] = set()
    seen_prepared_tables: set[PreparedTableName] = set()

    for page_definition in page_definitions:
        for summary_id in page_definition.required_summary_ids:
            if summary_id not in seen_summary_ids:
                required_summary_ids.append(summary_id)
                seen_summary_ids.add(summary_id)
        for summary_id in page_definition.optional_summary_ids:
            if summary_id in seen_summary_ids or summary_id in seen_optional_summary_ids:
                continue
            optional_summary_ids.append(summary_id)
            seen_optional_summary_ids.add(summary_id)
        for table_name in page_definition.required_prepared_tables:
            if table_name not in seen_prepared_tables:
                required_prepared_tables.append(table_name)
                seen_prepared_tables.add(table_name)

    return DashboardDataRequirements(
        prepared_data_mode=enabled_prepared_data_mode_for_pages(page_definitions),
        required_summary_ids=tuple(required_summary_ids),
        optional_summary_ids=tuple(optional_summary_ids),
        required_prepared_tables=tuple(required_prepared_tables),
    )


def enabled_prepared_data_mode(config: Config) -> PreparedDataMode:
    return enabled_prepared_data_mode_for_pages(resolve_live_page_definitions(config))


def enabled_export_prepared_data_mode(config: Config) -> PreparedDataMode:
    return enabled_prepared_data_mode_for_pages(resolve_export_page_definitions(config))


def live_data_requirements(config: Config) -> DashboardDataRequirements:
    return data_requirements_for_pages(resolve_live_page_definitions(config))


def export_data_requirements(config: Config) -> DashboardDataRequirements:
    requirements = data_requirements_for_pages(resolve_export_page_definitions(config))
    return DashboardDataRequirements(
        prepared_data_mode="none",
        required_summary_ids=requirements.required_summary_ids,
        optional_summary_ids=requirements.optional_summary_ids,
        required_prepared_tables=(),
    )


def build_prepared_run_provider_for_page_definitions(
    runs: list[tuple[str, RunData]] | None,
    page_definitions: (
        list[DashboardPageDefinition] | tuple[DashboardPageDefinition, ...]
    ),
    *,
    config: Config | None = None,
) -> DashboardPreparedRunProvider:
    prepared_mode = data_requirements_for_pages(page_definitions).prepared_data_mode
    if prepared_mode == "none":
        return DashboardPreparedRunProvider.not_requested()
    if runs:
        provider = DashboardPreparedRunProvider.loaded(runs)
        if config is not None:
            provider.configure_weighting_modes(
                config.weighting_mode_definitions,
                config=config,
            )
        return provider
    return DashboardPreparedRunProvider.unavailable()


def build_dashboard_prepared_run_provider(
    runs: list[tuple[str, RunData]] | None,
    config: Config,
) -> DashboardPreparedRunProvider:
    return build_prepared_run_provider_for_page_definitions(
        runs,
        resolve_live_page_definitions(config),
        config=config,
    )


def build_export_prepared_run_provider(
    runs: list[tuple[str, RunData]] | None,
    config: Config,
) -> DashboardPreparedRunProvider:
    return DashboardPreparedRunProvider.not_requested()


def _build_registered_pages(
    state: DashboardState,
    config: Config,
    page_definitions: (
        list[DashboardPageDefinition] | tuple[DashboardPageDefinition, ...]
    ),
) -> list[DashboardPage]:
    pages: list[DashboardPage] = []
    for page_definition in page_definitions:
        page_cls = page_definition.page_cls
        if page_cls is None:
            raise ValueError(
                f"Dashboard page {page_definition.page_id!r} has no page class."
            )
        pages.append(page_cls(state, config))
    return pages


def build_registered_live_pages(
    state: DashboardState, config: Config
) -> list[DashboardPage]:
    return _build_registered_pages(state, config, resolve_live_page_definitions(config))


def build_registered_export_pages(
    state: DashboardState, config: Config
) -> list[DashboardPage]:
    return _build_registered_pages(
        state, config, resolve_export_page_definitions(config)
    )
