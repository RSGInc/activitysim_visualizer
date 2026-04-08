"""Destination page: NM tour distance distributions."""

from __future__ import annotations

import panel as pn
import polars as pl

from dashboard.components import _to_pandas, density_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition, PageSelectorDefinition
from summarize import destination as destination_sums
from summarize.reader import Config, RunData


def _nm_dist_by_purpose(
    rd: RunData, purpose: str | None, col_name: str | None
) -> pl.DataFrame:
    """Return (distbin 0-40, freq) for NM tours filtered by purpose."""
    tours = rd.tours
    if "tour_category" not in tours.columns:
        return pl.DataFrame({"distbin": list(range(41)), "freq": [0.0] * 41})

    indiv = tours.filter(pl.col("tour_category").is_in(["non-mandatory", "atwork"]))
    joint = tours.filter(pl.col("tour_category") == "joint").with_columns(
        (pl.col("finalweight") * pl.col("NUMBER_HH")).alias("wgt")
    )
    joint = (
        joint.rename({"wgt": "finalweight"})
        if "finalweight" not in joint.columns
        else joint.with_columns(pl.col("wgt").alias("finalweight"))
    )

    if purpose is None or purpose == "All NM":
        combined = pl.concat(
            [
                (
                    indiv.select(["SKIMDIST", "finalweight"])
                    if "SKIMDIST" in indiv.columns
                    else pl.DataFrame()
                ),
                (
                    joint.select(["SKIMDIST", "finalweight"])
                    if "SKIMDIST" in joint.columns
                    else pl.DataFrame()
                ),
            ]
        )
    else:
        if col_name is None or col_name not in tours.columns:
            return pl.DataFrame({"distbin": list(range(41)), "freq": [0.0] * 41})
        combined = pl.concat(
            [
                (
                    indiv.filter(pl.col(col_name) == purpose).select(
                        ["SKIMDIST", "finalweight"]
                    )
                    if "SKIMDIST" in indiv.columns
                    else pl.DataFrame()
                ),
                (
                    joint.filter(pl.col(col_name) == purpose).select(
                        ["SKIMDIST", "finalweight"]
                    )
                    if "SKIMDIST" in joint.columns
                    else pl.DataFrame()
                ),
            ]
        )

    if len(combined) == 0 or "SKIMDIST" not in combined.columns:
        return pl.DataFrame({"distbin": list(range(41)), "freq": [0.0] * 41})

    combined = combined.with_columns(
        pl.col("SKIMDIST").cast(pl.Int32).clip(0, 40).alias("distbin")
    )
    return (
        combined.group_by("distbin")
        .agg(pl.col("finalweight").sum().alias("freq"))
        .join(pl.DataFrame({"distbin": list(range(41))}), on="distbin", how="right")
        .fill_null(0)
        .sort("distbin")
    )


def discover_purpose_columns(
    runs: list[tuple[str, RunData]],
) -> tuple[list[str], dict[str, str | None]]:
    """Collect destination purpose options and per-run source columns."""
    purposes_set = set()
    run_to_purpose_col: dict[str, str | None] = {}
    for run_label, rd in runs:
        if "tour_category" not in rd.tours.columns:
            run_to_purpose_col[run_label] = None
            continue
        for cand in ("primary_purpose", "tour_type", "purpose"):
            if cand in rd.tours.columns and not rd.tours[cand].dtype.is_numeric():
                run_to_purpose_col[run_label] = cand
                break
        else:
            run_to_purpose_col[run_label] = None
        purpose_col = run_to_purpose_col[run_label]
        if purpose_col:
            nm_tours = rd.tours.filter(
                pl.col("tour_category").is_in(["non-mandatory", "atwork", "joint"])
            )
            purposes_set.update(nm_tours[purpose_col].drop_nulls().unique().to_list())

    purposes = sorted(purposes_set) if purposes_set else []
    return ["All NM"] + purposes, run_to_purpose_col


def distance_chart_data(
    runs: list[tuple[str, RunData]],
    purpose: str,
    run_to_purpose_col: dict[str, str | None],
) -> list[tuple[str, pl.DataFrame]]:
    """Build destination distance chart data for each run."""
    return [
        (run_label, _nm_dist_by_purpose(rd, purpose, run_to_purpose_col.get(run_label)))
        for run_label, rd in runs
    ]


def average_distance_table(
    runs: list[tuple[str, RunData]],
    purposes: list[str],
    run_to_purpose_col: dict[str, str | None],
) -> pl.DataFrame:
    """Build the average destination distance comparison table."""
    rows = []
    for purp in purposes:
        row = {"Purpose": purp}
        for run_label, rd in runs:
            purpose_col = run_to_purpose_col.get(run_label)
            if purpose_col is None:
                row[run_label] = None
                continue
            if "SKIMDIST" in rd.tours.columns and purpose_col in rd.tours.columns:
                sub = rd.tours.filter(pl.col(purpose_col) == purp)
                if len(sub) > 0:
                    wgt = sub["finalweight"].to_numpy()
                    dist = sub["SKIMDIST"].to_numpy()
                    mask = dist == dist
                    if mask.sum() > 0 and wgt[mask].sum() > 0:
                        row[run_label] = round(
                            float((dist[mask] * wgt[mask]).sum() / wgt[mask].sum()),
                            2,
                        )
                        continue
            row[run_label] = None
        rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None) if rows else pl.DataFrame()


