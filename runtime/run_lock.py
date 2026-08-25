"""Cross-process lock for one visualizer output root."""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


class RunLockError(RuntimeError):
    """Raised when another process owns a visualizer output-root lock."""


def acquire_run_lock(output_root: str | Path) -> tuple[Path, BinaryIO]:
    lock_path = Path(output_root) / ".activitysim_visualizer.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    stream = lock_path.open("a+b")
    if lock_path.stat().st_size == 0:
        stream.write(b"\0")
        stream.flush()
    stream.seek(0)

    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        stream.close()
        raise RunLockError(
            f"another visualizer process is already using output root "
            f"{lock_path.parent}. Lock file: {lock_path}"
        ) from exc

    return lock_path, stream


def release_run_lock(lock: tuple[Path, BinaryIO] | None) -> None:
    if lock is None:
        return
    _, stream = lock
    try:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        stream.close()


__all__ = ["RunLockError", "acquire_run_lock", "release_run_lock"]
