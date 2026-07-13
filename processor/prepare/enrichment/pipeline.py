"""Public orchestration entrypoint for prepare enrichment."""

from __future__ import annotations

from runtime.logging import get_logger

from processor.models import RunData
from processor.prepare.enrichment.bootstrap import _init_prepare_state
from processor.prepare.enrichment.finalize import _finalize_prepared_run
from processor.prepare.enrichment.stages import (
    _run_prepare_core_stages,
    _run_prepare_output_stages,
    _run_prepare_person_and_tour_stages,
)
from runtime.config import Config

LOGGER = get_logger("processor.prepare")


def prepare_data(rd: RunData, config: Config) -> RunData:
    """Enrich ``RunData`` with derived columns needed by summaries and dashboard pages."""
    LOGGER.info("[prepare_data] Starting: %s", rd.label)

    state = _init_prepare_state(rd)
    state = _run_prepare_core_stages(state, config)
    state = _run_prepare_person_and_tour_stages(state, config)
    state = _run_prepare_output_stages(state, config)

    LOGGER.info("[prepare_data] Complete: %s", state.label)
    return _finalize_prepared_run(state)


__all__ = ["prepare_data"]
