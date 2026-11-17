"""Start the GUI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from antennamax.core.optional import require


def has_display() -> bool:
    """Can a window be opened here? (Linux needs an X or Wayland display unless Qt is told to
    run without one.)"""
    if sys.platform != "linux" or os.environ.get("QT_QPA_PLATFORM"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def window_icon():
    """The application icon (SVG shipped with the package), or None if Qt cannot load it."""
    from PySide6 import QtGui

    path = Path(__file__).parent / "resources" / "icon.svg"
    icon = QtGui.QIcon(str(path))
    return None if icon.isNull() else icon


def run_gui(design_path: Path | None = None) -> int:
    """Open the main window (with `design_path` loaded and calculated) and run until closed."""
    require("PySide6.QtWidgets", "start the GUI", extra="gui")
    if not has_display():
        print(
            "antennamax: error: no display found (set DISPLAY, or QT_QPA_PLATFORM=offscreen)",
            file=sys.stderr,
        )
        return 2
    from PySide6 import QtWidgets

    from antennamax.gui.theme import apply_look
    from antennamax.gui.window import MainWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    app.setApplicationName("AntennaMax")
    apply_look(app)
    icon = window_icon()
    if icon is not None:
        app.setWindowIcon(icon)
    window = MainWindow(design_path)
    window.show()
    return app.exec()
