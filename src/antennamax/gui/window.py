"""The main window: form on the left, results on the right, calculation in a worker process."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from antennamax.core.units import hz_to_mhz
from antennamax.gui.calc import (
    Calculator,
    ComputeOutcome,
    PartsOutcome,
    compute_design,
    export_parts,
)
from antennamax.gui.state import (
    TEMPLATE_NAMES,
    FieldError,
    FormValues,
    default_values,
    mapping_to_yaml,
    validate,
    values_from_file,
)
from antennamax.gui.widgets import (
    MplView,
    ParamForm,
    Scene3D,
    SummaryView,
    SweepBox,
    WarningsView,
)
from antennamax.io.design import DesignError
from antennamax.viz import plot2d
from antennamax.viz.data import DesignRun


class _Signals(QtCore.QObject):
    done = QtCore.Signal(int, object)


class _WaitTask(QtCore.QRunnable):
    """Waits for a future in a pool thread and hands the result to the GUI thread."""

    def __init__(self, future: Any, request: int, signals: _Signals) -> None:
        super().__init__()
        self.future, self.request, self.signals = future, request, signals

    def run(self) -> None:
        try:
            result: Any = self.future.result()
        except BaseException as exc:  # noqa: BLE001 - a dead worker process, for example
            result = exc
        self.signals.done.emit(self.request, result)


class MainWindow(QtWidgets.QMainWindow):
    """AntennaMax: edit a design, calculate it, look at the results."""

    calculation_finished = QtCore.Signal(bool)  # True if there is a result
    parts_finished = QtCore.Signal(bool)

    def __init__(
        self,
        design_path: str | Path | None = None,
        *,
        use_3d: bool | None = None,
        backend: str | None = None,
        auto_calculate: bool = True,
        theme: str = "light",
        persist_theme: bool = False,
    ) -> None:
        super().__init__()
        self.theme = theme
        self._persist_theme = persist_theme
        self.setWindowTitle("AntennaMax")
        self.resize(1400, 850)
        if use_3d is None:
            use_3d = os.environ.get("ANTENNAMAX_GUI_3D", "1") != "0"
        self.calculator = Calculator(backend)
        self.run: DesignRun | None = None
        self.mapping: dict[str, Any] | None = None
        self.path: Path | None = None
        self.last_parts_report = ""
        self._request = 0
        self._started = 0.0
        self._loading = False
        self._dialogs: list[QtWidgets.QDialog] = []
        self._signals = _Signals()
        self._signals.done.connect(self._on_done)
        self._parts_signals = _Signals()
        self._parts_signals.done.connect(self._on_parts_done)

        # --- left: template, parameters, sweep, calculate -----------------------------------
        self.template_box = QtWidgets.QComboBox()
        self.template_box.setObjectName("template_box")
        self.template_box.addItems(list(TEMPLATE_NAMES))
        self.form = ParamForm()
        self.sweep = SweepBox()
        inner = QtWidgets.QWidget()
        inner_layout = QtWidgets.QVBoxLayout(inner)
        header = QtWidgets.QFormLayout()
        header.addRow("Template", self.template_box)
        inner_layout.addLayout(header)
        inner_layout.addWidget(self.form)
        inner_layout.addWidget(self.sweep)
        inner_layout.addStretch(1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setMinimumWidth(380)
        self.calc_button = QtWidgets.QPushButton("Calculate")
        self.calc_button.setObjectName("calculate_button")
        self.calc_button.setDefault(True)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)  # busy indicator
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(8)
        self.progress.hide()
        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(scroll, 1)
        left_layout.addWidget(self.progress)
        left_layout.addWidget(self.calc_button)

        # --- right: result tabs -------------------------------------------------------------
        self.scene = Scene3D(enabled=use_3d)
        self.impedance_view = MplView(plot2d.draw_impedance)
        self.pattern_view = MplView(plot2d.draw_patterns)
        for view in (self.impedance_view, self.pattern_view, self.scene):
            view.theme = self.theme
        self.summary = SummaryView()
        self.warnings = WarningsView()
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self.scene, "3D view")
        self.tabs.addTab(self.impedance_view, "SWR and R/X")
        self.tabs.addTab(self.pattern_view, "Patterns")
        self.tabs.addTab(self.summary, "Summary")
        self.tabs.addTab(self.warnings, "Warnings")
        self._warnings_tab = self.tabs.indexOf(self.warnings)

        splitter = QtWidgets.QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 980])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Ready")
        self._build_menus()

        self.template_box.currentTextChanged.connect(self._on_template_changed)
        self.calc_button.clicked.connect(self.calculate)
        self.apply_values(default_values("dipole"))
        self.calculator_warm = False
        if design_path is not None:
            loaded = self.open_file(design_path)
            if loaded and auto_calculate:
                QtCore.QTimer.singleShot(0, self.calculate)

    # --- menus ------------------------------------------------------------------------------

    def _build_menus(self) -> None:
        # The menu bar stays inside the window on every OS (no macOS global menu bar).
        self.menuBar().setNativeMenuBar(False)
        file_menu = self.menuBar().addMenu("&File")
        self.open_action = file_menu.addAction("&Open design.yaml…", self._choose_open)
        self.open_action.setShortcut(QtGui.QKeySequence.Open)
        self.save_action = file_menu.addAction("&Save design.yaml…", self._choose_save)
        self.save_action.setShortcut(QtGui.QKeySequence.Save)
        file_menu.addSeparator()
        self.json_action = file_menu.addAction("Export result as &JSON…", self._choose_json)
        self.parts_action = file_menu.addAction(
            "Export QFH &parts (STL / STEP)…", self._choose_parts
        )
        file_menu.addSeparator()
        file_menu.addAction("&Quit", self.close).setShortcut(QtGui.QKeySequence.Quit)
        design_menu = self.menuBar().addMenu("&Design")
        calc = design_menu.addAction("&Calculate", self.calculate)
        calc.setShortcut(QtGui.QKeySequence("F5"))
        view_menu = self.menuBar().addMenu("&View")
        group = QtGui.QActionGroup(self)
        self.theme_actions: dict[str, QtGui.QAction] = {}
        for name, label in (("light", "&Light"), ("dark", "&Dark")):
            action = view_menu.addAction(label, lambda n=name: self.set_theme(n))
            action.setCheckable(True)
            action.setChecked(name == self.theme)
            group.addAction(action)
            self.theme_actions[name] = action
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction("&About", self._about)
        self._update_menu_state()

    def set_theme(self, theme: str) -> None:
        """Switch between the light and the dark look (window, plots and 3D view)."""
        from antennamax.gui.theme import apply_look

        self.theme = theme
        app = QtWidgets.QApplication.instance()
        if app is not None:
            apply_look(app, theme)
        for view in (self.impedance_view, self.pattern_view, self.scene):
            view.set_theme(theme)
        self.theme_actions[theme].setChecked(True)
        if self._persist_theme:
            QtCore.QSettings("AntennaMax", "AntennaMax").setValue("theme", theme)

    def _update_menu_state(self) -> None:
        self.json_action.setEnabled(self.run is not None)
        self.parts_action.setEnabled(self.template_box.currentText() == "qfh")

    def _about(self) -> None:
        QtWidgets.QMessageBox.about(
            self,
            "About AntennaMax",
            "AntennaMax: antenna simulator for amateur radio.\n"
            "Calculations use the same code as the command line (NEC2 via PyNEC).",
        )

    # --- form <-> values ------------------------------------------------------------------

    def values(self) -> FormValues:
        values = FormValues(template=self.template_box.currentText())
        self.form.values_into(values)
        self.sweep.values_into(values)
        return values

    def apply_values(self, values: FormValues) -> None:
        self._loading = True
        try:
            self.template_box.setCurrentText(values.template)
            self.form.fill(values)
            self.sweep.fill(values)
            self._show_errors([])
        finally:
            self._loading = False
        self._update_menu_state()

    def _on_template_changed(self, name: str) -> None:
        if self._loading or not name:
            return
        self.path = None
        self.apply_values(default_values(name))
        self._update_title()

    def _show_errors(self, errors: list[FieldError]) -> None:
        self.form.show_errors(errors)
        self.sweep.show_errors(errors)

    def _update_title(self) -> None:
        name = f" — {self.path.name}" if self.path else ""
        self.setWindowTitle(f"AntennaMax{name}")

    # --- files --------------------------------------------------------------------------------

    def report_problem(self, message: str) -> None:
        """Show a problem without a modal dialog: status bar and the Warnings tab."""
        self.statusBar().showMessage(message.splitlines()[0] if message else "Problem")
        self.warnings.show_messages([], error=message)
        self.tabs.setTabText(self._warnings_tab, "Warnings (!)")
        self.tabs.setCurrentIndex(self._warnings_tab)

    def open_file(self, path: str | Path) -> bool:
        path = Path(path)
        try:
            values = values_from_file(path)
        except DesignError as exc:
            self.report_problem(str(exc))
            return False
        self.apply_values(values)
        self.path = path
        self._update_title()
        self.statusBar().showMessage(f"Opened {path}")
        return True

    def save_file(self, path: str | Path) -> bool:
        design, mapping, errors = validate(self.values())
        self._show_errors(errors)
        if design is None or mapping is None:
            self.statusBar().showMessage("Cannot save: fix the highlighted inputs")
            return False
        path = Path(path)
        try:
            path.write_text(mapping_to_yaml(mapping), encoding="utf-8")
        except OSError as exc:
            self.report_problem(f"cannot write {path}: {exc.strerror or exc}")
            return False
        self.path = path
        self._update_title()
        self.statusBar().showMessage(f"Saved {path}")
        return True

    def export_json(self, path: str | Path) -> bool:
        if self.run is None or self.mapping is None:
            self.statusBar().showMessage("Nothing to export: calculate first")
            return False
        run = self.run
        payload = {
            "template": run.design.template_name,
            "design": self.mapping,
            "center_frequency_hz": run.center_frequency_hz,
            "sweep": run.sweep_result.to_dict(),
            "pattern": run.pattern_result.to_dict(),
        }
        try:
            Path(path).write_text(json.dumps(payload), encoding="utf-8")
        except OSError as exc:
            self.report_problem(f"cannot write {path}: {exc.strerror or exc}")
            return False
        self.statusBar().showMessage(f"Exported {path}")
        return True

    def export_parts(self, directory: str | Path) -> bool:
        """Write the printable parts (the `parts` command) in the background."""
        design, mapping, errors = validate(self.values())
        self._show_errors(errors)
        if design is None or mapping is None:
            self.statusBar().showMessage("Cannot export: fix the highlighted inputs")
            return False
        if design.template_name != "qfh":
            self.statusBar().showMessage("Printable parts exist for the QFH only")
            return False
        self._set_busy(True, "Building parts…")
        future = self.calculator.submit(export_parts, mapping_to_yaml(mapping), str(directory))
        self._request += 1
        request = self._request
        QtCore.QThreadPool.globalInstance().start(_WaitTask(future, request, self._parts_signals))
        return True

    def _choose_open(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open design", "", "Design files (*.yaml *.yml);;All files (*)"
        )
        if path:
            if self.open_file(path):
                self.calculate()

    def _choose_save(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save design", str(self.path or "design.yaml"), "Design files (*.yaml *.yml)"
        )
        if path:
            self.save_file(path)

    def _choose_json(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export result", "result.json", "JSON (*.json)"
        )
        if path:
            self.export_json(path)

    def _choose_parts(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Folder for the STL / STEP files"
        )
        if directory:
            self.export_parts(directory)

    # --- calculation -------------------------------------------------------------------------

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.calc_button.setEnabled(not busy)
        self.progress.setVisible(busy)
        if message:
            self.statusBar().showMessage(message)

    def calculate(self) -> bool:
        """Check the inputs and start the calculation in the worker. Returns False on bad input."""
        design, mapping, errors = validate(self.values())
        self._show_errors(errors)
        if design is None or mapping is None:
            self.statusBar().showMessage("Cannot calculate: fix the highlighted inputs")
            return False
        self.mapping = mapping
        self._request += 1
        request = self._request
        self._started = time.monotonic()
        self._set_busy(True, "Calculating…")
        future = self.calculator.submit(compute_design, mapping)
        QtCore.QThreadPool.globalInstance().start(_WaitTask(future, request, self._signals))
        return True

    def _on_done(self, request: int, result: Any) -> None:
        if request != self._request:
            return  # an older calculation: the inputs have been calculated again since
        self._set_busy(False)
        if isinstance(result, BaseException):
            self.calculator.close()  # a fresh worker for the next calculation
            result = ComputeOutcome(error=f"the calculation process stopped: {result}")
        outcome: ComputeOutcome = result
        self.warnings.show_messages(outcome.warnings, outcome.error)
        count = len(outcome.warnings) + (1 if outcome.error else 0)
        self.tabs.setTabText(self._warnings_tab, f"Warnings ({count})" if count else "Warnings")
        if outcome.run is None:
            self.run = None
            self.statusBar().showMessage((outcome.error or "No result").splitlines()[0])
            self.tabs.setCurrentIndex(self._warnings_tab)
            self._update_menu_state()
            self.calculation_finished.emit(False)
            return
        self.run = outcome.run
        self.scene.show_run(outcome.run)
        self.impedance_view.show_run(outcome.run)
        self.pattern_view.show_run(outcome.run)
        self.summary.show_run(outcome.run)
        elapsed = time.monotonic() - self._started
        self.statusBar().showMessage(
            f"Done in {elapsed:.2f} s — {hz_to_mhz(outcome.run.center_frequency_hz):.3f} MHz"
            + (f", {count} warning(s)" if count else "")
        )
        self._update_menu_state()
        self.calculation_finished.emit(True)

    def _on_parts_done(self, request: int, result: Any) -> None:
        self._set_busy(False)
        if isinstance(result, BaseException):
            self.calculator.close()
            result = PartsOutcome(1, "", f"the calculation process stopped: {result}")
        outcome: PartsOutcome = result
        text = outcome.stdout + (("\n" + outcome.stderr) if outcome.stderr else "")
        self.last_parts_report = text
        ok = outcome.code == 0
        self.statusBar().showMessage("Parts written" if ok else "Parts export failed")
        self.show_text_dialog("QFH parts" if ok else "QFH parts: failed", text)
        self.parts_finished.emit(ok)

    def show_text_dialog(self, title: str, text: str) -> None:
        """A non-modal window with some text (the parts listing)."""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(900, 520)
        box = QtWidgets.QPlainTextEdit(text)
        box.setReadOnly(True)
        box.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(dialog.close)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(box)
        layout.addWidget(close)
        self._dialogs.append(dialog)
        dialog.show()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802 - Qt API
        self.calculator.close()
        self.scene.close_plotter()
        super().closeEvent(event)
