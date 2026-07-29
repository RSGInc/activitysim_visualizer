"""Lifecycle and authoring implementation behind the public page facade."""

from __future__ import annotations

from typing import Callable, TYPE_CHECKING

import panel as pn

from dashboard.state import DashboardState
from dashboard.data_access import (
    PageData,
)
from dashboard.page_diagnostics import PageDiagnostics
from dashboard.rendering import Plotter, RenderContext
from runtime.config import Config
from dashboard.page_declarations import (
    DefaultPolicy,
    OptionProvider,
    PAGE_SELECTOR_STYLESHEET,
    RegisteredPageSection,
    RegisteredPageSelector,
    SectionContent,
    SelectorOptions,
    UNSET,
    default_value,
    option_values,
)

if TYPE_CHECKING:
    from dashboard.page_definitions import DashboardPageDefinition, PreparedDataMode


def _query_capture(value):
    """Return a stable, hashable representation of a query closure value."""
    if value is None or isinstance(value, (str, int, float, bool, bytes)):
        return value
    if isinstance(value, tuple):
        return tuple(_query_capture(item) for item in value)
    if isinstance(value, frozenset):
        return tuple(sorted(_query_capture(item) for item in value))
    return (type(value).__module__, type(value).__qualname__)


class DashboardPage(PageDiagnostics):
    """Persistent controller for one dashboard page.

    Pages own widget instances, page-local cached views, and the summary/prepared-run
    lookups needed to refresh their visible Panel layout.
    """

    definition: DashboardPageDefinition | None = None

    def __init__(self, state: DashboardState, config: Config) -> None:
        if not isinstance(state, DashboardState):
            raise TypeError("DashboardPage requires a DashboardState instance.")
        if not isinstance(config, Config):
            raise TypeError("DashboardPage requires a Config instance.")

        definition = self.definition
        name = definition.title if definition is not None else type(self).__name__
        page_state_id = (
            definition.page_id if definition is not None else type(self).__name__
        )
        self.name = name
        self.state = state
        self.config = config
        self._page_state = state.get_page_state(page_state_id)
        self.data = PageData(
            state,
            weighting_key=lambda: self.weighting_key,
            required_summary_ids=lambda: self.required_summary_ids,
            record_selection=self._record_data_selection,
            warn_missing=self._warn_missing_summary,
            warn_missing_prepared=self._warn_missing_prepared,
        )
        self.view: pn.viewable.Viewable | None = None
        self._registered_selectors: dict[str, RegisteredPageSelector] = {}
        self._registered_sections: dict[str, RegisteredPageSection] = {}
        self._features = []
        self._selector_ids_by_widget_id: dict[int, str] = {}
        self._is_refreshing = False
        self._queued_selector_ids: set[str] = set()
        self._active_section_id: str | None = None

        if type(self).build_page is not DashboardPage.build_page:
            self.view = self.build_page()
            self._validate_registered_components()

    def refresh_if_needed(self) -> None:
        """Refresh the page when its rendered global state is stale."""
        if self._page_state.get("last_rendered_state") != self.state.global_state_key():
            self.refresh(force=True)

    def refresh(self, force: bool = False) -> None:
        """Refresh the page content."""
        current_state_key = self.state.global_state_key()
        last_state_key = self._page_state.get("last_rendered_state")
        global_state_changed = force or last_state_key != current_state_key
        if not force and not global_state_changed and not self._dirty_sections():
            return
        self._page_state["visualization_diagnostics"] = []
        if self._registered_sections:
            if global_state_changed:
                self.on_global_state_changed()
                for section in self._registered_sections.values():
                    section.dirty = True
            self._refresh_registered_sections()
        else:
            self._active_section_id = None
            self._refresh()
        self._page_state["last_rendered_state"] = current_state_key

    def mark_stale(self) -> None:
        """Mark the page stale so the next activation refreshes it."""
        self._page_state["last_rendered_state"] = None
        for section in self._registered_sections.values():
            section.dirty = True

    def mark_section_stale(self, *section_ids: str) -> None:
        """Mark one or more registered sections stale."""
        for section_id in section_ids:
            section = self._registered_sections.get(section_id)
            if section is None:
                raise KeyError(
                    f"Unknown section id {section_id!r} on page {self.name!r}."
                )
            section.dirty = True

    def build_page(self) -> pn.viewable.Viewable:
        raise NotImplementedError

    def sync_controls(self) -> None:
        """Update selector options/values before rendering dirty sections."""

    def export_ignored_selectors(
        self,
        section_id: str,
        selected_values: dict[str, str],
    ) -> set[str]:
        """Return selectors ignored by one export section state."""
        return set()

    def export_canonical_selector_value(
        self,
        section_id: str,
        selector_id: str,
        value: str,
        selected_values: dict[str, str],
    ) -> str:
        """Return the canonical value for one selector during export enumeration."""
        return value

    def on_global_state_changed(self) -> None:
        """Hook for page-local cache invalidation on global dashboard state changes."""

    def selector(
        self,
        selector_id: str,
        *,
        widget: pn.widgets.Widget,
        label: str,
        exportable: bool = True,
        options: OptionProvider | None = None,
        default: DefaultPolicy = "first",
    ) -> pn.widgets.Widget:
        """Register one page-local selector widget."""
        if selector_id in self._registered_selectors:
            raise ValueError(
                f"Dashboard page {self.name!r} declares duplicate selector id {selector_id!r}."
            )
        if hasattr(widget, "name"):
            widget.name = label
        css_classes = list(getattr(widget, "css_classes", []) or [])
        if "page-selector-widget" not in css_classes:
            css_classes.append("page-selector-widget")
        widget.css_classes = css_classes
        stylesheets = list(getattr(widget, "stylesheets", []) or [])
        if PAGE_SELECTOR_STYLESHEET not in stylesheets:
            stylesheets.append(PAGE_SELECTOR_STYLESHEET)
        widget.stylesheets = stylesheets
        selector = RegisteredPageSelector(
            selector_id=selector_id,
            widget=widget,
            label=label,
            exportable=exportable,
            options=options,
            default=default,
        )
        self._registered_selectors[selector_id] = selector
        self._selector_ids_by_widget_id[id(widget)] = selector_id
        widget.param.watch(
            lambda event, sid=selector_id: self._handle_selector_change(sid),
            "value",
        )
        return widget

    def select(
        self,
        selector_id: str,
        label: str,
        *,
        options: SelectorOptions | OptionProvider,
        value: object = UNSET,
        default: DefaultPolicy = "first",
        exportable: bool = True,
        **widget_options,
    ) -> pn.widgets.Select:
        """Create and register the common single-value dropdown selector."""
        provider = options if callable(options) else None
        initial_options = provider() if provider is not None else options
        if value is UNSET:
            value = default_value(initial_options, default)
        widget = pn.widgets.Select(
            name=label,
            options=initial_options,
            value=value,
            **widget_options,
        )
        return self.selector(
            selector_id,
            widget=widget,
            label=label,
            exportable=exportable,
            options=provider,
            default=default,
        )

    def section(
        self,
        section_id: str,
        *,
        selectors: tuple[str, ...] = (),
        export: bool = True,
        export_data_mode: "PreparedDataMode" = "none",
        render: Callable[[], SectionContent],
    ) -> pn.Column:
        """Register one stable page section."""
        if section_id in self._registered_sections:
            raise ValueError(
                f"Dashboard page {self.name!r} declares duplicate section id {section_id!r}."
            )
        unknown_selectors = [
            selector_id
            for selector_id in selectors
            if selector_id not in self._registered_selectors
        ]
        if unknown_selectors:
            raise ValueError(
                f"Dashboard page {self.name!r} section {section_id!r} references unknown selectors: "
                + ", ".join(repr(selector_id) for selector_id in unknown_selectors)
            )
        container = self.new_section()
        self._registered_sections[section_id] = RegisteredPageSection(
            section_id=section_id,
            container=container,
            selector_ids=tuple(selectors),
            export=export,
            export_data_mode=export_data_mode,
            render=render,
        )
        return container

    def section_view(self, section_id: str) -> pn.Column:
        section = self._registered_sections.get(section_id)
        if section is None:
            raise KeyError(f"Unknown section id {section_id!r} on page {self.name!r}.")
        return section.container

    def feature(self, feature_id: str):
        """Create a composable page-local feature with namespaced components."""
        from dashboard.page_features import PageFeature

        if any(feature.feature_id == feature_id for feature in self._features):
            raise ValueError(
                f"Dashboard page {self.name!r} declares duplicate feature id {feature_id!r}."
            )
        feature = PageFeature(self, feature_id)
        self._features.append(feature)
        return feature

    @property
    def features(self) -> tuple:
        return tuple(self._features)

    @property
    def registered_selectors(self) -> tuple[RegisteredPageSelector, ...]:
        return tuple(self._registered_selectors.values())

    @property
    def registered_sections(self) -> tuple[RegisteredPageSection, ...]:
        return tuple(self._registered_sections.values())

    def _dirty_sections(self) -> tuple[RegisteredPageSection, ...]:
        return tuple(
            section for section in self._registered_sections.values() if section.dirty
        )

    def _handle_selector_change(self, selector_id: str) -> None:
        if self._is_refreshing:
            self._queued_selector_ids.add(selector_id)
            return
        self._mark_sections_for_selectors({selector_id})
        self.refresh(force=False)

    def _mark_sections_for_selectors(self, selector_ids: set[str]) -> None:
        for section in self._registered_sections.values():
            if selector_ids.intersection(section.selector_ids):
                section.dirty = True

    def _refresh_registered_sections(self) -> None:
        self._is_refreshing = True
        try:
            rerun_requested = False
            for _ in range(2):
                self._queued_selector_ids.clear()
                self._sync_declared_selectors()
                self.sync_controls()
                dirty_sections = list(self._dirty_sections())
                if not dirty_sections and not self._queued_selector_ids:
                    break
                for section in dirty_sections:
                    self._render_section(section)
                    section.dirty = False
                if not self._queued_selector_ids:
                    break
                self._mark_sections_for_selectors(set(self._queued_selector_ids))
                rerun_requested = True
            if rerun_requested:
                self._queued_selector_ids.clear()
        finally:
            self._is_refreshing = False

    def _render_section(self, section: RegisteredPageSection) -> None:
        previous_section_id = self._active_section_id
        self._active_section_id = section.section_id
        try:
            rendered = section.render()
        finally:
            self._active_section_id = previous_section_id
        if isinstance(rendered, pn.viewable.Viewable):
            objects = [rendered]
        else:
            objects = list(rendered)
        section.container.objects = objects

    def _sync_declared_selectors(self) -> None:
        """Refresh provider-backed options and repair stale selector values."""
        for selector in self._registered_selectors.values():
            if selector.options is None:
                continue
            options = selector.options()
            values = option_values(options)
            selector.widget.options = options
            if selector.widget.value not in values:
                selector.widget.value = default_value(options, selector.default)

    def _validate_registered_components(self) -> None:
        if self.view is None:
            raise ValueError(
                f"Dashboard page {self.name!r} build_page() returned no view."
            )
        if not isinstance(self.view, pn.viewable.Viewable):
            raise TypeError(
                f"Dashboard page {self.name!r} build_page() must return a Panel viewable."
            )

    def new_section(self, *objects, **kwargs) -> pn.Column:
        """Create a stable page section container that can be refreshed in place."""
        kwargs.setdefault("sizing_mode", "stretch_width")
        return pn.Column(*objects, **kwargs)

    @property
    def notes_enabled(self) -> bool:
        """Return whether explanatory calculation notes should be displayed."""
        return bool(getattr(getattr(self, "config", None), "include_notes", True))

    def section_note(self, note_id: str, section: pn.Column) -> pn.pane.HTML:
        """Build a static note associated with one registered page section."""
        registered = next(
            (
                item
                for item in self._registered_sections.values()
                if item.container is section
            ),
            None,
        )
        if registered is None:
            raise ValueError(
                f"Dashboard page {self.name!r} cannot annotate an unregistered section."
            )
        if not self.notes_enabled:
            return pn.pane.HTML("", sizing_mode="stretch_width", margin=0)
        from dashboard.calculation_notes import calculation_note

        note = calculation_note(note_id)
        note._calculation_note_target_id = id(section)
        note._calculation_note_section_id = registered.section_id
        section._calculation_note_id = note_id
        return note

    def noted_section(self, note_id: str, section: pn.Column) -> pn.Column:
        """Pair a static calculation note with a selector-driven section."""
        if not self.notes_enabled:
            return section
        note = self.section_note(note_id, section)
        wrapper = self.new_section(
            section,
            note,
            css_classes=["calculation-note-section"],
        )
        wrapper._calculation_note_id = note_id
        wrapper._calculation_note_section_id = note._calculation_note_section_id
        return wrapper

    def noted_view(
        self,
        note_id: str,
        view: pn.viewable.Viewable,
    ) -> pn.viewable.Viewable:
        """Place one calculation note immediately below one plot or table."""
        if not self.notes_enabled:
            return view
        from dashboard.calculation_notes import calculation_note

        note = calculation_note(note_id)
        note._calculation_note_target_id = id(view)
        wrapper = self.new_section(
            view,
            note,
            css_classes=["calculation-note-view"],
        )
        wrapper._calculation_note_id = note_id
        return wrapper

    @property
    def as_percent(self) -> bool:
        """Return whether the current display mode should show percentages."""
        return self.state.value_mode == "Percent"

    @property
    def plot(self) -> Plotter:
        """Return a plotter bound to the current immutable render state."""
        return Plotter(RenderContext.from_dashboard(self.config, self.state))

    @property
    def weighting_key(self) -> str:
        """Return the current weighting key used for summary-table lookup."""
        return self.state.weighting_key()

    @classmethod
    def page_id(cls) -> str | None:
        """Return the registered page id when one has been assigned."""
        return cls.definition.page_id if cls.definition is not None else None

    @classmethod
    def page_title(cls) -> str | None:
        """Return the registered page title when one has been assigned."""
        return cls.definition.title if cls.definition is not None else None

    @property
    def required_summary_ids(self) -> tuple[str, ...]:
        if self.definition is None:
            return ()
        return self.definition.required_summary_ids

    @property
    def optional_summary_ids(self) -> tuple[str, ...]:
        if self.definition is None:
            return ()
        return self.definition.optional_summary_ids

    @property
    def prepared_data_mode(self) -> str:
        if self.definition is None:
            return "none"
        return self.definition.prepared_data_mode

    def query(self, factory: Callable):
        """Memoize one section query from declared state and captured arguments.

        Authors provide only the transformation. The framework derives identity
        from the page, global state, active section, that section's selectors,
        the callable location, and values captured by the callable.
        """
        page_cache_id = self.page_id() or self.name
        section_id = self._active_section_id or "*"
        section = self._registered_sections.get(section_id)
        selector_ids = section.selector_ids if section is not None else ()
        selector_values = tuple(
            (
                selector_id,
                _query_capture(self._registered_selectors[selector_id].widget.value),
            )
            for selector_id in selector_ids
        )
        code = getattr(factory, "__code__", None)
        callable_id = (
            getattr(factory, "__module__", type(factory).__module__),
            getattr(factory, "__qualname__", type(factory).__qualname__),
            getattr(code, "co_filename", None),
            getattr(code, "co_firstlineno", None),
        )
        closure = tuple(
            _query_capture(cell.cell_contents)
            for cell in (getattr(factory, "__closure__", None) or ())
        )
        defaults = _query_capture(getattr(factory, "__defaults__", None))
        keyword_defaults = _query_capture(getattr(factory, "__kwdefaults__", None))
        return self.state.get_or_create_cached(
            "page_query",
            page_cache_id,
            self.state.global_state_key(),
            section_id,
            selector_values,
            callable_id,
            closure,
            defaults,
            keyword_defaults,
            factory=factory,
        )

    def clear_query_cache(self) -> None:
        """Clear memoized queries for this page."""
        page_cache_id = self.page_id() or self.name
        cache = self.state.get_cache("page_query")
        stale_keys = [key for key in cache if key[0] == page_cache_id]
        for key in stale_keys:
            cache.pop(key, None)

    def _refresh(self) -> None:
        raise NotImplementedError
