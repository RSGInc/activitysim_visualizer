#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd -W)"
VENV_PYTHON="${ROOT_DIR}/.venv/Scripts/python.exe"

if [[ ! -f "${VENV_PYTHON}" ]]; then
  echo "Expected virtual environment Python at ${VENV_PYTHON}" >&2
  echo "Run 'uv sync --locked' from the project root first." >&2
  exit 1
fi

export QUARTO_PYTHON="${QUARTO_PYTHON:-${VENV_PYTHON}}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${ROOT_DIR}/.uv_cache}"

cd "${ROOT_DIR}"
exec uv run quarto "$@"
