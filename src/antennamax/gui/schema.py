"""Describe the parameters of a template for a form (no GUI toolkit needed).

The fields come from the template's pydantic model, so the form follows the model: a new field or
a changed default shows up without touching the GUI. Values are shown in mm / MHz (the
`*_mm` / `*_mhz` input spelling the models accept) and kept in SI inside the models.
"""

from __future__ import annotations

import types
import typing
from dataclasses import dataclass
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from antennamax.io.design import TEMPLATES

Kind = Literal["float", "int", "choice", "table"]

# (SI suffix, display unit, key suffix, display = SI * scale)
_SUFFIXES = (
    ("_m_s", "m/s", "_m_s", 1.0),  # speed of light: shown as is
    ("_m", "mm", "_mm", 1000.0),
    ("_hz", "MHz", "_mhz", 1e-6),
    ("_deg", "deg", "_deg", 1.0),
)


@dataclass(frozen=True)
class FieldSpec:
    name: str  # pydantic field name (SI), e.g. "diameter_m"
    label: str  # "diameter"
    unit: str  # "mm", "MHz", "" ...
    key: str  # key of the design mapping in display units, e.g. "diameter_mm"
    kind: Kind
    scale: float  # display value = SI value * scale
    optional: bool  # may be left empty (a default or an automatic value is used)
    default: Any  # SI default (None if there is none or it is automatic)
    required: bool
    choices: tuple[str, ...] = ()
    columns: tuple[FieldSpec, ...] = ()  # for tables: the columns (fields of one row)
    description: str = ""

    def to_display(self, si_value: Any) -> str:
        """Text for the editor from an SI value (None -> empty)."""
        if si_value is None:
            return ""
        if self.kind in ("float",):
            return f"{float(si_value) * self.scale:.10g}"
        return str(si_value)

    def to_si(self, text: str) -> float | int | str:
        """Value of the editor text in the field's display unit (a number or a choice)."""
        text = text.strip()
        if self.kind == "int":
            return int(text)
        if self.kind == "float":
            return float(text)
        return text


def _split_optional(annotation: Any) -> tuple[Any, bool]:
    origin = get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        optional = len(args) != len(get_args(annotation))
        if len(args) == 1:
            return args[0], optional
    return annotation, False


def _unit(name: str) -> tuple[str, str, float]:
    for suffix, unit, key_suffix, scale in _SUFFIXES:
        if name.endswith(suffix):
            return unit, name[: -len(suffix)] + key_suffix, scale
    return "", name, 1.0


def _label(name: str) -> str:
    for suffix, *_ in _SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.replace("_", " ")


def _spec(name: str, info: Any) -> FieldSpec:
    base, optional_type = _split_optional(info.annotation)
    unit, key, scale = _unit(name)
    has_default = (
        info.default is not PydanticUndefinedType and info.default is not PydanticUndefined
    )
    default = info.default if has_default else None
    required = info.is_required()
    description = info.description or ""
    origin = get_origin(base)
    if origin is Literal:
        return FieldSpec(
            name, _label(name), "", name, "choice", 1.0, False, default, required,
            choices=tuple(str(c) for c in get_args(base)), description=description,
        )  # fmt: skip
    if origin is list:
        (item,) = get_args(base)
        columns = tuple(_spec(n, i) for n, i in item.model_fields.items())
        return FieldSpec(
            name, _label(name), "", name, "table", 1.0, False, None, required,
            columns=columns, description=description,
        )  # fmt: skip
    kind: Kind = "int" if base is int else "float"
    return FieldSpec(
        name, _label(name), unit, key, kind, scale, optional_type or not required, default,
        required, description=description,
    )  # fmt: skip


PydanticUndefinedType = type(PydanticUndefined)


def model_fields(model: type[BaseModel]) -> list[FieldSpec]:
    return [_spec(name, info) for name, info in model.model_fields.items()]


def template_fields(template_name: str) -> list[FieldSpec]:
    """The parameters of a template (dipole, yagi, qfh) for a form, in model order."""
    return model_fields(TEMPLATES[template_name])
