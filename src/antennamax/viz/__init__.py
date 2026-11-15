"""Visualisation helpers (optional dependencies: install with `uv sync --extra gui` / `plot`)."""

from __future__ import annotations

from antennamax.core.optional import MissingExtraError, require

__all__ = ["MissingExtraError", "require"]
