"""Central registry helpers for dashboard page definitions."""

from __future__ import annotations

from functools import lru_cache
import importlib
import pkgutil

import dashboard.pages as dashboard_pages_package
from dashboard import DashboardState
from dashboard.data_access import DashboardRawRunProvider
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, RawDataMode
from summarize.reader import Config, RunData

_WARNED_LEGACY_CONFIG_PATHS: set[str] = set()


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
            key=lambda page_definition: (page_definition.order, page_definition.page_id),
        )
    )


def page_definition_by_id(page_id: str) -> DashboardPageDefinition | None:
    """Look up a registered page definition by stable page id."""
    for page_definition in all_page_definitions():
        if page_definition.page_id == page_id:
            return page_definition
    return None


def default_page_definitions() -> tuple[DashboardPageDefinition, ...]:
    """Return the default dashboard page set used when config omits `dashboard_pages`."""
    return tuple(
        page_definition
        for page_definition in all_page_definitions()
        if page_definition.default_enabled
    )


def _warn_missing_dashboard_pages(config: Config) -> None:
    config_path = str(config.config_path)
    if config_path in _WARNED_LEGACY_CONFIG_PATHS:
        return
    print(
        "Warning: config does not define 'dashboard_pages'. "
        "Using legacy behavior and including the default dashboard pages."
    )
    _WARNED_LEGACY_CONFIG_PATHS.add(config_path)


def resolve_page_definitions(config: Config) -> list[DashboardPageDefinition]:
    """Resolve the configured dashboard pages in display order."""
    available_pages = list(all_page_definitions())
    if config.dashboard_pages is None:
        _warn_missing_dashboard_pages(config)
        return list(default_page_definitions())

    available_by_id = {
        page_definition.page_id: page_definition for page_definition in available_pages
    }
    unknown_page_ids = [
        page_id for page_id in config.dashboard_pages if page_id not in available_by_id
    ]
    if unknown_page_ids:
        raise ValueError(
            "Unsupported dashboard_pages entries: "
            + ", ".join(repr(page_id) for page_id in unknown_page_ids)
        )
    return [available_by_id[page_id] for page_id in config.dashboard_pages]


def enabled_raw_data_mode(config: Config) -> RawDataMode:
    """Return the strongest raw-data requirement across the enabled dashboard pages."""
    mode: RawDataMode = "none"
    for page_definition in resolve_page_definitions(config):
        if page_definition.raw_data_mode == "required":
            return "required"
        if page_definition.raw_data_mode == "optional":
            mode = "optional"
    return mode


def build_dashboard_raw_run_provider(
    runs: list[tuple[str, RunData]] | None,
    config: Config,
) -> DashboardRawRunProvider:
    """Return the raw-run provider needed for the enabled dashboard pages."""
    raw_mode = enabled_raw_data_mode(config)
    if raw_mode == "none":
        return DashboardRawRunProvider.not_requested()
    if runs:
        return DashboardRawRunProvider.loaded(runs)
    return DashboardRawRunProvider.unavailable()


def build_registered_live_pages(
    state: DashboardState,
    config: Config,
) -> list[DashboardPage]:
    """Instantiate the registered live dashboard page controllers."""
    pages: list[DashboardPage] = []
    for page_definition in resolve_page_definitions(config):
        controller_cls = page_definition.controller_cls
        if controller_cls is None:
            raise ValueError(
                f"Dashboard page {page_definition.page_id!r} has no controller class."
            )
        pages.append(controller_cls(state, config))
    return pages
