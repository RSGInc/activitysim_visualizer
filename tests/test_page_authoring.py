from __future__ import annotations

from pathlib import Path

import panel as pn
import pytest

from dashboard import DashboardPage, DashboardState
from test_export_html import _write_config


def test_provider_selector_repairs_stale_value_before_feature_render(
    tmp_path: Path,
) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(summary_runs=[], weighting_modes=config.weighting_modes)

    class DeclarativePage(DashboardPage):
        def __init__(self) -> None:
            self.available = ["A", "B"]
            self.rendered_values: list[str] = []
            super().__init__(state, config)

        def build_page(self):
            chart = self.feature("chart")
            self.choice = chart.select(
                "choice",
                "Choice",
                options=lambda: self.available,
                default="last",
            )
            body = chart.section(
                "body",
                selectors=("choice",),
                render=self.render_chart,
            )
            return pn.Column(self.choice, body)

        def render_chart(self):
            value = str(self.choice.value)
            self.rendered_values.append(value)
            return pn.pane.Markdown(value)

    page = DeclarativePage()
    page.refresh(force=True)
    assert page.choice.value == "B"

    page.available = ["C", "D"]
    page.refresh(force=True)

    assert page.choice.value == "D"
    assert page.rendered_values[-1] == "D"
    assert [feature.feature_id for feature in page.features] == ["chart"]
    assert page.registered_sections[0].section_id == "chart.body"
    assert page.registered_sections[0].selector_ids == ("chart.choice",)


def test_query_identity_uses_declared_selector_state(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(summary_runs=[], weighting_modes=config.weighting_modes)
    calls: list[str] = []

    class QueryPage(DashboardPage):
        def build_page(self):
            self.choice = self.select("choice", "Choice", options=["A", "B"])
            body = self.section(
                "body",
                selectors=("choice",),
                render=self.render_chart,
            )
            return pn.Column(self.choice, body)

        def render_chart(self):
            value = str(self.choice.value)

            def build(value=value):
                calls.append(value)
                return value

            return pn.pane.Markdown(self.query(build))

    page = QueryPage(state, config)
    page.refresh(force=True)
    page.refresh(force=True)
    page.choice.value = "B"
    page.refresh(force=True)

    assert calls == ["A", "B"]
    assert state.cache_stats["page_query"] == {"hits": 2, "misses": 2}


def test_feature_ids_must_be_unique(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    state = DashboardState(summary_runs=[], weighting_modes=config.weighting_modes)

    class DuplicateFeaturePage(DashboardPage):
        def build_page(self):
            self.feature("duplicate")
            with pytest.raises(ValueError, match="duplicate feature id"):
                self.feature("duplicate")
            return pn.Column()

    DuplicateFeaturePage(state, config)