class DestinationPage(DashboardPage):
    def __init__(self, state, config: Config) -> None:
        super().__init__("Destination", state, config)
        purp_opts = self._purpose_options(state.weighted_runs)
        self.purp_sel = pn.widgets.Select(
            name="Purpose", options=purp_opts, value=purp_opts[0]
        )
        self._watch_widget(self.purp_sel)
        self._body = pn.Column(sizing_mode="stretch_width")
        self.view = pn.Column(
            pn.pane.Markdown("## Destination Choice (NM Tour Distances)"),
            pn.Row(pn.pane.Markdown("**Purpose:**"), self.purp_sel),
            self._body,
            sizing_mode="stretch_width",
        )

    def _purpose_options(self, runs: list[tuple[str, RunData]]) -> list[str]:
        if runs:
            purp_opts, _ = discover_purpose_columns(runs)
            return purp_opts
        dist_list = self.state.get_precomputed_summary(
            "destination_distance", "weighted"
        )
        if dist_list is not None:
            first_df = next((df for _, df in dist_list if len(df) > 0), pl.DataFrame())
            purposes = (
                sorted(
                    [
                        purpose
                        for purpose in first_df["purpose"]
                        .drop_nulls()
                        .unique()
                        .to_list()
                        if purpose != "All NM"
                    ]
                )
                if len(first_df) > 0 and "purpose" in first_df.columns
                else []
            )
            return ["All NM"] + purposes
        return ["All NM"]

    def _refresh(self) -> None:
        runs = self.state.get_runs()
        if not self.state.run_labels:
            self._body.objects = [pn.pane.Markdown("No runs loaded.")]
            return

        purp_opts = self._purpose_options(runs)
        self.purp_sel.options = purp_opts
        if self.purp_sel.value not in purp_opts:
            self.purp_sel.value = purp_opts[0]
        purpose = self.purp_sel.value
        if runs:
            _, run_to_purpose_col = discover_purpose_columns(runs)
            data = self.get_filtered_view(
                "destination_dist",
                purpose,
                factory=lambda: distance_chart_data(runs, purpose, run_to_purpose_col),
            )
            avg_df = self.get_filtered_view(
                "destination_avg",
                tuple(self.purp_sel.options[1:]),
                factory=lambda: average_distance_table(
                    runs, list(self.purp_sel.options[1:]), run_to_purpose_col
                ),
            )
        else:
            dist_list = self.get_summary(
                "destination_distance",
                lambda: [
                    (label, destination_sums.distance_distribution(rd))
                    for label, rd in runs
                ],
            )
            data = self.get_filtered_view(
                "destination_dist",
                purpose,
                factory=lambda: [
                    (
                        label,
                        df.with_columns(pl.col("purpose").cast(pl.Utf8))
                        .filter(pl.col("purpose") == purpose)
                        .select(["distbin", "freq"]),
                    )
                    for label, df in dist_list
                ],
            )
            avg_list = self.get_summary(
                "destination_average_distance",
                lambda: [
                    (label, destination_sums.average_distance(rd)) for label, rd in runs
                ],
            )
            rows = []
            for purp in self.purp_sel.options[1:]:
                row = {"Purpose": purp}
                for run_label, df in avg_list:
                    value = None
                    if len(df) > 0 and {"purpose", "avg_distance"}.issubset(df.columns):
                        match = df.with_columns(pl.col("purpose").cast(pl.Utf8)).filter(
                            pl.col("purpose") == purp
                        )
                        if len(match) > 0:
                            value = match["avg_distance"][0]
                    row[run_label] = (
                        round(float(value), 2) if value is not None else None
                    )
                rows.append(row)
            avg_df = pl.DataFrame(rows) if rows else pl.DataFrame()

        self._body.objects = [
            density_chart(
                data,
                "distbin",
                "freq",
                f"NM Tour Distance Distribution - {purpose}",
                "Distance (miles)",
                normalize=False,
                as_percent=self.as_percent,
            ),
            pn.pane.Markdown("### Average Tour Distances (miles)"),
            (
                pn.widgets.Tabulator(_to_pandas(avg_df), sizing_mode="stretch_width")
                if len(avg_df) > 0
                else pn.pane.Markdown("*(No distance data available)*")
            ),
        ]


PAGE = DashboardPageDefinition(
    page_id="destination",
    title="Destination",
    order=50,
    controller_cls=DestinationPage,
    selectors=(
        PageSelectorDefinition(
            selector_id="purpose",
            widget_attr="purp_sel",
            label="Purpose",
        ),
    ),
)
