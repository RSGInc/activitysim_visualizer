from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import panel as pn
import plotly.graph_objects as go

from dashboard.export.serializer import serialize_viewable


def test_serialize_viewable_supports_container_and_card_nodes() -> None:
    view = pn.Column(
        pn.Card("Alpha", title="Card Title"),
        pn.Row("Left", "Right"),
    )

    payload = serialize_viewable(view, disable_widgets=True)

    assert payload["kind"] == "container"
    assert payload["layout"] == "column"
    assert payload["children"][0]["kind"] == "card"
    assert payload["children"][0]["title"] == "Card Title"
    assert payload["children"][1]["kind"] == "container"
    assert payload["children"][1]["layout"] == "row"


def test_serialize_viewable_supports_tabs_nodes() -> None:
    view = pn.Tabs(("One", pn.pane.HTML("First")), ("Two", pn.pane.HTML("<b>Second</b>")))

    payload = serialize_viewable(view, disable_widgets=True)

    assert payload == {
        "kind": "tabs",
        "tabs": [
            {"title": "One", "content": {"kind": "html", "html": "First"}},
            {"title": "Two", "content": {"kind": "html", "html": "<b>Second</b>"}},
        ],
    }


def test_serialize_viewable_supports_plotly_and_table_nodes() -> None:
    plot_payload = serialize_viewable(
        pn.pane.Plotly(go.Figure(data=[go.Bar(x=["a"], y=[1])])),
        disable_widgets=True,
    )
    table_payload = serialize_viewable(
        pn.widgets.Tabulator(pd.DataFrame({"alpha": [1], "beta": ["x"]})),
        disable_widgets=True,
    )

    assert plot_payload["kind"] == "plotly"
    assert plot_payload["figure"]["data"][0]["type"] == "bar"
    assert table_payload == {
        "kind": "table",
        "columns": ["alpha", "beta"],
        "rows": [{"alpha": 1, "beta": "x"}],
    }


def test_serialize_viewable_supports_widget_nodes_with_export_metadata() -> None:
    radio = pn.widgets.RadioButtonGroup(
        name="Mode",
        options=["All", "Drive", "Walk"],
        value="All",
    )
    select = pn.widgets.Select(
        name="Purpose",
        options=["Total", "eatout", "social"],
        value="Total",
        disabled=True,
    )
    widget_metadata = {
        id(radio): (
            "mode",
            {
                "export_enabled": False,
                "resolved_values": ["All", "Drive", "Walk"],
            },
        ),
        id(select): (
            "purpose",
            {
                "export_enabled": True,
                "resolved_values": ["Total", "social"],
            },
        ),
    }

    radio_payload = serialize_viewable(
        radio,
        disable_widgets=False,
        widget_metadata=widget_metadata,
    )
    select_payload = serialize_viewable(
        select,
        disable_widgets=False,
        widget_metadata=widget_metadata,
    )

    assert radio_payload == {
        "kind": "widget",
        "widget_type": "radio_button_group",
        "name": "Mode",
        "value": "All",
        "options": ["All", "Drive", "Walk"],
        "disabled": True,
        "selector_id": "mode",
        "export_enabled": False,
    }
    assert select_payload == {
        "kind": "widget",
        "widget_type": "select",
        "name": "Purpose",
        "value": "Total",
        "options": ["Total", "social"],
        "disabled": False,
        "selector_id": "purpose",
        "export_enabled": True,
    }


def test_serialize_viewable_supports_html_and_spacer_nodes() -> None:
    markdown_payload = serialize_viewable(
        pn.pane.Markdown("**Hello**"),
        disable_widgets=True,
    )
    html_payload = serialize_viewable(
        pn.pane.HTML("<i>World</i>"),
        disable_widgets=True,
    )
    string_payload = serialize_viewable("Plain text", disable_widgets=True)
    spacer_payload = serialize_viewable(pn.Spacer(), disable_widgets=True)

    assert markdown_payload["kind"] == "html"
    assert "<strong>Hello</strong>" in markdown_payload["html"]
    assert html_payload == {"kind": "html", "html": "<i>World</i>"}
    assert string_payload == {"kind": "html", "html": "Plain text"}
    assert spacer_payload["kind"] == "spacer"


def test_serialize_viewable_uses_fallback_for_unsupported_objects() -> None:
    payload = serialize_viewable(object(), disable_widgets=True)

    assert payload["kind"] == "html"
    assert "Unsupported export item: object" in payload["html"]
