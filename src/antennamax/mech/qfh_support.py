"""Choice between the integrated spreaders and the hub-and-rod supports for a QFH."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from antennamax.mech.base import to_mm
from antennamax.mech.qfh_hubrod import QfhHubRodPartSet
from antennamax.mech.qfh_parts import QfhPartSet
from antennamax.templates.qfh import Qfh

SupportMode = Literal["integrated", "hub-rod", "auto"]


@dataclass(frozen=True)
class SupportPlan:
    mode: Literal["integrated", "hub-rod"]  # what was chosen
    part_set: QfhPartSet | QfhHubRodPartSet
    reason: str


def _first_line(exc: ValidationError) -> str:
    return exc.errors()[0]["msg"].removeprefix("Value error, ")


def plan_supports(
    qfh: Qfh,
    support: SupportMode = "auto",
    print_settings: dict[str, Any] | None = None,
    mast_outer_diameter_m: float | None = None,
    rod_diameter_m: float | None = None,
    rod_insert_depth_m: float | None = None,
) -> SupportPlan:
    """Build the part set for the requested support style.

    "auto" uses the integrated spreaders if every part fits the build volume, and the hub-and-rod
    supports otherwise (also when the integrated spreaders cannot be built at all).
    """
    common: dict[str, Any] = {"qfh": qfh}
    if print_settings is not None:
        common["print_settings"] = print_settings
    if mast_outer_diameter_m is not None:
        common["mast_outer_diameter_m"] = mast_outer_diameter_m
    rod: dict[str, Any] = {}
    if rod_diameter_m is not None:
        rod["rod_diameter_m"] = rod_diameter_m
    if rod_insert_depth_m is not None:
        rod["rod_insert_depth_m"] = rod_insert_depth_m

    if support == "integrated":
        return SupportPlan("integrated", QfhPartSet(**common), "requested")
    if support == "hub-rod":
        return SupportPlan("hub-rod", QfhHubRodPartSet(**common, **rod), "requested")

    try:
        integrated = QfhPartSet(**common)
    except ValidationError as exc:
        hub_rod = QfhHubRodPartSet(**common, **rod)
        return SupportPlan(
            "hub-rod", hub_rod, f"integrated spreaders not possible: {_first_line(exc)}"
        )
    problems = integrated.fit_problems()
    if not problems:
        return SupportPlan("integrated", integrated, "all integrated parts fit the build volume")
    names = ", ".join(p.name for p in problems)
    volume = " x ".join(f"{to_mm(v):g}" for v in integrated.print_settings.build_volume_m)
    reason = f"integrated parts exceed the build volume {volume} mm ({names})"
    try:
        return SupportPlan("hub-rod", QfhHubRodPartSet(**common, **rod), reason)
    except ValidationError as exc:
        return SupportPlan(
            "integrated", integrated, f"{reason}; hub-and-rod not possible: {_first_line(exc)}"
        )
