from pathlib import Path
import sys

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.rendering import Plotter, RenderContext
from dashboard.rendering.labels import display_label_map


def test_display_run_labels_preserve_distinct_ends_and_deduplicate_collisions() -> None:
    labels = [
        "Regional Transportation Scenario Baseline 2050 North",
        "Regional Transportation Scenario Baseline 2050 South",
        f"{'A' * 20} first {'Z' * 12}",
        f"{'A' * 20} second {'Z' * 12}",
    ]

    display_labels = display_label_map(labels)

    assert display_labels[labels[0]] == "Regional Transportation…North"
    assert display_labels[labels[1]] == "Regional Transportation…South"
    assert len(set(display_labels.values())) == len(labels)
    assert all(len(label) <= 30 for label in display_labels.values())
    assert display_labels[labels[2]].endswith("[1]")
    assert display_labels[labels[3]].endswith("[2]")


def test_figure_first_bar_omits_undeclared_hover_columns() -> None:
    figure = Plotter(RenderContext()).figure.bar(
        [
            (
                "Base",
                pl.DataFrame(
                    {"mode": ["Walk"], "trip_count": [5.0], "pct": [100.0]}
                ),
            )
        ],
        x="mode",
        y="trip_count",
        category_order=["Walk", "Bike"],
    )

    hover = list(figure.data[0].customdata)
    assert "Pct:" not in hover[0]
    assert "Pct:" not in hover[1]
    assert hover[0] == "Base<br>mode: Walk<br>Count: 5.0"
    assert figure.layout.hovermode != "x unified"


def test_figure_builder_reports_run_and_missing_columns() -> None:
    with pytest.raises(
        ValueError,
        match="bar chart for run 'Base' is missing columns: trip_count",
    ):
        Plotter(RenderContext()).figure.bar(
            [("Base", pl.DataFrame({"mode": ["Walk"]}))],
            x="mode",
            y="trip_count",
        )


def test_bar_and_density_chart_hover_formatting_matches_units() -> None:
    bar = Plotter(RenderContext(value_mode="share")).bar(
        [("Base", pl.DataFrame({"mode": ["Walk", "Bike"], "trip_count": [25.0, 75.0]}))],
        x="mode",
        y="trip_count",
        x_title="Mode",
        y_title="Trips",
    )
    density_percent = Plotter(RenderContext(value_mode="share")).density(
        [("Base", pl.DataFrame({"clock_time": ["03:00", "03:30"], "trip_count": [25.0, 75.0]}))],
        x="clock_time",
        y="trip_count",
        x_title="Clock Time",
        y_title="Trips",
    )
    density_count = Plotter(RenderContext(value_mode="count")).density(
        [("Base", pl.DataFrame({"clock_time": ["03:00"], "trip_count": [1234.0]}))],
        x="clock_time",
        y="trip_count",
        x_title="Clock Time",
        y_title="Trips",
    )

    assert list(bar.object.data[0].customdata)[0] == (
        "Base<br>Mode: Walk<br>Percent of Trips (%): 25.00%"
    )
    assert list(density_percent.object.data[0].customdata)[0] == (
        "Base<br>Clock Time: 03:00<br>Percent of Trips (%): 25.00%"
    )
    assert list(density_count.object.data[0].customdata)[0] == (
        "Base<br>Clock Time: 03:00<br>Trips: 1,234"
    )


def test_long_run_names_are_short_in_legends_and_full_in_hovers() -> None:
    label = "Regional Transportation Scenario Baseline 2050 North"
    data = [(label, pl.DataFrame({"period": [1, 2], "value": [10.0, 20.0]}))]
    context = RenderContext(run_labels=(label,))

    bar = Plotter(context).figure.bar(data, x="period", y="value")
    line = Plotter(context).figure.line(data, x="period", y="value")
    density = Plotter(context).figure.density(data, x="period", y="value")
    scatter = Plotter(context).figure.scatter(data, x="period", y="value")

    for figure in (bar, line, density, scatter):
        trace = figure.data[0]
        assert trace.name == "Regional Transportation…North"
        assert trace.meta == {"run_name": label}
        hover = trace.hovertemplate + "".join(map(str, trace.customdata or []))
        assert "Regional Transportation Scenario<br>Baseline 2050 North" in hover
    assert scatter.data[0].legendgroup == label


