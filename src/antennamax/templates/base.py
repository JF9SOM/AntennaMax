"""Template base: pydantic parameters -> Geometry.

Fields are stored in SI units. For convenience, inputs may also be given with a unit
suffix: a key ending in `_mm` is converted from mm to a field ending in `_m`, and a key ending
in `_mhz` from MHz to a field ending in `_hz` (e.g. `length_mm=1000` -> `length_m=1.0`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from antennamax.core.geometry import Geometry
from antennamax.core.units import mhz_to_hz, mm_to_m


def _number(key: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")
    return float(value)


class SIModel(BaseModel):
    """Pydantic model that accepts `*_mm` / `*_mhz` inputs and stores SI values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="before")
    @classmethod
    def _convert_units(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(key, str) and key.endswith("_mm"):
                new_key, value = key[: -len("_mm")] + "_m", mm_to_m(_number(key, value))
            elif isinstance(key, str) and key.endswith("_mhz"):
                new_key, value = key[: -len("_mhz")] + "_hz", mhz_to_hz(_number(key, value))
            else:
                new_key = key
            if new_key in out:
                raise ValueError(f"{new_key} given more than once (different units?)")
            out[new_key] = value
        return out


class Template(SIModel, ABC):
    """Parametric antenna design."""

    @abstractmethod
    def to_geometry(self) -> Geometry:
        """Build the electrical model."""
