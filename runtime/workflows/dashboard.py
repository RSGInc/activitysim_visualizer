"""Dashboard and export workflow orchestration."""

from __future__ import annotations

from typing import Any

from runtime.logging import get_logger
from dashboard.page_registry import export_data_requirements, live_data_requirements
from processor.models import RunData, prune_prepared_runs
from runtime.config import Config
from runtime.workflows.common import prune_summary_runs

LOGGER = get_logger("main")


def run_dashboard_workflow(
    *,
    summary_runs: list[Any],
    prepared_runs: list[tuple[str, RunData]] | None = None,
    config: Config,
    export_html_path: str | None = None,
    port: int = 5006,
    show: bool = True,
) -> None:
    """Render the live dashboard or a standalone HTML export."""
    if prepared_runs is None:
        prepared_runs = []
    if not summary_runs:
        raise ValueError(
            "dashboard workflow requires precomputed summary runs and will not build them."
        )
    requirements = (
        export_data_requirements(config)
        if export_html_path
        else live_data_requirements(config)
    )
    summary_runs = prune_summary_runs(
        summary_runs,
        requirements.summary_ids_for_pruning,
    )
    prepared_runs = (
        prune_prepared_runs(prepared_runs, requirements.required_prepared_tables)
        if requirements.prepared_data_mode != "none"
        else []
    )

    if export_html_path:
        from dashboard.export.html import ExportBuildError, write_export_html_document

        LOGGER.info("Building dashboard")
        LOGGER.info("Exporting dashboard to %s ...", export_html_path)
        try:
            write_export_html_document(
                export_html_path,
                prepared_runs,
                config,
                summary_runs=summary_runs,
            )
        except ExportBuildError as exc:
            LOGGER.error("Dashboard export failed during %s.", exc.phase)
            if exc.output_path:
                LOGGER.error("Export target: %s", exc.output_path)
            if exc.hint:
                LOGGER.error("Next step: %s", exc.hint)
            raise
        LOGGER.info("Done.")
        return

    from dashboard.app import build_dashboard
    import panel as pn

    LOGGER.info("Building dashboard")
    dashboard = build_dashboard(
        prepared_runs,
        config,
        summary_runs=summary_runs,
    )
    pn.serve(
        dashboard,
        port=port,
        show=show,
        title=config.dashboard_title,
    )
