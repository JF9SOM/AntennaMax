"""Qt widgets of the GUI: the parameter form, the sweep box and the result views.

The form is generated from the template's pydantic model (`gui.schema`); every input has an error
label under it, so that a problem is shown next to the field it belongs to.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_API", "pyside6")  # for matplotlib, before it picks a Qt binding

from typing import Any  # noqa: E402

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from antennamax.gui.schema import FieldSpec, template_fields  # noqa: E402
from antennamax.gui.state import (  # noqa: E402
    PATTERN_RESOLUTIONS,
    FieldError,
    FormValues,
)
from antennamax.gui.summary import SWEEP_COLUMNS, center_summary, sweep_rows  # noqa: E402
from antennamax.viz.data import DesignRun  # noqa: E402

ERROR_STYLE = "color: #c0392b; font-size: 11px;"
ERROR_BORDER = "border: 1px solid #c0392b;"
ERROR_CELL = QtGui.QColor("#f5b7b1")


def _error_label(name: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel()
    label.setObjectName(name)
    label.setStyleSheet(ERROR_STYLE)
    label.setWordWrap(True)
    label.hide()
    return label


def _set_error(editor: QtWidgets.QWidget, label: QtWidgets.QLabel, message: str | None) -> None:
    if message:
        label.setText(message)
        label.show()
        editor.setStyleSheet(ERROR_BORDER)
        editor.setToolTip(message)
    else:
        label.clear()
        label.hide()
        editor.setStyleSheet("")
        editor.setToolTip("")


class ElementTable(QtWidgets.QWidget):
    """Editable table of a list of rows (the elements of a Yagi), with add / remove buttons."""

    def __init__(self, spec: FieldSpec, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.spec = spec
        self.table = QtWidgets.QTableWidget(0, len(spec.columns))
        self.table.setObjectName(f"table_{spec.name}")
        self.table.setHorizontalHeaderLabels(
            [f"{c.label} [{c.unit}]" if c.unit else c.label for c in spec.columns]
        )
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.setMinimumHeight(120)
        add = QtWidgets.QPushButton("Add element")
        add.setObjectName("add_row")
        remove = QtWidgets.QPushButton("Remove selected")
        remove.setObjectName("remove_row")
        add.clicked.connect(lambda: self.add_row())
        remove.clicked.connect(self.remove_selected)
        self.error_label = _error_label(f"error_{spec.name}")
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        layout.addWidget(self.error_label)

    def add_row(self, texts: dict[str, str] | None = None) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        texts = texts or {}
        for col, spec in enumerate(self.spec.columns):
            self.table.setItem(row, col, QtWidgets.QTableWidgetItem(texts.get(spec.name, "")))

    def remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows and self.table.rowCount():
            rows = [self.table.rowCount() - 1]
        for row in rows:
            self.table.removeRow(row)

    def rows(self) -> list[dict[str, str]]:
        out = []
        for row in range(self.table.rowCount()):
            out.append(
                {
                    spec.name: (self.table.item(row, c).text() if self.table.item(row, c) else "")
                    for c, spec in enumerate(self.spec.columns)
                }
            )
        return out

    def set_rows(self, rows: list[dict[str, str]]) -> None:
        self.table.setRowCount(0)
        for texts in rows:
            self.add_row(texts)

    def show_errors(self, errors: list[FieldError]) -> None:
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                if item is not None:
                    item.setBackground(QtGui.QBrush())
                    item.setToolTip("")
        names = [c.name for c in self.spec.columns]
        messages = []
        for err in errors:
            if err.target[0] == "table":
                messages.append(err.message)
            elif err.target[0] == "row":
                _, row, column = err.target
                where = f"element {row + 1}" + (f", {column}" if column != "*" else "")
                messages.append(f"{where}: {err.message}")
                cols = range(self.table.columnCount()) if column == "*" else [names.index(column)]
                for c in cols:
                    item = self.table.item(row, c)
                    if item is not None:
                        item.setBackground(ERROR_CELL)
                        item.setToolTip(err.message)
        self.error_label.setText("\n".join(messages))
        self.error_label.setVisible(bool(messages))
        self.table.setStyleSheet(ERROR_BORDER if messages else "")


class ParamForm(QtWidgets.QWidget):
    """The parameters of the selected template, generated from its pydantic model."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._grid = QtWidgets.QGridLayout(self)
        self._grid.setColumnStretch(1, 1)
        self.template = ""
        self._editors: dict[str, QtWidgets.QWidget] = {}
        self._error_labels: dict[str, QtWidgets.QLabel] = {}
        self._specs: dict[str, FieldSpec] = {}
        self.table: ElementTable | None = None
        self.general_error = _error_label("error_general")

    def set_template(self, template: str, values: FormValues) -> None:
        """Rebuild the form for a template and fill it."""
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self.general_error:
                widget.hide()  # gone at once (deleteLater alone leaves it painted for a while)
                widget.setParent(None)
                widget.deleteLater()
        self._editors.clear()
        self._error_labels.clear()
        self._specs.clear()
        self.table = None
        self.template = template
        row = 0
        for spec in template_fields(template):
            self._specs[spec.name] = spec
            if spec.kind == "table":
                self._grid.addWidget(QtWidgets.QLabel(f"<b>{spec.label}</b>"), row, 0, 1, 3)
                self.table = ElementTable(spec)
                self.table.set_rows(values.rows)
                self._grid.addWidget(self.table, row + 1, 0, 1, 3)
                row += 2
                continue
            title = QtWidgets.QLabel(spec.label)
            title.setToolTip(spec.description or spec.name)
            if spec.kind == "choice":
                editor: QtWidgets.QWidget = QtWidgets.QComboBox()
                editor.addItems(list(spec.choices))
                editor.setCurrentText(values.fields.get(spec.name, str(spec.default)))
            else:
                editor = QtWidgets.QLineEdit(values.fields.get(spec.name, ""))
                placeholder = (
                    spec.to_display(spec.default) if spec.default is not None else "automatic"
                )
                editor.setPlaceholderText(placeholder if spec.optional else "required")
                editor.setToolTip(f"{spec.name}" + (f" [{spec.unit}]" if spec.unit else ""))
            editor.setObjectName(f"field_{spec.name}")
            unit = QtWidgets.QLabel(spec.unit)
            unit.setMinimumWidth(36)
            error = _error_label(f"error_{spec.name}")
            self._grid.addWidget(title, row, 0)
            self._grid.addWidget(editor, row, 1)
            self._grid.addWidget(unit, row, 2)
            self._grid.addWidget(error, row + 1, 1, 1, 2)
            self._editors[spec.name] = editor
            self._error_labels[spec.name] = error
            row += 2
        self._grid.addWidget(self.general_error, row, 0, 1, 3)
        self._grid.setRowStretch(row + 1, 1)

    def fill(self, values: FormValues) -> None:
        self.set_template(values.template, values)

    def editor(self, name: str) -> QtWidgets.QWidget:
        return self._editors[name]

    def error_text(self, name: str) -> str:
        label = self._error_labels[name]
        return label.text() if not label.isHidden() else ""

    def values_into(self, values: FormValues) -> None:
        for name, editor in self._editors.items():
            values.fields[name] = (
                editor.currentText() if isinstance(editor, QtWidgets.QComboBox) else editor.text()
            )
        values.rows = self.table.rows() if self.table is not None else []

    def clear_errors(self) -> None:
        for name, label in self._error_labels.items():
            _set_error(self._editors[name], label, None)
        _set_error(self.general_error, self.general_error, None)
        if self.table is not None:
            self.table.show_errors([])

    def show_errors(self, errors: list[FieldError]) -> None:
        """Show each problem next to its field; whatever has no field goes to the general line."""
        self.clear_errors()
        table_errors: list[FieldError] = []
        general: list[str] = []
        for err in errors:
            kind = err.target[0]
            if kind == "field" and err.target[1] in self._editors:
                name = err.target[1]
                _set_error(self._editors[name], self._error_labels[name], err.message)
            elif kind in ("row", "table") and self.table is not None:
                table_errors.append(err)
            elif kind in ("field", "general"):
                general.append(err.message)
        if table_errors and self.table is not None:
            self.table.show_errors(table_errors)
        if general:
            self.general_error.setText("\n".join(general))
            self.general_error.show()


