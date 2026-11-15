"""Load design.yaml into a Template, a Sweep and pattern settings. See docs/DESIGN_FORMAT.md."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from pydantic import (
    PositiveFloat,
    PositiveInt,
    ValidationError,
    field_validator,
    model_validator,
)

from antennamax.solvers.base import Sweep
from antennamax.solvers.nec2 import Nec2Solver
from antennamax.templates import Dipole, Qfh, Template, Yagi
from antennamax.templates.base import SIModel

TEMPLATES: dict[str, type[Template]] = {"dipole": Dipole, "yagi": Yagi, "qfh": Qfh}


class DesignError(ValueError):
    """The design file is unreadable or invalid; the message is meant for the user."""


class SweepSpec(SIModel):
    start_hz: PositiveFloat
    stop_hz: PositiveFloat
    points: PositiveInt

    @model_validator(mode="after")
    def _check(self) -> SweepSpec:
        if self.stop_hz < self.start_hz:
            raise ValueError("stop must not be smaller than start")
        if self.points > 1 and self.stop_hz == self.start_hz:
            raise ValueError("start and stop must differ when points > 1")
        return self


class PatternSpec(SIModel):
    resolution_deg: PositiveFloat

    @field_validator("resolution_deg")
    @classmethod
    def _valid_resolution(cls, v: float) -> float:
        Nec2Solver(pattern_resolution_deg=v)  # raises ValueError for unusable steps
        return v


class DesignFile(SIModel):
    template: str
    params: dict[str, Any]
    sweep: SweepSpec
    pattern: PatternSpec | None = None

    @field_validator("template")
    @classmethod
    def _known_template(cls, v: str) -> str:
        if v not in TEMPLATES:
            raise ValueError(f"unknown template {v!r}; available: {', '.join(sorted(TEMPLATES))}")
        return v


@dataclass(frozen=True)
class LoadedDesign:
    template_name: str
    template: Template
    sweep: Sweep
    pattern_resolution_deg: float | None


def _format_errors(exc: ValidationError, prefix: str = "") -> str:
    lines = []
    for err in exc.errors():
        loc = (
            ".".join(str(p) for p in (*([prefix] if prefix else []), *err["loc"])) or "(top level)"
        )
        lines.append(f"  {loc}: {err['msg']}")
    return "\n".join(lines)


def load_design(path: str | Path) -> LoadedDesign:
    """Read a design.yaml. Raises DesignError with a readable message on any problem."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DesignError(f"cannot read {path}: {exc.strerror or exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise DesignError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise DesignError(f"{path}: the top level must be a mapping (template, params, sweep)")

    try:
        spec = DesignFile.model_validate(data)
    except ValidationError as exc:
        raise DesignError(f"{path}: invalid design:\n{_format_errors(exc)}") from exc

    template_cls = TEMPLATES[spec.template]
    params = dict(spec.params)
    given = {"max_frequency_hz", "max_frequency_mhz"} & params.keys()
    if "max_frequency_hz" in template_cls.model_fields and not given:
        # Segmentation is judged at the top of the sweep (never below the centre frequency).
        centre = params.get("center_frequency_hz")
        if centre is None and isinstance(params.get("center_frequency_mhz"), int | float):
            centre = params["center_frequency_mhz"] * 1e6
        top = spec.sweep.stop_hz
        params["max_frequency_hz"] = max(top, centre) if isinstance(centre, int | float) else top
    try:
        template = template_cls.model_validate(params)
    except ValidationError as exc:
        raise DesignError(
            f"{path}: invalid params for template {spec.template!r}:\n"
            f"{_format_errors(exc, 'params')}"
        ) from exc

    freqs = np.linspace(spec.sweep.start_hz, spec.sweep.stop_hz, spec.sweep.points)
    return LoadedDesign(
        template_name=spec.template,
        template=template,
        sweep=Sweep(tuple(float(f) for f in freqs)),
        pattern_resolution_deg=spec.pattern.resolution_deg if spec.pattern else None,
    )
