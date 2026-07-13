"""Public orchestration entrypoint for prepare enrichment."""

from __future__ import annotations

from runtime.logging import get_logger

from processor.models import RunData
from processor.prepare.enrichment.domains import (
    enrich_mobility_domain,
    enrich_people_and_places_domain,
    finalize_output_domain,
    normalize_source_domain,
)
from processor.prepare.enrichment.types import _PrepareState
from runtime.config import Config

LOGGER = get_logger("processor.prepare")


def prepare_data(rd: RunData, config: Config) -> RunData:
    """Enrich ``RunData`` with derived columns needed by summaries and dashboard pages."""
    LOGGER.info("[prepare_data] Starting: %s", rd.label)

    state = _PrepareState.from_run(rd)
    state = normalize_source_domain(state, config)
    state = enrich_people_and_places_domain(state, config)
    state = enrich_mobility_domain(state, config)
    state = finalize_output_domain(state)

    LOGGER.info("[prepare_data] Complete: %s", state.label)
    return state.to_run()


__all__ = ["prepare_data"]
