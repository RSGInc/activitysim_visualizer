"""Shared logging configuration for ActivitySim Visualizer runtime workflows."""

from __future__ import annotations

import logging
from pathlib import Path
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.config import Config

LOGGER_NAMESPACE = "activitysim_viz"
DEFAULT_LOG_FILENAME = "activitysim_visualizer.log"


def get_logger(name: str) -> logging.Logger:
    """Return an application logger under the shared namespace."""
    if not name:
        return logging.getLogger(LOGGER_NAMESPACE)
    if name.startswith(f"{LOGGER_NAMESPACE}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAMESPACE}.{name}")


def default_log_path(config: "Config") -> Path:
    """Return the default runtime log file path for a config."""
    summary_root = Path(config.summary_root)
    return summary_root.parent / "logs" / DEFAULT_LOG_FILENAME


def configure_logging(
    config: "Config",
    *,
    level: int = logging.INFO,
    log_path: str | Path | None = None,
) -> Path:
    """Configure console and file logging for the application namespace."""
    resolved_log_path = (
        Path(log_path) if log_path is not None else default_log_path(config)
    )
    resolved_log_path.parent.mkdir(parents=True, exist_ok=True)

    app_logger = logging.getLogger(LOGGER_NAMESPACE)
    app_logger.setLevel(level)
    app_logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    for handler in list(app_logger.handlers):
        app_logger.removeHandler(handler)
        if isinstance(handler, logging.FileHandler):
            handler.close()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(
        resolved_log_path,
        mode="w",
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    app_logger.addHandler(console_handler)
    app_logger.addHandler(file_handler)
    return resolved_log_path


def shutdown_logging() -> None:
    """Detach and close application logging handlers."""
    app_logger = logging.getLogger(LOGGER_NAMESPACE)
    for handler in list(app_logger.handlers):
        app_logger.removeHandler(handler)
        if isinstance(handler, logging.FileHandler):
            handler.close()
