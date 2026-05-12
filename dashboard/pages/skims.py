"""Skim summaries page."""

from __future__ import annotations

import numpy as np
import panel as pn
import polars as pl

from dashboard.components import control_row, data_table, density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition
from processor.models import RunData

TRIP_STATS_SUMMARY_ID = "skimjoin_trip_component_stats"
TOUR_STATS_SUMMARY_ID = "skimjoin_tour_component_stats"
TRIP_ECDF_SUMMARY_ID = "skimjoin_trip_component_ecdf"
TOUR_ECDF_SUMMARY_ID = "skimjoin_tour_component_ecdf"
_DEFAULT_BIN_COUNT = 500


def _nonempty(
    data_list: list[tuple[str, pl.DataFrame]] | None,
) -> list[tuple[str, pl.DataFrame]]:
    return [
        (label, df)
        for label, df in (data_list or [])
        if df is not None and not df.is_empty()
    ]


def _first_nonempty_frame(
    *data_lists: list[tuple[str, pl.DataFrame]] | None,
) -> pl.DataFrame | None:
    for data_list in data_lists:
        for _, df in _nonempty(data_list):
            return df
    return None


def _component_options(
    trip_stats: list[tuple[str, pl.DataFrame]] | None,
    tour_stats: list[tuple[str, pl.DataFrame]] | None,
) -> list[str]:
    components: list[str] = []
    for data_list in (trip_stats, tour_stats):
        for _, df in _nonempty(data_list):
            if "component" not in df.columns:
                continue
            for value in (
                df.select(pl.col("component").cast(pl.Utf8))
                .drop_nulls()
                .unique()
                .sort("component")
                .get_column("component")
                .to_list()
            ):
                if value not in components:
                    components.append(value)
    return components or ["No components available"]


def _mode_options(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    mode_column: str,
    component: str | None,
) -> list[str]:
    first_df = _first_nonempty_frame(data_list)
    if first_df is None or mode_column not in first_df.columns:
        return ["No modes available"]

    options: list[str] = []
    for _, df in _nonempty(data_list):
        filtered = df
        if (
            component
            and component != "No components available"
            and "component" in df.columns
        ):
            filtered = filtered.filter(pl.col("component").cast(pl.Utf8) == component)
        if "n_valid" in filtered.columns:
            filtered = filtered.filter(pl.col("n_valid").cast(pl.Float64) > 0)
        if filtered.is_empty():
            continue
        values = (
            filtered.select(pl.col(mode_column).cast(pl.Utf8))
            .drop_nulls()
            .unique()
            .sort(mode_column)
            .get_column(mode_column)
            .to_list()
        )
        for value in values:
            if value not in options:
                options.append(value)
    return options or ["No modes available"]


def _filter_stats(
    data_list: list[tuple[str, pl.DataFrame]] | None,
    *,
    component: str,
    mode_column: str,
    mode_value: str,
) -> list[tuple[str, pl.DataFrame]]:
    metric_columns = [
        "n_total",
        "n_valid",
        "mean",
        "std",
        "min",
        "max",
        "median",
        "mode",
        "zero_share",
        "missing_share",
    ]
    filtered_list: list[tuple[str, pl.DataFrame]] = []
    for label, df in _nonempty(data_list):
        filtered = (
            df.with_columns(
                pl.col("component").cast(pl.Utf8),
                pl.col(mode_column).cast(pl.Utf8),
            )
            .filter(
                (pl.col("component") == component) & (pl.col(mode_column) == mode_value)
            )
            .select([column for column in metric_columns if column in df.columns])
        )
        filtered_list.append((label, filtered))
    return filtered_list


