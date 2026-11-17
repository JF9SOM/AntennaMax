"""GUI tests (offscreen Qt): the window, validation display, calculation, files, exports."""

import json
import time

import pytest

pytest.importorskip("pytestqt")
pytest.importorskip("PySide6")
pytest.importorskip("matplotlib")

from PySide6 import QtCore  # noqa: E402

from antennamax.gui.window import MainWindow  # noqa: E402

TIMEOUT = 60_000


@pytest.fixture
def window(qtbot):
    w = MainWindow(use_3d=False, backend="thread")
    qtbot.addWidget(w)
    yield w
    w.calculator.close()


def calc(qtbot, window) -> bool:
    with qtbot.waitSignal(window.calculation_finished, timeout=TIMEOUT) as blocker:
        assert window.calculate()
    return blocker.args[0]


def test_opens_example_and_calculates(qtbot):
    w = MainWindow("examples/qfh_137mhz.yaml", use_3d=False, backend="thread")
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.calculation_finished, timeout=TIMEOUT) as blocker:
        pass
    assert blocker.args == [True]
    assert w.template_box.currentText() == "qfh"
    rows = w.summary.center_values()
    assert any("SWR" in k for k in rows) and any("RHCP" in k for k in rows)
    assert w.impedance_view.figure.axes and w.pattern_view.figure.axes
    w.calculator.close()


def test_yagi_table_is_editable_and_recalculates(qtbot, window):
    window.open_file("examples/yagi3_144mhz.yaml")
    table = window.form.table
    assert len(table.rows()) == 3
    assert calc(qtbot, window)
    before = window.summary.center_values()
    rows = table.rows()
    rows[1]["length_m"] = "950"
    table.set_rows(rows)
    window.form.table.add_row({"position_m": "900", "length_m": "880", "diameter_m": "6"})
    assert len(window.form.table.rows()) == 4
    assert calc(qtbot, window)
    assert window.summary.center_values() != before


def test_invalid_input_is_shown_at_the_field(qtbot, window):
    window.form.editor("center_frequency_hz").setText("abc")
    assert window.calculate() is False
    assert window.form.error_text("center_frequency_hz")
    window.form.editor("center_frequency_hz").setText("145")
    assert calc(qtbot, window)
    assert window.form.error_text("center_frequency_hz") == ""


def test_invalid_sweep_is_shown_at_the_sweep(qtbot, window):
    window.sweep.points.setText("x")
    assert window.calculate() is False
    assert window.sweep.error_text("points")


def test_save_and_open_round_trip(qtbot, window, tmp_path):
    window.open_file("examples/yagi3_144mhz.yaml")
    out = tmp_path / "saved.yaml"
    assert window.save_file(out)
    other = MainWindow(use_3d=False, backend="thread")
    qtbot.addWidget(other)
    assert other.open_file(out)
    assert other.values() == window.values()
    other.calculator.close()


def test_broken_file_does_not_crash(qtbot, window, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("template: dipole\nparams: [", encoding="utf-8")
    assert window.open_file(bad) is False
    assert "Warnings" in window.tabs.tabText(window._warnings_tab)
    assert window.open_file(tmp_path / "missing.yaml") is False


def test_json_export(qtbot, window, tmp_path):
    out = tmp_path / "result.json"
    assert window.export_json(out) is False  # nothing calculated yet
    assert calc(qtbot, window)
    assert window.export_json(out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["template"] == "dipole" and "sweep" in data


def test_parts_only_for_qfh(qtbot, window, tmp_path):
    assert window.export_parts(tmp_path) is False


def test_qfh_parts_export(qtbot, tmp_path):
    pytest.importorskip("build123d")
    w = MainWindow("examples/qfh_137mhz.yaml", use_3d=False, backend="thread", auto_calculate=False)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.parts_finished, timeout=600_000) as blocker:
        assert w.export_parts(tmp_path)
    assert blocker.args == [True]
    assert any(tmp_path.rglob("*.stl"))
    for d in w._dialogs:
        d.close()
    w.calculator.close()


def test_window_stays_responsive_with_the_process_worker(qtbot):
    w = MainWindow("examples/yagi3_144mhz.yaml", use_3d=False, backend="process")
    qtbot.addWidget(w)
    ticks = []
    timer = QtCore.QTimer()
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start(20)
    with qtbot.waitSignal(w.calculation_finished, timeout=TIMEOUT) as blocker:
        pass
    timer.stop()
    assert blocker.args == [True]
    assert len(ticks) >= 3  # the event loop kept running while the worker calculated
    w.calculator.close()


@pytest.mark.skipif(
    __import__("os").environ.get("ANTENNAMAX_TEST_3D") != "1",
    reason="interactive 3D view needs OpenGL: set ANTENNAMAX_TEST_3D=1 on a machine with a display",
)
def test_3d_view_smoke(qtbot):
    pytest.importorskip("pyvistaqt")
    w = MainWindow("examples/qfh_137mhz.yaml", use_3d=True, backend="thread")
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.calculation_finished, timeout=TIMEOUT):
        pass
    assert w.scene.available
    w.scene.close_plotter()
    w.calculator.close()


def test_menu_bar_is_inside_the_window(qtbot, window):
    assert not window.menuBar().isNativeMenuBar()
    titles = [a.text() for a in window.menuBar().actions()]
    assert titles == ["&File", "&Design", "&Help"]


def test_same_look_on_every_os(qtbot):
    from PySide6 import QtWidgets

    from antennamax.gui.theme import apply_look

    app = QtWidgets.QApplication.instance()
    apply_look(app)
    assert app.style().objectName().lower() == "fusion"
    assert app.palette().window().color().name() == "#f0f0f0"
    assert app.font().pixelSize() == 16