class SweepBox(QtWidgets.QGroupBox):
    """Frequency sweep and pattern resolution."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__("Sweep and pattern", parent)
        grid = QtWidgets.QGridLayout(self)
        grid.setColumnStretch(1, 1)
        self.start = QtWidgets.QLineEdit()
        self.stop = QtWidgets.QLineEdit()
        self.points = QtWidgets.QLineEdit()
        self.pattern = QtWidgets.QComboBox()
        self.pattern.addItems(list(PATTERN_RESOLUTIONS))
        self._editors: dict[str, QtWidgets.QWidget] = {
            "start": self.start,
            "stop": self.stop,
            "points": self.points,
            "pattern": self.pattern,
        }
        self._labels: dict[str, QtWidgets.QLabel] = {}
        for row, (key, title, unit) in enumerate(
            (
                ("start", "start", "MHz"),
                ("stop", "stop", "MHz"),
                ("points", "points", ""),
                ("pattern", "pattern step", "deg"),
            )
        ):
            editor = self._editors[key]
            editor.setObjectName(f"sweep_{key}")
            grid.addWidget(QtWidgets.QLabel(title), row * 2, 0)
            grid.addWidget(editor, row * 2, 1)
            grid.addWidget(QtWidgets.QLabel(unit), row * 2, 2)
            label = _error_label(f"error_sweep_{key}")
            self._labels[key] = label
            grid.addWidget(label, row * 2 + 1, 1, 1, 2)
        self.general = _error_label("error_sweep_general")
        grid.addWidget(self.general, 8, 0, 1, 3)

    def fill(self, values: FormValues) -> None:
        self.start.setText(values.sweep_start_mhz)
        self.stop.setText(values.sweep_stop_mhz)
        self.points.setText(values.sweep_points)
        if self.pattern.findText(values.pattern_deg) < 0:
            self.pattern.addItem(values.pattern_deg)
        self.pattern.setCurrentText(values.pattern_deg)

    def values_into(self, values: FormValues) -> None:
        values.sweep_start_mhz = self.start.text()
        values.sweep_stop_mhz = self.stop.text()
        values.sweep_points = self.points.text()
        values.pattern_deg = self.pattern.currentText()

    def error_text(self, key: str) -> str:
        label = self._labels[key]
        return label.text() if not label.isHidden() else ""

    def show_errors(self, errors: list[FieldError]) -> None:
        for key, label in self._labels.items():
            _set_error(self._editors[key], label, None)
        _set_error(self.general, self.general, None)
        general = []
        for err in errors:
            kind = err.target[0]
            if kind == "sweep" and err.target[1] in self._labels:
                key = err.target[1]
                _set_error(self._editors[key], self._labels[key], err.message)
            elif kind == "pattern":
                _set_error(self.pattern, self._labels["pattern"], err.message)
            elif kind == "sweep":
                general.append(err.message)
        if general:
            self.general.setText("\n".join(general))
            self.general.show()


# --- result views ----------------------------------------------------------------------------


class MplView(QtWidgets.QWidget):
    """A matplotlib figure with its toolbar; `draw_fn(run, figure)` draws a result into it."""

    def __init__(self, draw_fn: Any, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
        from matplotlib.figure import Figure

        self.draw_fn = draw_fn
        self.figure = Figure(figsize=(7, 5))
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        layout.addWidget(self.canvas, 1)
        self.clear()

    def clear(self) -> None:
        self.figure.clear()
        self.figure.text(0.5, 0.5, "Press Calculate", ha="center", va="center", color="gray")
        self.canvas.draw_idle()

    def show_run(self, run: DesignRun) -> None:
        self.figure.clear()
        self.draw_fn(run, self.figure)
        self.canvas.draw_idle()


class Scene3D(QtWidgets.QWidget):
    """The 3D view: wires and radiation pattern on an interactive pyvista plotter.

    If the plotter cannot be created (no OpenGL, pyvistaqt missing) a message takes its place
    and the rest of the window keeps working.
    """

    def __init__(self, enabled: bool = True, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.plotter: Any = None
        self.message = ""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if enabled:
            try:
                from pyvistaqt import QtInteractor

                self.plotter = QtInteractor(self)
                layout.addWidget(self.plotter, 1)
            except Exception as exc:  # noqa: BLE001 - e.g. no OpenGL on this machine
                self.plotter = None
                self.message = f"3D view unavailable: {type(exc).__name__}: {exc}"
        else:
            self.message = "3D view is switched off"
        if self.plotter is None:
            label = QtWidgets.QLabel(self.message)
            label.setAlignment(QtCore.Qt.AlignCenter)
            layout.addWidget(label, 1)

    @property
    def available(self) -> bool:
        return self.plotter is not None

    def show_run(self, run: DesignRun) -> None:
        if self.plotter is None:
            return
        from antennamax.viz.view3d import populate_scene

        self.plotter.clear()
        # The render window's size is in device pixels (twice the widget's on a retina screen).
        width, height = self.plotter.window_size
        ratio = float(self.devicePixelRatioF())
        size = (max(int(width), 400), max(int(height), 300))
        populate_scene(self.plotter, run, size, ratio)
        self.plotter.render()

    def close_plotter(self) -> None:
        if self.plotter is not None:
            self.plotter.close()
            self.plotter = None


class SummaryView(QtWidgets.QWidget):
    """The numbers: a table over the sweep, and the figures at the design frequency."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.table = QtWidgets.QTableWidget(0, len(SWEEP_COLUMNS))
        self.table.setObjectName("sweep_table")
        self.table.setHorizontalHeaderLabels(list(SWEEP_COLUMNS))
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.details = QtWidgets.QTableWidget(0, 2)
        self.details.setObjectName("center_table")
        self.details.setHorizontalHeaderLabels(["At the design frequency", "Value"])
        self.details.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.details.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.details, 3)
        layout.addWidget(self.table, 2)

    def clear(self) -> None:
        self.table.setRowCount(0)
        self.details.setRowCount(0)

    def show_run(self, run: DesignRun) -> None:
        rows = sweep_rows(run)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                item = QtWidgets.QTableWidgetItem(text)
                item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        pairs = center_summary(run)
        self.details.setRowCount(len(pairs))
        for r, (label, value) in enumerate(pairs):
            self.details.setItem(r, 0, QtWidgets.QTableWidgetItem(label))
            self.details.setItem(r, 1, QtWidgets.QTableWidgetItem(value))

    def center_values(self) -> dict[str, str]:
        out = {}
        for r in range(self.details.rowCount()):
            out[self.details.item(r, 0).text()] = self.details.item(r, 1).text()
        return out


class WarningsView(QtWidgets.QPlainTextEdit):
    """Warnings and errors of the last calculation."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setObjectName("warnings_text")
        self.setPlaceholderText("No warnings.")

    def show_messages(self, warnings: list[str], error: str | None = None) -> None:
        lines = []
        if error:
            lines.append(f"ERROR: {error}")
        lines.extend(f"WARNING {w}" for w in warnings)
        self.setPlainText("\n\n".join(lines))