def _prepared_component_values(
    prepared_runs: list[tuple[str, RunData]] | None,
    *,
    table_name: str,
    mode_column: str,
    mode_value: str,
    component: str,
) -> list[tuple[str, np.ndarray, np.ndarray]]:
    resolved: list[tuple[str, np.ndarray, np.ndarray]] = []
    for label, run in prepared_runs or []:
        df = getattr(run, table_name)
        if df is None or df.is_empty():
            continue
        required_columns = {mode_column, component}
        if not required_columns.issubset(df.columns):
            continue
        filtered = (
            df.with_columns(pl.col(mode_column).cast(pl.Utf8))
            .filter(
                (pl.col(mode_column) == mode_value) & pl.col(component).is_not_null()
            )
            .select(
                pl.col(component).cast(pl.Float64).alias(component),
                (
                    pl.col("finalweight").cast(pl.Float64)
                    if "finalweight" in df.columns
                    else pl.lit(1.0)
                ).alias("finalweight"),
            )
        )
        if filtered.is_empty():
            continue
        values = filtered.get_column(component).to_numpy()
        weights = filtered.get_column("finalweight").to_numpy()
        resolved.append((label, values, weights))
    return resolved


def _distribution_bins(
    prepared_runs: list[tuple[str, RunData]] | None,
    *,
    table_name: str,
    mode_column: str,
    mode_value: str,
    component: str,
    x_range: tuple[float, float] | None = None,
    bin_count: int = _DEFAULT_BIN_COUNT,
) -> list[tuple[str, pl.DataFrame]]:
    value_sets = _prepared_component_values(
        prepared_runs,
        table_name=table_name,
        mode_column=mode_column,
        mode_value=mode_value,
        component=component,
    )
    if not value_sets:
        return []

    all_values = np.concatenate([values for _, values, _ in value_sets])
    if all_values.size == 0:
        return []
    min_value = float(np.min(all_values))
    max_value = float(np.max(all_values))

    if x_range is not None:
        min_value = float(x_range[0])
        max_value = float(x_range[1])

    if min_value == max_value:
        bin_mid = min_value
        return [
            (
                label,
                pl.DataFrame(
                    {
                        "bin_mid": [bin_mid],
                        "freq": [float(np.sum(weights))],
                    }
                ),
            )
            for label, _, weights in value_sets
        ]

    edges = np.linspace(min_value, max_value, num=bin_count + 1)
    mids = ((edges[:-1] + edges[1:]) / 2.0).tolist()
    distributions: list[tuple[str, pl.DataFrame]] = []
    for label, values, weights in value_sets:
        in_range = (values >= min_value) & (values <= max_value)
        histogram_values = values[in_range]
        histogram_weights = weights[in_range]
        if histogram_values.size == 0:
            hist = np.zeros(len(mids), dtype=float)
        else:
            hist, _ = np.histogram(
                histogram_values,
                bins=edges,
                weights=histogram_weights,
            )
        distributions.append(
            (
                label,
                pl.DataFrame(
                    {
                        "bin_mid": mids,
                        "freq": hist.astype(float).tolist(),
                    }
                ),
            )
        )
    return distributions


def _distribution_title(base_title: str, x_range: tuple[float, float] | None) -> str:
    return base_title


def _distribution_data_bounds(
    prepared_runs: list[tuple[str, RunData]] | None,
    *,
    table_name: str,
    mode_column: str,
    mode_value: str,
    component: str,
) -> tuple[float, float] | None:
    value_sets = _prepared_component_values(
        prepared_runs,
        table_name=table_name,
        mode_column=mode_column,
        mode_value=mode_value,
        component=component,
    )
    if not value_sets:
        return None
    all_values = np.concatenate(
        [values for _, values, _ in value_sets if values.size > 0]
    )
    if all_values.size == 0:
        return None
    return (float(np.min(all_values)), float(np.max(all_values)))


def _resolve_distribution_range(
    min_value: float | None,
    max_value: float | None,
) -> tuple[float, float] | None:
    if min_value is None or max_value is None:
        return None
    if not np.isfinite(min_value) or not np.isfinite(max_value):
        return None
    if float(max_value) <= float(min_value):
        return None
    return (float(min_value), float(max_value))


