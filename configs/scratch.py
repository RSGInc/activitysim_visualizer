import panel as pn
from dashboard.components import bar_chart
from dashboard.page_base import DashboardPage
from dashboard.page_definitions import DashboardPageDefinition


class ExamplePage(DashboardPage):
    def build_page(self) -> pn.viewable.Viewable:
        # Register one stable page section whose content is produced by render_body().
        self._body = self.section("example_body", render=self.render_body)

        # Return the visible page layout.
        return self.new_section(
            pn.pane.Markdown("## Example Page"),
            self._body,
            sizing_mode="stretch_width",
        )

    def render_body(self):
        # Read the page's required summary table.
        summary = self.state.get_summary_table_set(
            "example_summary", self.weighting_key
        )

        # Show a standard fallback if the summary is unavailable.
        if summary is None:
            return [self.summary_only_unavailable_card()]

        # Return the list of viewables that make up the page content.
        return [
            bar_chart(
                summary,
                x_col="category",
                y_col="value",
                title="Example Figure",
                xaxis_title="Category",
                yaxis_title="Value",
            )
        ]


PAGE = DashboardPageDefinition(
    page_id="example_page",
    title="Example Page",
    group_id="custom",
    order=99,
    page_cls=ExamplePage,
    required_summary_ids=("example_summary",),
)

ExamplePage.definition = PAGE
