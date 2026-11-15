"""Command line interface: `antennamax run design.yaml [--json]`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from antennamax import __version__
from antennamax.core.units import hz_to_mhz
from antennamax.io.design import DesignError, load_design
from antennamax.results.result import Result
from antennamax.solvers.nec2 import Nec2Solver


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="antennamax", description="Antenna simulator")
    parser.add_argument("--version", action="version", version=f"antennamax {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="simulate a design.yaml")
    run.add_argument("design", type=Path, help="path to design.yaml")
    run.add_argument("--json", action="store_true", help="print the Result as JSON")
    return parser


def _format_table(result: Result) -> str:
    has_pattern = result.gain_dbi is not None
    header = f"{'f[MHz]':>10} {'R[ohm]':>10} {'X[ohm]':>10} {'SWR':>8}"
    if has_pattern:
        header += f" {'Gmax[dBi]':>10} {'F/B[dB]':>9}"
    lines = [header]
    for i, f in enumerate(result.frequencies_hz):
        z = result.impedance[i]
        line = f"{hz_to_mhz(f):>10.3f} {z.real:>10.2f} {z.imag:>10.2f} {result.swr[i]:>8.2f}"
        if has_pattern:
            line += f" {result.max_gain_dbi[i]:>10.2f} {result.front_to_back_db[i]:>9.2f}"
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
    result = solver.run(geometry, design.sweep)

    if as_json:
        payload = {"template": design.template_name, "result": result.to_dict()}
        print(json.dumps(payload))
    else:
        print(f"Design: {design_path} (template: {design.template_name})")
        print(f"Reference impedance Z0 = {result.z0:g} ohm")
        print()
        print(_format_table(result))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "run":
        return _run(args.design, args.json)
    return 2  # unreachable: subcommand is required


if __name__ == "__main__":
    sys.exit(main())
