"""Run calculations away from the GUI thread, in a separate process.

PyNEC does not give the GIL back while it works, so a thread would make the window stutter or
freeze on a big design; a separate (spawned) process keeps the window alive. The functions here
are top-level so that they can be pickled; they only call the existing code
(`io.design.parse_design`, `viz.data.simulate`, the `parts` command) and report what happened.
"""

from __future__ import annotations

import contextlib
import io
import multiprocessing
import os
import tempfile
import warnings
from concurrent.futures import Executor, Future, ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from antennamax.io.design import DesignError, parse_design
from antennamax.viz.data import DesignRun, simulate


@dataclass
class ComputeOutcome:
    """What a calculation produced: a run, or an error message; plus the warnings it raised."""

    run: DesignRun | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class PartsOutcome:
    code: int
    stdout: str
    stderr: str


def compute_design(mapping: dict[str, Any]) -> ComputeOutcome:
    """Validate a design mapping and simulate it. Never raises: problems come back as text."""
    outcome = ComputeOutcome()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            outcome.run = simulate(parse_design(mapping))
        except DesignError as exc:
            outcome.error = str(exc)
        except (ValueError, RuntimeError) as exc:  # SegmentationError is a ValueError
            outcome.error = f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001 - the window must survive anything
            outcome.error = f"unexpected error ({type(exc).__name__}): {exc}"
    # The same warning can be raised by more than one solver run: show it once.
    outcome.warnings = list(dict.fromkeys(f"{w.category.__name__}: {w.message}" for w in caught))
    return outcome


def export_parts(yaml_text: str, out_dir: str, support: str = "auto") -> PartsOutcome:
    """Run `antennamax parts` for a design given as YAML text; capture what it prints."""
    from antennamax.cli.main import main

    out, err = io.StringIO(), io.StringIO()
    with tempfile.TemporaryDirectory() as tmp:
        design = Path(tmp) / "design.yaml"
        design.write_text(yaml_text, encoding="utf-8")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main(["parts", str(design), "--out", out_dir, "--support", support])
            except Exception as exc:  # noqa: BLE001
                print(f"unexpected error ({type(exc).__name__}): {exc}", file=err)
                code = 1
    return PartsOutcome(code, out.getvalue(), err.getvalue())


def _warm_up() -> bool:
    """Import everything a calculation needs, so that the first real one starts quickly."""
    import antennamax.solvers.nec2  # noqa: F401
    import antennamax.viz.data  # noqa: F401

    return True


class Calculator:
    """Runs functions in a worker (a spawned process by default) and gives back futures."""

    def __init__(self, backend: str | None = None) -> None:
        backend = backend or os.environ.get("ANTENNAMAX_GUI_BACKEND", "process")
        if backend not in ("process", "thread"):
            raise ValueError("backend must be 'process' or 'thread'")
        self.backend = backend
        self._executor: Executor | None = None

    def _get(self) -> Executor:
        if self._executor is None:
            if self.backend == "process":
                self._executor = ProcessPoolExecutor(
                    max_workers=1, mp_context=multiprocessing.get_context("spawn")
                )
            else:
                self._executor = ThreadPoolExecutor(max_workers=1)
        return self._executor

    def warm_up(self) -> Future:
        return self._get().submit(_warm_up)

    def submit(self, fn: Any, *args: Any) -> Future:
        return self._get().submit(fn, *args)

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
