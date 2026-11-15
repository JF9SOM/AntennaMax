"""Helpers for optional dependencies (installed through extras: plot, gui, cad)."""

from __future__ import annotations

import importlib
from types import ModuleType


class MissingExtraError(RuntimeError):
    """An optional dependency is not installed."""


def require(module: str, purpose: str, extra: str = "gui") -> ModuleType:
    """Import an optional module or raise an error that says which extra to install."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise MissingExtraError(
            f"{module} is required to {purpose} but is not installed: run `uv sync --extra {extra}`"
        ) from exc
