"""Central registry helpers for dashboard page definitions."""

from __future__ import annotations

from functools import lru_cache
import importlib
import pkgutil

from activitysim_viz_logging import get_logger
import dashboard.pages as dashboard_pages_package
from dashboard import DashboardState
from dashboard.data_access import DashboardRawRunProvider
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import (
    DashboardPageDefinition,
    PageSelectorDefinition,
    RawDataMode,
)
from runtime.config import Config
from runtime.models import RunData
from summarize.cache import SUMMARY_SPEC_BY_ID

LOGGER = get_logger("dashboard.page_registry")
VALID_RAW_DATA_MODES: tuple[RawDataMode, ...] = ("none", "optional", "required")


def _load_page_modules():
    """Yield imported dashboard page modules discovered from `dashboard/pages/`."""
    package_name = dashboard_pages_package.__name__
    for module_info in pkgutil.iter_modules(dashboard_pages_package.__path__):
        if module_info.name.startswith("_"):
            continue
        yield importlib.import_module(f"{package_name}.{module_info.name}")


@lru_cache(maxsize=1)
def all_page_definitions() -> tuple[DashboardPageDefinition, ...]:
    """Return all registered dashboard pages in the current default order."""
    page_definitions: list[DashboardPageDefinition] = []
    for module in _load_page_modules():
        page_definition = getattr(module, "PAGE", None)
        if page_definition is None:
            continue
        if not isinstance(page_definition, DashboardPageDefinition):
            raise TypeError(
                f"{module.__name__}.PAGE must be a DashboardPageDefinition instance."
            )
        controller_cls = page_definition.controller_cls
        if controller_cls is None:
            raise ValueError(
                f"Dashboard page {page_definition.page_id!r} does not declare a controller."
            )
        _validate_page_definition(page_definition)
        # Mirror the module-level PAGE object onto the controller class so
        # instantiated pages can recover their registration contract later.
        controller_cls.definition = page_definition
        page_definitions.append(page_definition)

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
                page_definition.order,
                page_definition.page_id,
            ),
        )
    )


def _validate_page_definition(page_definition: DashboardPageDefinition) -> None:
    """Validate one discovered dashboard page definition."""
    if page_definition.raw_data_mode not in VALID_RAW_DATA_MODES:
        raise ValueError(
            f"Dashboard page {page_definition.page_id!r} declares invalid raw_data_mode "
            f"{page_definition.raw_data_mode!r}."
        )

    required_summary_ids = page_definition.required_summary_ids
    if len(set(required_summary_ids)) != len(required_summary_ids):
        raise ValueError(
            f"Dashboard page {page_definition.page_id!r} declares duplicate required_summary_ids."
        )

    unknown_summary_ids = [
        summary_id
        for summary_id in required_summary_ids
        if summary_id not in SUMMARY_SPEC_BY_ID
    ]
    if unknown_summary_ids:
        # Pages reference summaries by stable id. Validating here catches
        # dashboard/summarize registration drift before any render happens.
        raise ValueError(
            f"Dashboard page {page_definition.page_id!r} declares unknown summary ids: "
            + ", ".join(repr(summary_id) for summary_id in unknown_summary_ids)
        )


def _validate_selected_page_definitions(
    page_definitions: (
        list[DashboardPageDefinition] | tuple[DashboardPageDefinition, ...]
    ),
) -> None:
    """Validate only the page definitions enabled for the active workflow."""

    for page_definition in page_definitions:
        _validate_page_definition(page_definition)


def page_definition_by_id(page_id: str) -> DashboardPageDefinition | None:
    """Look up a registered page definition by stable page id."""
    for page_definition in all_page_definitions():
        if page_definition.page_id == page_id:
            return page_definition
    return None


def selector_definition_by_id(
    page_id: str,
    selector_id: str,
) -> PageSelectorDefinition | None:
    """Look up one registered selector definition by page id and selector id."""
    page_definition = page_definition_by_id(page_id)
    if page_definition is None:
        return None
    for selector in page_definition.selectors:
        if selector.selector_id == selector_id:
            return selector
    return None


def exportable_page_selectors() -> list[tuple[DashboardPageDefinition, PageSelectorDefinition]]:
    """Return all exportable page selectors in stable page/selector order."""
    return [
        (page_definition, selector)
        for page_definition in all_page_definitions()
        for selector in page_definition.selectors
        if selector.exportable
    ]


def default_page_definitions() -> tuple[DashboardPageDefinition, ...]:
    """Return the default dashboard page set used when config omits `dashboard_pages`."""
    return tuple(
        page_definition
        for page_definition in all_page_definitions()
        if page_definition.default_enabled
    )


def _resolve_configured_page_definitions(
    configured_page_ids: list[str],
) -> list[DashboardPageDefinition]:
    """Resolve config-facing page ids to registered page definitions."""
    available_pages = list(all_page_definitions())
    available_by_id = {
        page_definition.page_id: page_definition for page_definition in available_pages
    }
    unknown_page_ids = [
        page_id for page_id in configured_page_ids if page_id not in available_by_id
    ]
    if unknown_page_ids:
        raise ValueError(
            "Unsupported configured page ids: "
            + ", ".join(repr(page_id) for page_id in unknown_page_ids)
        )
    duplicate_page_ids = [
        page_id
        for page_id in dict.fromkeys(configured_page_ids)
        if configured_page_ids.count(page_id) > 1
    ]
    if duplicate_page_ids:
        raise ValueError(
            "Duplicate configured page ids are not allowed: "
            + ", ".join(repr(page_id) for page_id in duplicate_page_ids)
        )
    return [available_by_id[page_id] for page_id in configured_page_ids]


