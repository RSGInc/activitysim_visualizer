"""Tour mode choice page."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition


def purpose_options(mode_list: list[tuple[str, pl.DataFrame]]) -> list[str]:
    purpose_set = set()
    for _, df in mode_list:
        if len(df) > 0 and "tour_purpose" in df.columns:
            purpose_set.update(df["tour_purpose"].drop_nulls().cast(pl.Utf8).to_list())
    return sorted(str(purpose) for purpose in purpose_set) if purpose_set else []


def purpose_mapping(raw_purposes: list[str]) -> tuple[list[str], dict[str, str | None]]:
    mapping: dict[str, str | None] = {}
    if "all_tour_purposes" in raw_purposes:
        mapping["Total"] = "all_tour_purposes"
    else:
        mapping["Total"] = None
    for purpose in raw_purposes:
        if purpose not in {"all_tour_purposes", "Total"}:
            mapping[purpose] = purpose
    return list(mapping), mapping


def charts_by_column(
    mode_list: list[tuple[str, pl.DataFrame]],
    purpose: str | None,
    columns: list[str] | None = None,
) -> dict[str, list[tuple[str, pl.DataFrame]]]:
    columns = columns or [
        "tour_count_all_households",
        "tour_count_zero_auto",
        "tour_count_auto_deficient",
        "tour_count_auto_sufficient",
    ]

    def filtered_df(df: pl.DataFrame, column: str) -> pl.DataFrame:
        if purpose is None:
            purpose_col = pl.col("tour_purpose").cast(pl.Utf8)
            return (
                df.filter(~purpose_col.is_in(["all_tour_purposes", "Total"]))
                .group_by("tour_mode")
                .agg(pl.col(column).sum().alias(column))
                .sort("tour_mode")
            )
        return (
            df.filter(pl.col("tour_purpose").cast(pl.Utf8) == purpose)
            .select(["tour_mode", column])
            .sort("tour_mode")
        )

    return {
        col: [(label, filtered_df(df, col)) for label, df in mode_list if col in df.columns]
        for col in columns
    }


class TourModePage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        total_opts = self._purpose_options()
        _, self._purpose_to_raw = purpose_mapping([] if total_opts == ["Total"] else total_opts)
        if not self._purpose_to_raw:
            self._purpose_to_raw = {"Total": None}
        self.purp_sel = self.selector(
            "purpose",
            widget=pn.widgets.Select(name="Tour Purpose", options=total_opts, value=total_opts[0]),
            label="Tour Purpose",
        )
        self._body = self.section(
            "tours_mode_body",
            selectors=("purpose",),
            render=self.render_body,
        )
        return self.new_section(
            pn.pane.Markdown("## Tour Mode Choice"),
            pn.Row(pn.pane.Markdown("**Tour Purpose:**"), self.purp_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self) -> list[str]:
        mode_result = self.state.inspect_summary_table(
            "tour_mode_by_tour_purpose_and_auto_sufficiency",
            weighting_key="weighted",
            required_columns=(
                "tour_purpose",
                "tour_mode",
                "tour_count_all_households",
                "tour_count_zero_auto",
                "tour_count_auto_deficient",
                "tour_count_auto_sufficient",
            ),
        )
        if not mode_result.has_usable_runs:
            return ["Total"]
        raw_purposes = purpose_options([(label, table) for label, table in mode_result.usable_runs])
        options, _ = purpose_mapping(raw_purposes)
        return options or ["Total"]

    def sync_controls(self) -> None:
        mode_result = self.resolve_summary_visualization(
            "tour_mode_auto_sufficiency",
            summary_requirements={
                "tour_mode_by_tour_purpose_and_auto_sufficiency": (
                    "tour_purpose",
                    "tour_mode",
                    "tour_count_all_households",
                    "tour_count_zero_auto",
                    "tour_count_auto_deficient",
                    "tour_count_auto_sufficient",
                )
            },
        )
        if not mode_result.has_usable_runs:
            return
        mode_list = mode_result.usable_by_input["tour_mode_by_tour_purpose_and_auto_sufficiency"]
        raw_purposes = purpose_options(mode_list)
        purp_opts, self._purpose_to_raw = purpose_mapping(raw_purposes)
        if not purp_opts:
            purp_opts = ["Total"]
            self._purpose_to_raw = {"Total": None}
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]

    def render_body(self):
        if not self.state.run_labels:
            return [pn.pane.Markdown("No runs loaded.")]

        mode_result = self.resolve_summary_visualization(
            "tour_mode_auto_sufficiency",
            summary_requirements={
                "tour_mode_by_tour_purpose_and_auto_sufficiency": (
                    "tour_purpose",
                    "tour_mode",
                    "tour_count_all_households",
                    "tour_count_zero_auto",
                    "tour_count_auto_deficient",
                    "tour_count_auto_sufficient",
                )
            },
        )
        if not mode_result.has_usable_runs:
            return [
                self.unavailable_visualization(
                    mode_result,
                    detail="Tour mode summaries are unavailable.",
                )
            ]

        mode_list = mode_result.usable_by_input["tour_mode_by_tour_purpose_and_auto_sufficiency"]
        purp = self.purp_sel.value
        raw_purpose = self._purpose_to_raw.get(purp)

        charts_by_col = self.get_filtered_view(
            "tour_mode",
            raw_purpose,
            tuple(label for label, _ in mode_list),
            factory=lambda: charts_by_column(mode_list, raw_purpose),
        )

        def make_chart(col: str, title: str):
            return bar_chart(
                charts_by_col[col],
                x_col="tour_mode",
                y_col=col,
                title=title,
                xaxis_title="Mode",
                as_percent=self.as_percent,
            )

        body: list[pn.viewable.Viewable] = [
            pn.Row(
                make_chart("tour_count_all_households", "All Households"),
                make_chart("tour_count_zero_auto", "Zero Autos"),
            ),
            pn.Row(
                make_chart("tour_count_auto_deficient", "Autos < Workers"),
                make_chart("tour_count_auto_sufficient", "Autos >= Workers"),
            ),
        ]

        if self.config.mode_groups:
            grouped_result = self.resolve_summary_visualization(
                "tour_mode_grouped_profile",
                summary_requirements={"grouped_tour_mode_profile": ("mode_group", "freq_all")},
            )
            if grouped_result.has_usable_runs:
                grouped_list = grouped_result.usable_by_input["grouped_tour_mode_profile"]
                body.extend(
                    [
                        pn.pane.Markdown("### Grouped Mode Summary"),
                        bar_chart(
                            grouped_list,
                            x_col="mode_group",
                            y_col="freq_all",
                            title="Tour Mode (Grouped)",
                            xaxis_title="Mode Group",
                            as_percent=self.as_percent,
                        ),
                    ]
                )
            else:
                body.append(
                    self.unavailable_visualization(
                        grouped_result,
                        detail="Grouped tour mode summaries are unavailable while mode groups are enabled.",
                    )
                )
        return body


PAGE = DashboardPageDefinition(
    page_id="tr_mode",
    title="Old Tour Mode",
    group_id="tours",
    child_order=30,
    page_cls=TourModePage,
    required_summary_ids=("tour_mode_by_tour_purpose_and_auto_sufficiency",),
)

TourModePage.definition = PAGE