class SkimSummariesPage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        trip_stats = self.state.get_summary_table_set(TRIP_STATS_SUMMARY_ID, "weighted")
        tour_stats = self.state.get_summary_table_set(TOUR_STATS_SUMMARY_ID, "weighted")
        component_options = _component_options(trip_stats, tour_stats)
        initial_component = component_options[0]

        self.component_sel = self.selector(
            "skim_component",
            widget=pn.widgets.Select(
                name="Skim Component",
                options=component_options,
                value=initial_component,
            ),
            label="Skim Component",
        )
        self.trip_mode_sel = self.selector(
            "trip_mode",
            widget=pn.widgets.Select(
                name="Trip Mode",
                options=_mode_options(
                    trip_stats,
                    mode_column="trip_mode",
                    component=initial_component,
                ),
            ),
            label="Trip Mode",
        )
        self.trip_min_sel = self.selector(
            "trip_min",
            widget=pn.widgets.FloatInput(name="Trip Min", step=0.1, value=0.0),
            label="Trip Min",
        )
        self.trip_max_sel = self.selector(
            "trip_max",
            widget=pn.widgets.FloatInput(name="Trip Max", step=0.1, value=1.0),
            label="Trip Max",
        )
        self.trip_reset_btn = pn.widgets.Button(
            name="Reset to full range",
            button_type="default",
            width=150,
        )
        self.tour_mode_sel = self.selector(
            "tour_mode",
            widget=pn.widgets.Select(
                name="Tour Mode",
                options=_mode_options(
                    tour_stats,
                    mode_column="tour_mode",
                    component=initial_component,
                ),
            ),
            label="Tour Mode",
        )
        self.tour_min_sel = self.selector(
            "tour_min",
            widget=pn.widgets.FloatInput(name="Tour Min", step=0.1, value=0.0),
            label="Tour Min",
        )
        self.tour_max_sel = self.selector(
            "tour_max",
            widget=pn.widgets.FloatInput(name="Tour Max", step=0.1, value=1.0),
            label="Tour Max",
        )
        self.tour_reset_btn = pn.widgets.Button(
            name="Reset to full range",
            button_type="default",
            width=150,
        )

        if self.trip_mode_sel.options:
            self.trip_mode_sel.value = self.trip_mode_sel.options[0]
        if self.tour_mode_sel.options:
            self.tour_mode_sel.value = self.tour_mode_sel.options[0]

        self.trip_reset_btn.on_click(
            lambda event: self._reset_distribution_range("trip")
        )
        self.tour_reset_btn.on_click(
            lambda event: self._reset_distribution_range("tour")
        )

        self._trip_section = self.section(
            "skim_trip_summary_section",
            selectors=("skim_component", "trip_mode"),
            render=self.render_trip_summary_section,
        )
        self._trip_distribution_section = self.section(
            "skim_trip_distribution_section",
            selectors=("skim_component", "trip_mode", "trip_min", "trip_max"),
            export_data_mode="required",
            render=self.render_trip_distribution_section,
        )
        self._tour_section = self.section(
            "skim_tour_summary_section",
            selectors=("skim_component", "tour_mode"),
            render=self.render_tour_summary_section,
        )
        self._tour_distribution_section = self.section(
            "skim_tour_distribution_section",
            selectors=("skim_component", "tour_mode", "tour_min", "tour_max"),
            export_data_mode="required",
            render=self.render_tour_distribution_section,
        )

        return self.new_section(
            pn.pane.Markdown("## Skim Summaries"),
            control_row(
                pn.pane.Markdown("**Skim Component:**"),
                self.component_sel,
            ),
            self._trip_section,
            self._trip_distribution_section,
            self._tour_section,
            self._tour_distribution_section,
        )

    def _trip_summaries(self):
        return self.optional_summary(TRIP_STATS_SUMMARY_ID)

    def _tour_summaries(self):
        return self.optional_summary(TOUR_STATS_SUMMARY_ID)

    def _trip_prepared_runs(self):
        return self.get_prepared_runs(weighted=(self.weighting_key == "weighted"))

    def _tour_prepared_runs(self):
        return self.get_prepared_runs(weighted=(self.weighting_key == "weighted"))

    def _trip_ecdf_summaries(self):
        return self.optional_summary(TRIP_ECDF_SUMMARY_ID)

    def _tour_ecdf_summaries(self):
        return self.optional_summary(TOUR_ECDF_SUMMARY_ID)

    def sync_controls(self) -> None:
        trip_stats = self._trip_summaries()
        tour_stats = self._tour_summaries()

        component_options = _component_options(trip_stats, tour_stats)
        self.component_sel.options = component_options
        if self.component_sel.value not in component_options:
            self.component_sel.value = component_options[0]

        trip_mode_options = _mode_options(
            trip_stats,
            mode_column="trip_mode",
            component=self.component_sel.value,
        )
        self.trip_mode_sel.options = trip_mode_options
        if self.trip_mode_sel.value not in trip_mode_options:
            self.trip_mode_sel.value = trip_mode_options[0]

        tour_mode_options = _mode_options(
            tour_stats,
            mode_column="tour_mode",
            component=self.component_sel.value,
        )
        self.tour_mode_sel.options = tour_mode_options
        if self.tour_mode_sel.value not in tour_mode_options:
            self.tour_mode_sel.value = tour_mode_options[0]

        self._sync_distribution_range_controls(
            prefix="trip",
            prepared_runs=self._trip_prepared_runs(),
            table_name="trips",
            mode_column="trip_mode",
            mode_value=self.trip_mode_sel.value,
            component=self.component_sel.value,
        )
        self._sync_distribution_range_controls(
            prefix="tour",
            prepared_runs=self._tour_prepared_runs(),
            table_name="tours",
            mode_column="tour_mode",
            mode_value=self.tour_mode_sel.value,
            component=self.component_sel.value,
        )

    def _sync_distribution_range_controls(
        self,
        *,
        prefix: str,
        prepared_runs: list[tuple[str, RunData]] | None,
        table_name: str,
        mode_column: str,
        mode_value: str,
        component: str,
    ) -> None:
        min_widget = getattr(self, f"{prefix}_min_sel")
        max_widget = getattr(self, f"{prefix}_max_sel")
        context_key = (component, mode_value, self.weighting_key)
        state_key = f"{prefix}_distribution_range_context"
        auto_key = f"{prefix}_distribution_auto_range"

        bounds = _distribution_data_bounds(
            prepared_runs,
            table_name=table_name,
            mode_column=mode_column,
            mode_value=mode_value,
            component=component,
        )
        target_range = bounds
        if target_range is None:
            self._page_state[state_key] = context_key
            self._page_state[auto_key] = None
            return

        last_context = self._page_state.get(state_key)
        last_auto_range = self._page_state.get(auto_key)
        current_range = _resolve_distribution_range(min_widget.value, max_widget.value)

        should_reset = (
            last_context != context_key
            or last_auto_range is None
            or current_range is None
            or (
                current_range is not None
                and last_auto_range is not None
                and tuple(current_range) == tuple(last_auto_range)
            )
        )
        if should_reset:
            min_widget.value = float(target_range[0])
            max_widget.value = float(target_range[1])

        self._page_state[state_key] = context_key
        self._page_state[auto_key] = tuple(target_range)

    def _reset_distribution_range(self, prefix: str) -> None:
        auto_range = self._page_state.get(f"{prefix}_distribution_auto_range")
        if not auto_range:
            return
        min_widget = getattr(self, f"{prefix}_min_sel")
        max_widget = getattr(self, f"{prefix}_max_sel")
        min_widget.value = float(auto_range[0])
        max_widget.value = float(auto_range[1])

    def render_trip_summary_section(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        trip_stats = self._trip_summaries()
        if trip_stats is None:
            return [
                pn.pane.Markdown("### Trip Skims"),
                control_row(
                    pn.pane.Markdown("**Trip Mode:**"),
                    self.trip_mode_sel,
                ),
                self.data_not_available_card(
                    detail="Trip skim summaries require the precomputed skim trip statistics table.",
                    missing_items=[TRIP_STATS_SUMMARY_ID],
                ),
            ]

        component = self.component_sel.value
        trip_mode = self.trip_mode_sel.value
        if component == "No components available" or trip_mode == "No modes available":
            return [
                pn.pane.Markdown("### Trip Skims"),
                control_row(
                    pn.pane.Markdown("**Trip Mode:**"),
                    self.trip_mode_sel,
                ),
                self.data_not_available_card(
                    detail="Trip skim summaries are available only when skim-enriched trip summary tables contain numeric components.",
                    missing_items=[TRIP_STATS_SUMMARY_ID],
                ),
            ]

        trip_stats_data = self.get_filtered_view(
            "skim_trip_stats",
            component,
            trip_mode,
            factory=lambda: _filter_stats(
                trip_stats,
                component=component,
                mode_column="trip_mode",
                mode_value=trip_mode,
            ),
        )
        if not any(not df.is_empty() for _, df in trip_stats_data):
            return [
                pn.pane.Markdown("### Trip Skims"),
                control_row(
                    pn.pane.Markdown("**Trip Mode:**"),
                    self.trip_mode_sel,
                ),
                self.data_not_available_card(
                    detail=f"No trip skim summary data is available for component `{component}` and mode `{trip_mode}`.",
                ),
            ]

        return [
            pn.pane.Markdown("### Trip Skims"),
            control_row(
                pn.pane.Markdown("**Trip Mode:**"),
                self.trip_mode_sel,
            ),
            data_table(
                trip_stats_data,
                title=f"Trip Summary Statistics - {component} / {trip_mode}",
                height=130,
            ),
        ]

    def render_trip_distribution_section(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        component = self.component_sel.value
        trip_mode = self.trip_mode_sel.value
        trip_distribution_x_range = _resolve_distribution_range(
            self.trip_min_sel.value,
            self.trip_max_sel.value,
        )
        if trip_distribution_x_range is None:
            return [
                control_row(
                    pn.pane.Markdown("**Trip Distribution Min:**"),
                    self.trip_min_sel,
                    pn.pane.Markdown("**Trip Distribution Max:**"),
                    self.trip_max_sel,
                    self.trip_reset_btn,
                ),
                self.data_not_available_card(
                    detail="Trip distribution controls require finite values with min less than max.",
                ),
            ]

        trip_distribution_data = self.get_filtered_view(
            "skim_trip_distribution",
            component,
            trip_mode,
            self.weighting_key,
            trip_distribution_x_range[0],
            trip_distribution_x_range[1],
            factory=lambda: _distribution_bins(
                self._trip_prepared_runs(),
                table_name="trips",
                mode_column="trip_mode",
                mode_value=trip_mode,
                component=component,
                x_range=trip_distribution_x_range,
            ),
        )

        trip_distribution_view = (
            density_chart(
                trip_distribution_data,
                x_col="bin_mid",
                y_col="freq",
                title=_distribution_title(
                    f"Trip Distribution - {component} / {trip_mode}",
                    trip_distribution_x_range,
                ),
                xaxis_title="Skim Value",
                yaxis_title="Trips",
                normalize=self.as_percent,
                height=320,
                as_percent=False,
                xaxis_range=trip_distribution_x_range,
            )
            if any(not df.is_empty() for _, df in trip_distribution_data)
            else self.data_not_available_card(
                detail=(
                    "The disaggregated trip skim distribution requires loaded prepared trip "
                    "tables with non-null values for the selected component and mode."
                ),
            )
        )

        return [
            control_row(
                pn.pane.Markdown("**Trip Distribution Min:**"),
                self.trip_min_sel,
                pn.pane.Markdown("**Trip Distribution Max:**"),
                self.trip_max_sel,
                self.trip_reset_btn,
            ),
            trip_distribution_view,
        ]

    def render_tour_summary_section(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        tour_stats = self._tour_summaries()
        if tour_stats is None:
            return [
                pn.pane.Markdown("### Tour Skims"),
                control_row(
                    pn.pane.Markdown("**Tour Mode:**"),
                    self.tour_mode_sel,
                ),
                self.data_not_available_card(
                    detail="Tour skim summaries require the precomputed skim tour statistics table.",
                    missing_items=[TOUR_STATS_SUMMARY_ID],
                ),
            ]

        component = self.component_sel.value
        tour_mode = self.tour_mode_sel.value
        if component == "No components available" or tour_mode == "No modes available":
            return [
                pn.pane.Markdown("### Tour Skims"),
                control_row(
                    pn.pane.Markdown("**Tour Mode:**"),
                    self.tour_mode_sel,
                ),
                self.data_not_available_card(
                    detail="Tour skim summaries are available only when skim-enriched tour summary tables contain numeric components.",
                    missing_items=[TOUR_STATS_SUMMARY_ID],
                ),
            ]

        tour_stats_data = self.get_filtered_view(
            "skim_tour_stats",
            component,
            tour_mode,
            factory=lambda: _filter_stats(
                tour_stats,
                component=component,
                mode_column="tour_mode",
                mode_value=tour_mode,
            ),
        )
        if not any(not df.is_empty() for _, df in tour_stats_data):
            return [
                pn.pane.Markdown("### Tour Skims"),
                control_row(
                    pn.pane.Markdown("**Tour Mode:**"),
                    self.tour_mode_sel,
                ),
                self.data_not_available_card(
                    detail=f"No tour skim summary data is available for component `{component}` and mode `{tour_mode}`.",
                ),
            ]

        return [
            pn.pane.Markdown("### Tour Skims"),
            control_row(
                pn.pane.Markdown("**Tour Mode:**"),
                self.tour_mode_sel,
            ),
            data_table(
                tour_stats_data,
                title=f"Tour Summary Statistics - {component} / {tour_mode}",
                height=130,
            ),
        ]

    def render_tour_distribution_section(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        component = self.component_sel.value
        tour_mode = self.tour_mode_sel.value
        tour_distribution_x_range = _resolve_distribution_range(
            self.tour_min_sel.value,
            self.tour_max_sel.value,
        )
        if tour_distribution_x_range is None:
            return [
                control_row(
                    pn.pane.Markdown("**Tour Distribution Min:**"),
                    self.tour_min_sel,
                    pn.pane.Markdown("**Tour Distribution Max:**"),
                    self.tour_max_sel,
                    self.tour_reset_btn,
                ),
                self.data_not_available_card(
                    detail="Tour distribution controls require finite values with min less than max.",
                ),
            ]

        tour_distribution_data = self.get_filtered_view(
            "skim_tour_distribution",
            component,
            tour_mode,
            self.weighting_key,
            tour_distribution_x_range[0],
            tour_distribution_x_range[1],
            factory=lambda: _distribution_bins(
                self._tour_prepared_runs(),
                table_name="tours",
                mode_column="tour_mode",
                mode_value=tour_mode,
                component=component,
                x_range=tour_distribution_x_range,
            ),
        )

        tour_distribution_view = (
            density_chart(
                tour_distribution_data,
                x_col="bin_mid",
                y_col="freq",
                title=_distribution_title(
                    f"Tour Distribution - {component} / {tour_mode}",
                    tour_distribution_x_range,
                ),
                xaxis_title="Skim Value",
                yaxis_title="Tours",
                normalize=self.as_percent,
                height=320,
                as_percent=False,
                xaxis_range=tour_distribution_x_range,
            )
            if any(not df.is_empty() for _, df in tour_distribution_data)
            else self.data_not_available_card(
                detail=(
                    "The disaggregated tour skim distribution requires loaded prepared tour "
                    "tables with non-null values for the selected component and mode."
                ),
            )
        )

        return [
            control_row(
                pn.pane.Markdown("**Tour Distribution Min:**"),
                self.tour_min_sel,
                pn.pane.Markdown("**Tour Distribution Max:**"),
                self.tour_max_sel,
                self.tour_reset_btn,
            ),
            tour_distribution_view,
        ]


PAGE = DashboardPageDefinition(
    page_id="skims",
    title="Skim Summaries",
    order=40,
    page_cls=SkimSummariesPage,
    default_enabled=False,
    prepared_data_mode="optional",
    required_prepared_tables=("trips", "tours"),
    required_summary_ids=(
        TRIP_STATS_SUMMARY_ID,
        TOUR_STATS_SUMMARY_ID,
    ),
)

SkimSummariesPage.definition = PAGE
