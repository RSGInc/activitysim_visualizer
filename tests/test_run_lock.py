from __future__ import annotations

from pathlib import Path

import pytest

from runtime.run_lock import RunLockError, acquire_run_lock, release_run_lock


def test_run_lock_blocks_same_output_root_until_released(tmp_path: Path) -> None:
    first = acquire_run_lock(tmp_path)
    try:
        with pytest.raises(RunLockError, match="already using output root"):
            acquire_run_lock(tmp_path)
    finally:
        release_run_lock(first)

    second = acquire_run_lock(tmp_path)
    release_run_lock(second)
