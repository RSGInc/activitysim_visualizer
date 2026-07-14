from __future__ import annotations

from pathlib import Path
import re
from uuid import uuid4

import pytest


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return slug or "test"


@pytest.fixture
def tmp_path(request: pytest.FixtureRequest) -> Path:
    """Provide a workspace-local temp directory.

    The default pytest temp root is not reliably accessible in this Windows
    environment, so tests use a repo-local directory instead.
    """

    path = (
        Path("tmp_export_test_artifacts")
        / f"{_slugify(request.node.name)}_{uuid4().hex}"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="session")
def representative_full_export_html() -> str:
    """Build the immutable all-page export once for cross-cutting assertions."""
    from dashboard.export.html import build_export_html_document
    from test_export_html import _full_summary_run, _write_config

    path = Path("tmp_export_test_artifacts") / f"full_export_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    config = _write_config(
        path,
        export_html_lines=[
            "dashboard:",
            "  weighting: all",
            "  values: all",
        ],
    )
    return build_export_html_document(
        [],
        config,
        summary_runs=[_full_summary_run()],
    )