def _resolve_page_definitions_for_ids(
    configured_page_ids: list[str] | None,
    *,
    default_to_enabled: bool,
    error_field_name: str,
) -> list[DashboardPageDefinition]:
    """Resolve pages for one workflow using shared ordering and validation."""
    if configured_page_ids is None:
        if default_to_enabled:
            page_definitions = list(default_page_definitions())
            _validate_selected_page_definitions(page_definitions)
            return page_definitions
        return []

    try:
        page_definitions = _resolve_configured_page_definitions(configured_page_ids)
    except ValueError as exc:
        message = str(exc).replace("configured page ids", error_field_name)
        raise ValueError(message) from exc
    _validate_selected_page_definitions(page_definitions)
    return page_definitions


def resolve_live_page_definitions(config: Config) -> list[DashboardPageDefinition]:
    """Resolve the live dashboard pages in display order."""
    return _resolve_page_definitions_for_ids(
        config.dashboard_pages,
        default_to_enabled=True,
        error_field_name="visualizer.dashboard_pages entries",
    )


def resolve_page_definitions(config: Config) -> list[DashboardPageDefinition]:
    """Compatibility alias for the live dashboard page resolver."""
    return resolve_live_page_definitions(config)


def resolve_export_page_definitions(config: Config) -> list[DashboardPageDefinition]:
    """Resolve the export HTML pages in display order."""
    configured_page_ids = (
        list(config.export_html.pages.keys()) if config.export_html.pages_configured else None
    )
    return _resolve_page_definitions_for_ids(
        configured_page_ids,
        default_to_enabled=True,
        error_field_name="visualizer.export_html.pages entries",
    )


def enabled_raw_data_mode_for_pages(
    page_definitions: (
        list[DashboardPageDefinition] | tuple[DashboardPageDefinition, ...]
    ),
) -> RawDataMode:
    """Return the strongest raw-data requirement across a page definition set."""
    mode: RawDataMode = "none"
    for page_definition in page_definitions:
        if page_definition.raw_data_mode == "required":
            return "required"
        if page_definition.raw_data_mode == "optional":
            mode = "optional"
    return mode


def enabled_raw_data_mode(config: Config) -> RawDataMode:
    """Return the strongest raw-data requirement across the enabled dashboard pages."""
    return enabled_raw_data_mode_for_pages(resolve_live_page_definitions(config))


def enabled_export_raw_data_mode(config: Config) -> RawDataMode:
    """Return the strongest raw-data requirement across the enabled export pages."""
    return enabled_raw_data_mode_for_pages(resolve_export_page_definitions(config))


def build_raw_run_provider_for_page_definitions(
    runs: list[tuple[str, RunData]] | None,
    page_definitions: (
        list[DashboardPageDefinition] | tuple[DashboardPageDefinition, ...]
    ),
) -> DashboardRawRunProvider:
    """Return the raw-run provider needed for the given page definition set."""
    raw_mode = enabled_raw_data_mode_for_pages(page_definitions)
    if raw_mode == "none":
        return DashboardRawRunProvider.not_requested()
    if runs:
        return DashboardRawRunProvider.loaded(runs)
    return DashboardRawRunProvider.unavailable()


def build_dashboard_raw_run_provider(
    runs: list[tuple[str, RunData]] | None,
    config: Config,
) -> DashboardRawRunProvider:
    """Return the raw-run provider needed for the enabled dashboard pages."""
    return build_raw_run_provider_for_page_definitions(
        runs,
        resolve_live_page_definitions(config),
    )


def build_export_raw_run_provider(
    runs: list[tuple[str, RunData]] | None,
    config: Config,
) -> DashboardRawRunProvider:
    """Return the raw-run provider needed for the export page set."""
    return build_raw_run_provider_for_page_definitions(
        runs,
        resolve_export_page_definitions(config),
    )


def _build_registered_pages(
    state: DashboardState,
    config: Config,
    page_definitions: (
        list[DashboardPageDefinition] | tuple[DashboardPageDefinition, ...]
    ),
) -> list[DashboardPage]:
    """Instantiate page controllers for an already-resolved definition list."""
    pages: list[DashboardPage] = []
    for page_definition in page_definitions:
        controller_cls = page_definition.controller_cls
        if controller_cls is None:
            raise ValueError(
                f"Dashboard page {page_definition.page_id!r} has no controller class."
            )
        pages.append(controller_cls(state, config))
    return pages


def build_registered_live_pages(
    state: DashboardState,
    config: Config,
) -> list[DashboardPage]:
    """Instantiate the registered live dashboard page controllers."""
    return _build_registered_pages(state, config, resolve_live_page_definitions(config))


def build_registered_export_pages(
    state: DashboardState,
    config: Config,
) -> list[DashboardPage]:
    """Instantiate the registered export page controllers."""
    return _build_registered_pages(
        state,
        config,
        resolve_export_page_definitions(config),
    )
