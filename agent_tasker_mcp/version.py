"""Package version helpers."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

PACKAGE_NAME = "agent-tasker-pi-omp"


def package_version() -> str:
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:  # pragma: no cover - source checkout
        return "dev"
