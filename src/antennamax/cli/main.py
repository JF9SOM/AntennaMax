"""Command line interface: `antennamax run design.yaml [--json]`."""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from antennamax import __version__
from antennamax.core.optional import MissingExtraError
from antennamax.core.segmentation import SegmentationError
from antennamax.core.units import hz_to_mhz
from antennamax.io.design import DesignError, load_design
from antennamax.results.result import Result
from antennamax.solvers.nec2 import Nec2Solver
from antennamax.solvers.thin_wire import ThinWireWarning


@contextmanager
def _thin_wire_warnings() -> Iterator[None]:
    """Print thin-wire warnings as `antennamax: warning: ...` on stderr (once each)."""
    with warnings.catch_warnings():
        warnings.simplefilter("always", ThinWireWarning)
        original = warnings.showwarning
        seen: set[str] = set()

        def show(message, category, filename, lineno, file=None, line=None):
            if issubclass(category, ThinWireWarning):
                if str(message) not in seen:  # the viewers run the solver more than once
                    seen.add(str(message))
                    print(f"antennamax: warning: {message}", file=sys.stderr)
            else:
                original(message, category, filename, lineno, file, line)

        warnings.showwarning = show
        yield


def _kernel_line(result: Result) -> str:
    kernel = "on" if result.meta.get("extended_kernel") else "off"
    ratio = result.meta.get("min_segment_to_radius")
    suffix = f"; min segment/radius = {ratio:.2f}" if ratio is not None else ""
    return f"Solver: NEC2, extended thin-wire kernel: {kernel}{suffix}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="antennamax", description="Antenna simulator")
    parser.add_argument("--version", action="version", version=f"antennamax {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="simulate a design.yaml")
    run.add_argument("design", type=Path, help="path to design.yaml")
    run.add_argument("--json", action="store_true", help="print the Result as JSON")

    view = sub.add_parser("view", help="3D view of the wires and radiation pattern (pyvista)")
    view.add_argument("design", type=Path, help="path to design.yaml")
    view.add_argument(
        "--screenshot", type=Path, help="render off-screen to this PNG instead of opening a window"
    )

    plot = sub.add_parser("plot", help="SWR, R/X and pattern cuts in one figure (matplotlib)")
    plot.add_argument("design", type=Path, help="path to design.yaml")
    plot.add_argument("--save", type=Path, help="write a PNG instead of opening a window")

    parts = sub.add_parser("parts", help="3D-printable parts (STL and STEP) for a design")
    parts.add_argument("design", type=Path, help="path to design.yaml")
    parts.add_argument("--out", type=Path, required=True, help="output directory")
    parts.add_argument(
        "--clearance-mm", type=float, default=0.2, help="hole/fit clearance in mm (default 0.2)"
    )
    parts.add_argument(
        "--mast-diameter-mm", type=float, help="mast outer diameter in mm (default: VP20, 26 mm)"
    )
    parts.add_argument(
        "--support",
        choices=("auto", "integrated", "hub-rod"),
        default="auto",
        help="support style: one-piece spreaders, hubs with rods, or choose by build volume",
    )
    parts.add_argument(
        "--rod-diameter-mm", type=float, help="rod diameter for hub-rod supports (default 8)"
    )
    parts.add_argument("--rod-insert-depth-mm", type=float, help="rod insertion depth (default 20)")
    parts.add_argument(
        "--build-volume-mm",
        type=float,
        nargs=3,
        metavar=("X", "Y", "Z"),
        help="printer build volume in mm (default 220 220 250)",
    )
    return parser


def _format_table(result: Result) -> str:
    has_pattern = result.gain_dbi is not None
    header = f"{'f[MHz]':>10} {'R[ohm]':>10} {'X[ohm]':>10} {'SWR':>8}"
    if has_pattern:
        header += (
            f" {'Gmax[dBi]':>10} {'F/B[dB]':>9} {'AR(z)[dB]':>10} {'RHCP(z)[dBic]':>14}"
            f" {'LHCP(z)[dBic]':>14}"
        )
    lines = [header]
    for i, f in enumerate(result.frequencies_hz):
        z = result.impedance[i]
        line = f"{hz_to_mhz(f):>10.3f} {z.real:>10.2f} {z.imag:>10.2f} {result.swr[i]:>8.2f}"
        if has_pattern:
            line += f" {result.max_gain_dbi[i]:>10.2f} {result.front_to_back_db[i]:>9.2f}"
            line += (
                f" {result.zenith_axial_ratio_db[i]:>10.2f}"
                f" {result.zenith_rhcp_gain_dbic[i]:>14.2f}"
                f" {result.zenith_lhcp_gain_dbic[i]:>14.2f}"
            )
        lines.append(line)
    return "\n".join(lines)


def _run(design_path: Path, as_json: bool) -> int:
    try:
        design = load_design(design_path)
    except DesignError as exc:
        print(f"antennamax: error: {exc}", file=sys.stderr)
        return 2
    geometry = design.template.to_geometry()
    solver = Nec2Solver(pattern_resolution_deg=design.pattern_resolution_deg)
    with _thin_wire_warnings():
        result = solver.run(geometry, design.sweep)

    if as_json:
        payload = {"template": design.template_name, "result": result.to_dict()}
        print(json.dumps(payload))
    else:
        print(f"Design: {design_path} (template: {design.template_name})")
        print(f"Reference impedance Z0 = {result.z0:g} ohm")
        print(_kernel_line(result))
        n_feeds = result.feed_impedances.shape[1]
        if n_feeds > 1:
            print(
                f"Note: {n_feeds} sources; Z and SWR are those of the first source "
                "(all of them: --json feed_impedances_*)"
            )
        print()
        print(_format_table(result))
    return 0


def _simulate_for_viewer(design_path: Path):
    """Load the design and run the calculations the viewers need."""
    from antennamax.viz.data import simulate

    with _thin_wire_warnings():
        return simulate(load_design(design_path))


def _view(design_path: Path, screenshot: Path | None) -> int:
    from antennamax.viz import view3d

    view3d.require("pyvista", "open the 3D view", extra="gui")  # fail fast, before the simulation
    view3d.show(_simulate_for_viewer(design_path), screenshot)
    return 0


def _plot(design_path: Path, save: Path | None) -> int:
    from antennamax.viz import plot2d

    plot2d.require("matplotlib", "draw the summary plot", extra="plot")
    run = _simulate_for_viewer(design_path)
    if save is not None:
        plot2d.save(run, save)
        print(f"saved {save}")
    else:
        plot2d.show(run)
    return 0


def _eprint(message: str) -> None:
    """Print to stderr; never fail on a console that cannot encode the message."""
    try:
        print(message, file=sys.stderr)
    except UnicodeEncodeError:
        print(message.encode("ascii", "replace").decode("ascii"), file=sys.stderr)


def _distance_mm(distance_m: float) -> float:
    """Distance for display, in mm to one decimal: a tiny or zero value shows as 0.0, never -0.0
    (round() keeps the sign of a negative zero; adding 0.0 clears it). Negative distances, for
    parts above the top, stay negative."""
    return round(distance_m * 1000.0, 1) + 0.0


def _parts(args: argparse.Namespace) -> int:
    from pydantic import ValidationError

    from antennamax.mech.base import require_cad, to_mm
    from antennamax.mech.qfh_parts import part_rows
    from antennamax.mech.qfh_support import plan_supports

    design = load_design(args.design)
    if design.template_name != "qfh":
        _eprint(
            f"antennamax: error: 部品未対応 (no printable parts for template "
            f"{design.template_name!r}; supported: qfh)"
        )
        return 2
    require_cad()  # fail early with the install hint
    settings: dict = {"clearance_mm": args.clearance_mm}
    if args.build_volume_mm is not None:
        settings["build_volume_m"] = tuple(v / 1000.0 for v in args.build_volume_mm)

    def metres(value_mm: float | None) -> float | None:
        return None if value_mm is None else value_mm / 1000.0

    try:
        plan = plan_supports(
            design.template,
            args.support,
            print_settings=settings,
            mast_outer_diameter_m=metres(args.mast_diameter_mm),
            rod_diameter_m=metres(args.rod_diameter_mm),
            rod_insert_depth_m=metres(args.rod_insert_depth_mm),
        )
    except ValidationError as exc:
        _eprint(
            f"antennamax: error: cannot build the {args.support} supports: {exc.errors()[0]['msg']}"
        )
        return 2
    part_set = plan.part_set

    rows = []
    for instance in part_set.instances():
        instance.part.export(args.out)
        rows.append((instance, instance.part.size_mm()))
    for problem in part_set.fit_problems():
        _eprint(f"antennamax: warning: {problem.message()}")

    print(f"Support: {plan.mode} ({plan.reason})")
    print(
        "From top = distance below the top conductor plane "
        "(the groove plane of the upper spreader / hub)"
    )
    print(f"{'Part':<26} {'Site':<12} {'Qty':>3} {'From top[mm]':>13}   Size x y z [mm]")
    pieces = 0
    for row in part_rows(part_set):
        x, y, z = row.size_mm
        top = _distance_mm(row.distance_from_top_m)
        print(
            f"{row.name:<26} {row.site:<12} {row.count:>3} {top:>13.1f}   "
            f"{x:.1f} x {y:.1f} x {z:.1f}"
        )
        pieces += row.count
    print(f"Printed parts: {pieces} pieces")
    guides = part_set.drill_guides()
    if guides:
        hole = to_mm(guides[0].hole_diameter_m)
        print(f"Drill guides (collars on the mast; drill through both {hole:.1f} mm guide holes):")
        print("  (From top = below the top conductor plane, the same reference as in the table)")
        for g in guides:
            hole_top = _distance_mm(g.hole_from_top_m)
            collar_top = _distance_mm(g.collar_top_from_top_m)
            above = _distance_mm(g.top_face_to_hole_m)
            print(
                f"  {g.loop} loop: guide hole at {hole_top:.1f} mm From top; "
                f"collar top face at {collar_top:.1f} mm From top ({above:.1f} mm above the hole)"
            )
        print("  Turn the collars so that their top-face notch faces the upper spreader's +x arm.")
        print(
            "  The upper spreader / hubs carry a notch at +x in the bottom edge of the rim: "
            "the x axis is the large loop."
        )
    rods = part_set.rods()
    if rods:
        print(f"Rods (not printed, {to_mm(rods[0].diameter_m):g} mm diameter):")
        for rod in rods:
            print(
                f"  {rod.name:<24} {rod.count:>3} x {to_mm(rod.length_m):.1f} mm "
                f"= {to_mm(rod.total_length_m):.1f} mm"
            )
        total = sum(rod.total_length_m for rod in rods)
        print(f"  total rod length {to_mm(total):.1f} mm")
    name = part_set.fastener.name
    print("Fasteners:")
    for use in part_set.fasteners():
        print(
            f"  {use.purpose}: {use.screws} x {name} screws "
            f"(length >= {to_mm(use.min_length_m):.1f} mm, use {use.screw_length_mm} mm), "
            f"{use.nuts} x {name} hex nuts"
        )
    print(
        f"  total: {part_set.screw_count} x {name} screws, {part_set.nut_count} x {name} hex nuts"
    )
    for instance, _ in rows:
        for path in (args.out / f"{instance.name}.stl", args.out / f"{instance.name}.step"):
            print(f"wrote {path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "run":
            return _run(args.design, args.json)
        if args.command == "view":
            return _view(args.design, args.screenshot)
        if args.command == "plot":
            return _plot(args.design, args.save)
        if args.command == "parts":
            return _parts(args)
    except (DesignError, SegmentationError, MissingExtraError) as exc:
        print(f"antennamax: error: {exc}", file=sys.stderr)
        return 2
    return 2  # unreachable: subcommand is required


if __name__ == "__main__":
    sys.exit(main())
