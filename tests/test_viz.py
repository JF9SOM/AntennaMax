"""Tests for `view` / `plot`: drawing data, PNG output, CLI, and the optional-dependency error.

Windowing is never opened. Rendering tests need the `gui` extra and are skipped when matplotlib
or pyvista is missing (as in CI, which installs only dev + rf) and, for pyvista, on Linux
without a display.
"""

import os
import sys
from pathlib import Path

import numpy as np
import pytest

from antennamax.cli.main import main
from antennamax.io.design import load_design
from antennamax.results.result import Result
from antennamax.templates import Dipole
from antennamax.viz import MissingExtraError, plot2d, require, view3d
from antennamax.viz.data import (
    feed_point,
    geometry_center,
    geometry_size,
    horizontal_cut,
    pattern_surface,
    simulate,
    vertical_cut,
    wire_draws,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
YAGI = EXAMPLES / "yagi3_144mhz.yaml"
DIPOLE = EXAMPLES / "dipole_145mhz.yaml"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(scope="module")
def yagi_run():
    return simulate(load_design(YAGI))


# --- Drawing data (NumPy only) -----------------------------------------------------------


def test_wire_draws_keep_proportions_and_flag_the_feed(yagi_run):
    draws, magnification = wire_draws(yagi_run.geometry)
    assert magnification > 1.0  # 3 mm radius on a ~1 m structure is magnified for display
    assert [d.is_fed for d in draws] == [False, True, False]
    assert all(d.display_radius == pytest.approx(d.radius * magnification) for d in draws)
    thickest = max(d.display_radius for d in draws)
    assert thickest == pytest.approx(0.012 * geometry_size(yagi_run.geometry))


def test_feed_point_is_the_centre_of_the_fed_wire(yagi_run):
    p = feed_point(yagi_run.geometry)
    assert p == pytest.approx([0.3, 0.0, 0.0], abs=1e-9)  # driven element at x = 300 mm, centred
    np.testing.assert_allclose(geometry_center(yagi_run.geometry), [0.3, 0.0, 0.0], atol=1e-9)


def test_pattern_surface_geometry():
    theta = np.radians(np.arange(0, 181, 30.0))
    phi = np.radians(np.arange(0, 360, 30.0))
    gain = np.full((len(theta), len(phi)), -10.0)
    gain[3, 0] = 8.0  # peak at theta = 90 deg, phi = 0
    gain[0, :] = -np.inf  # an exact null
    x, y, z, g = pattern_surface(theta, phi, gain, max_radius=2.0, center=np.array([1.0, 0, 0]))
    assert x.shape == (len(theta), len(phi) + 1)  # seam closed
    np.testing.assert_allclose(x[:, 0], x[:, -1], atol=1e-12)
    np.testing.assert_allclose(z[:, 0], z[:, -1], atol=1e-12)
    # Peak: radius 2 towards +x from the centre (1, 0, 0).
    assert (x[3, 0], y[3, 0], z[3, 0]) == pytest.approx((3.0, 0.0, 0.0), abs=1e-9)
    # Null and everything 30 dB below the peak collapse to the centre; colours stay finite.
    assert np.isfinite(g).all()
    np.testing.assert_allclose(x[0], 1.0, atol=1e-9)
    np.testing.assert_allclose(y[0], 0.0, atol=1e-9)
    np.testing.assert_allclose(z[0], 0.0, atol=1e-9)
    assert g.max() == pytest.approx(8.0)
    assert g.min() == pytest.approx(8.0 - 30.0)


def test_pattern_cuts_for_the_yagi(yagi_run):
    pattern = yagi_run.pattern_result
    assert pattern.gain_dbi.shape[0] == 1  # one frequency: the centre
    h = horizontal_cut(pattern)
    v = vertical_cut(pattern)
    n_theta, n_phi = pattern.gain_dbi.shape[1:]
    assert len(h.angle_rad) == len(h.gain_dbi) == n_phi + 1  # closed ring
    assert len(v.angle_rad) == len(v.gain_dbi) == 2 * n_theta - 1
    assert np.isfinite(h.gain_dbi).all() and np.isfinite(v.gain_dbi).all()
    # The beam points to +x: azimuth 0 in the horizontal cut, and in the vertical cut
    # (plane phi = 0 / 180) at alpha = 90 deg (the horizon on the phi = 0 side).
    assert h.angle_rad[np.argmax(h.gain_dbi)] in (0.0, 2 * np.pi)
    assert np.degrees(v.angle_rad[np.argmax(v.gain_dbi)]) == pytest.approx(90.0)
    # Front is stronger than back: horizon at alpha = 90 vs alpha = 270 degrees.
    assert (
        v.gain_dbi[np.argmin(np.abs(v.angle_rad - np.pi / 2))]
        > v.gain_dbi[np.argmin(np.abs(v.angle_rad - 3 * np.pi / 2))] + 3.0
    )


def test_simulate_uses_the_template_centre_frequency(yagi_run):
    assert yagi_run.center_frequency_hz == pytest.approx(144e6)
    assert yagi_run.sweep_result.gain_dbi is None
    assert len(yagi_run.sweep_result.frequencies_hz) == 5
    assert yagi_run.pattern_result.frequencies_hz.tolist() == [144e6]


def test_cuts_need_a_pattern():
    r = Result(np.array([1e8]), np.array([50 + 0j]))
    with pytest.raises(TypeError):
        horizontal_cut(r)  # gain_dbi is None


def test_dipole_without_pattern_block_still_gets_a_default_resolution(tmp_path):
    text = DIPOLE.read_text(encoding="utf-8").split("pattern:")[0]
    path = tmp_path / "d.yaml"
    path.write_text(text, encoding="utf-8")
    run = simulate(load_design(path))
    assert run.pattern_result.gain_dbi is not None
    assert isinstance(load_design(path).template, Dipole)


# --- Optional dependency errors ----------------------------------------------------------


@pytest.mark.parametrize("extra", ["plot", "gui"])
def test_require_names_the_extra(extra):
    with pytest.raises(MissingExtraError, match=rf"uv sync --extra {extra}\b"):
        require("antennamax_no_such_module", "do something", extra=extra)


@pytest.mark.parametrize(
    ("command", "module", "extra"), [("view", view3d, "gui"), ("plot", plot2d, "plot")]
)
def test_cli_reports_missing_extra(monkeypatch, capsys, command, module, extra):
    monkeypatch.setattr(
        module,
        "require",
        lambda name, purpose, extra="gui": require("no_such_module", purpose, extra),
    )
    code = main([command, str(YAGI)])
    captured = capsys.readouterr()
    assert code == 2
    assert f"uv sync --extra {extra}" in captured.err
    assert captured.out == ""


# --- matplotlib --------------------------------------------------------------------------


def test_plot_saves_a_png(tmp_path, capsys):
    pytest.importorskip("matplotlib")
    out = tmp_path / "summary.png"
    assert main(["plot", str(YAGI), "--save", str(out)]) == 0
    data = out.read_bytes()
    assert data.startswith(PNG_SIGNATURE)
    assert len(data) > 20_000  # a real figure, not an empty canvas
    assert "saved" in capsys.readouterr().out


def test_plot_figure_has_four_panels(yagi_run):
    pytest.importorskip("matplotlib")
    from matplotlib.figure import Figure

    fig = Figure(figsize=(10, 8))
    plot2d.draw(yagi_run, fig)
    axes = fig.get_axes()
    assert len(axes) == 4
    assert [a.name for a in axes] == ["rectilinear", "rectilinear", "polar", "polar"]
    swr_line = axes[0].lines[0]
    assert len(swr_line.get_xdata()) == 5
    assert min(swr_line.get_ydata()) >= 1.0


# --- pyvista (off-screen) ----------------------------------------------------------------

needs_display = pytest.mark.skipif(
    sys.platform == "linux" and not os.environ.get("DISPLAY"),
    reason="off-screen rendering needs a display (or xvfb) on Linux",
)


@needs_display
def test_view_screenshot_off_screen(tmp_path):
    pytest.importorskip("pyvista")
    out = tmp_path / "view.png"
    assert main(["view", str(YAGI), "--screenshot", str(out)]) == 0
    assert out.read_bytes().startswith(PNG_SIGNATURE)
    assert out.stat().st_size > 20_000
