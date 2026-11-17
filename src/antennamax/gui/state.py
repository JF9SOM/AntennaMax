"""The content of the GUI form and its conversion to and from a design mapping (no Qt here).

The form edits text; this module turns the text into a design mapping (what a design.yaml holds,
in mm / MHz), validates it with the same code the command line uses (`io.design.parse_design`),
and maps problems back to the field they belong to.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from antennamax.gui.schema import FieldSpec, template_fields
from antennamax.io.design import (
    DesignError,
    DesignFile,
    LoadedDesign,
    load_design,
    parse_design,
)

TEMPLATE_NAMES = ("dipole", "yagi", "qfh")
PATTERN_RESOLUTIONS = ("5", "10", "15", "30")  # degrees; all divide 180 and 360

# Starting designs for a template chosen in the GUI (the bundled examples).
DEFAULT_DESIGNS: dict[str, dict[str, Any]] = {
    "dipole": {
        "template": "dipole",
        "params": {"center_frequency_mhz": 145, "diameter_mm": 4},
        "sweep": {"start_mhz": 140, "stop_mhz": 150, "points": 11},
        "pattern": {"resolution_deg": 10},
    },
    "yagi": {
        "template": "yagi",
        "params": {
            "center_frequency_mhz": 144,
            "feed_index": 1,
            "elements": [
                {"position_mm": 0, "length_mm": 1030, "diameter_mm": 6},
                {"position_mm": 300, "length_mm": 980, "diameter_mm": 6},
                {"position_mm": 600, "length_mm": 920, "diameter_mm": 6},
            ],
        },
        "sweep": {"start_mhz": 142, "stop_mhz": 146, "points": 5},
        "pattern": {"resolution_deg": 10},
    },
    "qfh": {
        "template": "qfh",
        "params": {
            "center_frequency_mhz": 137.5,
            "diameter_mm": 3,
            "bend_radius_mm": 15,
            "handedness": "left",
        },
        "sweep": {"start_mhz": 135, "stop_mhz": 140, "points": 11},
        "pattern": {"resolution_deg": 10},
    },
}


@dataclass(frozen=True)
class FieldError:
    """A problem with one input. `target` says where it belongs:
    ("field", name), ("row", index, column_name), ("table",), ("sweep", name),
    ("pattern",) or ("general",)."""

    target: tuple
    message: str


@dataclass
class FormValues:
    template: str
    fields: dict[str, str] = field(default_factory=dict)  # field name -> text
    rows: list[dict[str, str]] = field(default_factory=list)  # table rows: column -> text
    sweep_start_mhz: str = ""
    sweep_stop_mhz: str = ""
    sweep_points: str = ""
    pattern_deg: str = "10"


def _parse(spec: FieldSpec, text: str) -> float | int | str:
    """Value of the editor text, in the display unit. Raises ValueError with a readable message."""
    text = text.strip()
    if spec.kind == "choice":
        if text not in spec.choices:
            raise ValueError(f"choose one of: {', '.join(spec.choices)}")
        return text
    try:
        value = int(text) if spec.kind == "int" else float(text)
    except ValueError:
        raise ValueError(
            "a whole number is expected" if spec.kind == "int" else "a number is expected"
        ) from None
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("a finite number is expected")
    return value


def build_mapping(values: FormValues) -> tuple[dict[str, Any] | None, list[FieldError]]:
    """The design mapping for the form, or the problems with the text typed in."""
    errors: list[FieldError] = []
    params: dict[str, Any] = {}
    for spec in template_fields(values.template):
        if spec.kind == "table":
            rows = []
            for i, row in enumerate(values.rows):
                out: dict[str, Any] = {}
                for col in spec.columns:
                    text = row.get(col.name, "").strip()
                    if not text:
                        errors.append(FieldError(("row", i, col.name), "required"))
                        continue
                    try:
                        out[col.key] = _parse(col, text)
                    except ValueError as exc:
                        errors.append(FieldError(("row", i, col.name), str(exc)))
                rows.append(out)
            params[spec.key] = rows
            continue
        text = values.fields.get(spec.name, "").strip()
        if not text:
            if spec.required:
                errors.append(FieldError(("field", spec.name), "required"))
            continue  # optional: the default or the automatic value is used
        try:
            value = _parse(spec, text)
        except ValueError as exc:
            errors.append(FieldError(("field", spec.name), str(exc)))
            continue
        default = spec.default
        if (
            spec.kind in ("float", "int")
            and default is not None
            and math.isclose(float(value), float(default) * spec.scale, rel_tol=1e-9)
        ):
            continue  # equal to the default: leave it out of the design
        params[spec.key] = value

    sweep: dict[str, Any] = {}
    for key, text, caster in (
        ("start_mhz", values.sweep_start_mhz, float),
        ("stop_mhz", values.sweep_stop_mhz, float),
        ("points", values.sweep_points, int),
    ):
        try:
            number = caster(text.strip())
            if isinstance(number, float) and not math.isfinite(number):
                raise ValueError
            sweep[key] = number
        except ValueError:
            what = "a whole number is expected" if caster is int else "a number is expected"
            errors.append(FieldError(("sweep", key.removesuffix("_mhz")), what))
    pattern: dict[str, Any] = {}
    try:
        pattern["resolution_deg"] = float(values.pattern_deg.strip())
    except ValueError:
        errors.append(FieldError(("pattern",), "a number is expected"))
    if errors:
        return None, errors
    return {"template": values.template, "params": params, "sweep": sweep, "pattern": pattern}, []


_SWEEP_TARGETS = {"start_hz": "start", "stop_hz": "stop", "points": "points"}


def _targets(error: DesignError, template: str) -> list[FieldError]:
    """Map the located problems of a DesignError to places in the form."""
    out: list[FieldError] = []
    specs = template_fields(template)
    for loc, message in error.errors:
        if loc[:1] == ("params",) and len(loc) >= 2 and loc[1] == "elements":
            if len(loc) >= 4:
                out.append(FieldError(("row", loc[2], loc[3]), message))
            elif len(loc) == 3:
                out.append(FieldError(("row", loc[2], "*"), message))  # the whole row
            else:
                out.append(FieldError(("table",), message))
        elif loc[:1] == ("params",) and len(loc) >= 2:
            out.append(FieldError(("field", loc[1]), message))
        elif loc == ("params",):
            # A problem of the template as a whole: attach it to the field the message names.
            named = next((s for s in specs if s.name in message or s.key in message), None)
            if named is not None and named.kind != "table":
                out.append(FieldError(("field", named.name), message))
            elif "element" in message:
                out.append(FieldError(("table",), message))
            else:
                out.append(FieldError(("general",), message))
        elif loc[:1] == ("sweep",):
            name = _SWEEP_TARGETS.get(loc[1]) if len(loc) > 1 else None
            out.append(FieldError(("sweep", name or "*"), message))
        elif loc[:1] == ("pattern",):
            out.append(FieldError(("pattern",), message))
        else:
            out.append(FieldError(("general",), message))
    return out or [FieldError(("general",), str(error))]


def validate(
    values: FormValues,
) -> tuple[LoadedDesign | None, dict[str, Any] | None, list[FieldError]]:
    """Check the form with the same code the command line uses.

    Returns (design, mapping, errors); on a problem the design is None and `errors` say where.
    Model-level problems that have no field of their own (for example a feed index outside the
    element list) are attached to the field the message is about where possible.
    """
    mapping, errors = build_mapping(values)
    if mapping is None:
        return None, None, errors
    try:
        return parse_design(mapping), mapping, []
    except DesignError as exc:
        return None, mapping, _targets(exc, values.template)


# --- reading designs ---------------------------------------------------------------------


def values_from_mapping(mapping: dict[str, Any]) -> FormValues:
    """Form content for a design mapping (validated: raises DesignError if it is not valid)."""
    loaded = parse_design(mapping)
    spec = DesignFile.model_validate(mapping)
    template = loaded.template
    raw_params = mapping.get("params", {})
    values = FormValues(template=loaded.template_name)
    for fspec in template_fields(loaded.template_name):
        if fspec.kind == "table":
            values.rows = [
                {col.name: col.to_display(getattr(item, col.name)) for col in fspec.columns}
                for item in getattr(template, fspec.name)
            ]
            continue
        value = getattr(template, fspec.name)
        if fspec.name == "max_frequency_hz" and not (
            {"max_frequency_hz", "max_frequency_mhz"} & raw_params.keys()
        ):
            value = None  # injected from the sweep by the loader, not set by the user
        values.fields[fspec.name] = (
            fspec.to_display(value) if fspec.kind != "choice" else str(value)
        )
    values.sweep_start_mhz = f"{spec.sweep.start_hz * 1e-6:.10g}"
    values.sweep_stop_mhz = f"{spec.sweep.stop_hz * 1e-6:.10g}"
    values.sweep_points = str(spec.sweep.points)
    if spec.pattern is not None:
        values.pattern_deg = f"{spec.pattern.resolution_deg:g}"
    return values


def default_values(template: str) -> FormValues:
    """The starting design for a template."""
    return values_from_mapping(DEFAULT_DESIGNS[template])


def values_from_file(path: str | Path) -> FormValues:
    """Form content for a design.yaml (raises DesignError with a readable message)."""
    path = Path(path)
    load_design(path)  # the same readable errors as the command line (file, YAML, content)
    mapping = yaml.safe_load(path.read_text(encoding="utf-8"))
    return values_from_mapping(mapping)


def mapping_to_yaml(mapping: dict[str, Any]) -> str:
    """design.yaml text for a design mapping."""
    body = yaml.safe_dump(mapping, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return "# Saved by the antennamax GUI. Format: docs/DESIGN_FORMAT.md\n" + body
