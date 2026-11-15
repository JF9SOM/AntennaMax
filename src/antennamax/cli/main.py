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


def _parts(design_path: Path, out_dir: Path, clearance_mm: float, mast_mm: float | None) -> int:
    from antennamax.mech.base import require_cad
    from antennamax.mech.qfh_spreader import QfhSpreader

    design = load_design(design_path)
    if design.template_name != "qfh":
        _eprint(
            f"antennamax: error: 部品未対応 (no printable parts for template "
            f"{design.template_name!r}; supported: qfh)"
        )
        return 2
    require_cad()  # fail early with the install hint
    params: dict = {"qfh": design.template, "print_settings": {"clearance_mm": clearance_mm}}
    if mast_mm is not None:
        params["mast_outer_diameter_mm"] = mast_mm
    spreader = QfhSpreader.model_validate(params)
    for path in spreader.export(out_dir, "qfh_spreader"):
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
            return _parts(args.design, args.out, args.clearance_mm, args.mast_diameter_mm)
    except (DesignError, SegmentationError, MissingExtraError) as exc:
        print(f"antennamax: error: {exc}", file=sys.stderr)
        return 2
    return 2  # unreachable: subcommand is required


if __name__ == "__main__":
    sys.exit(main())