def test_bar_chart_uses_configured_all_series_hover_mode() -> None:
    data = [
        ("Base", pl.DataFrame({"mode": ["Walk", "Bike"], "trip_count": [5.0, 1.0]})),
        ("Build", pl.DataFrame({"mode": ["Walk", "Bike"], "trip_count": [7.0, 0.5]})),
    ]

    chart = Plotter(RenderContext(bar_hover_mode="all")).bar(
        data, x="mode", y="trip_count"
    )
    assert chart.object.layout.hovermode == "x unified"


def test_density_chart_uses_configured_all_series_hover_mode() -> None:
    data = [
        ("Base", pl.DataFrame({"bin": [1, 2], "count": [10.0, 12.0]})),
        ("Build", pl.DataFrame({"bin": [1, 2], "count": [8.0, 15.0]})),
    ]

    default_chart = Plotter(RenderContext()).density(data, x="bin", y="count")
    all_hover_chart = Plotter(RenderContext(density_hover_mode="all")).density(
        data, x="bin", y="count"
    )

    assert default_chart.object.layout.hovermode != "x unified"
    assert all_hover_chart.object.layout.hovermode == "x unified"


def test_scatter_chart_can_add_one_to_one_reference_line() -> None:
    chart = Plotter(RenderContext()).scatter(
        [("Base", pl.DataFrame({"observed": [10.0, 20.0], "modeled": [12.0, 25.0]}))],
        x="observed",
        y="modeled",
        fit_overlays=[
            (
                "Base",
                pl.DataFrame(
                    {
                        "observed": [0.0, 100.0],
                        "modeled": [-100.0, 200.0],
                        "annotation": [
                            "Base<br>y = 3.00x - 100.00<br>R² = 0.90<br>n = 2"
                        ]
                        * 2,
                    }
                ),
            )
        ],
        x_title="Observed Count (vehicles)",
        y_title="Modeled Volume (vehicles)",
        one_to_one=True,
    )

    point_trace = chart.object.data[0]
    reference_line = chart.object.data[-1]
    fit_line = chart.object.data[-2]
    assert point_trace.hovertemplate == (
        "Base<br>Observed Count (vehicles): %{x}<br>"
        "Modeled Volume (vehicles): %{y}<extra></extra>"
    )
    assert fit_line.name == "Base fit"
    assert "y = 3.00x - 100.00" in fit_line.hovertemplate
    assert not chart.object.layout.annotations
    assert chart.object.layout.height == 400
    assert chart.object.layout.margin.t == 90
    assert reference_line.name == "1:1 line"
    assert list(reference_line.x) == [10.0, 25.0]
    assert list(reference_line.y) == [10.0, 25.0]
    assert reference_line.line.color == "#BDBDBD"
    assert reference_line.line.dash == "dash"
    assert reference_line.showlegend is True
    assert list(chart.object.layout.xaxis.range) == [10.0, 25.0]
    assert list(chart.object.layout.yaxis.range) == [10.0, 25.0]
    assert chart.object.layout.xaxis.constrain == "domain"
    assert chart.object.layout.yaxis.constrain == "domain"
    assert chart.object.layout.yaxis.scaleanchor == "x"
    assert chart.object.layout.yaxis.scaleratio == 1.0


def test_scatter_fit_details_are_hover_only_for_multiple_runs() -> None:
    labels = [f"Run {index}" for index in range(4)]
    scatter_data = [
        (
            label,
            pl.DataFrame({"observed": [10.0, 20.0], "modeled": [12.0, 25.0]}),
        )
        for label in labels
    ]
    fit_data = [
        (
            label,
            pl.DataFrame(
                {
                    "observed": [0.0, 100.0],
                    "modeled": [-100.0, 200.0],
                    "annotation": [
                        f"{label}<br>y = 3.00x - 100.00<br>R² = 0.90<br>n = 2"
                    ]
                    * 2,
                }
            ),
        )
        for label in labels
    ]

    chart = Plotter(RenderContext()).scatter(
        scatter_data,
        x="observed",
        y="modeled",
        x_title="Observed Count (vehicles)",
        y_title="Modeled Volume (vehicles)",
        fit_overlays=fit_data,
        one_to_one=True,
        panel_aspect_ratio=1.0,
    )

    assert not chart.object.layout.annotations
    assert chart.object.layout.height == 400
    assert chart.object.layout.margin.t == 90
    assert all("R² = 0.90" in trace.hovertemplate for trace in chart.object.data[4:8])
    assert list(chart.object.layout.xaxis.range) == [10.0, 25.0]
    assert list(chart.object.layout.yaxis.range) == [10.0, 25.0]
    assert chart.aspect_ratio == 1.0
