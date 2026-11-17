"""One look on every OS: the Fusion style, a fixed light palette and an in-window menu bar.

The platform styles (macOS, Windows 11) and the OS dark/light setting would otherwise make the
window look different on each system. Fonts still come from the OS (only the size is fixed).
"""

from __future__ import annotations

from PySide6 import QtGui, QtWidgets

FONT_POINT_SIZE = 10

_COLORS = {
    "Window": "#f0f0f0",
    "WindowText": "#202020",
    "Base": "#ffffff",
    "AlternateBase": "#f5f5f5",
    "Text": "#202020",
    "Button": "#e6e6e6",
    "ButtonText": "#202020",
    "ToolTipBase": "#ffffdc",
    "ToolTipText": "#202020",
    "Highlight": "#2a6fdb",
    "HighlightedText": "#ffffff",
    "Link": "#2a6fdb",
    "PlaceholderText": "#8a8a8a",
}


def light_palette() -> QtGui.QPalette:
    palette = QtGui.QPalette()
    for name, value in _COLORS.items():
        palette.setColor(getattr(QtGui.QPalette.ColorRole, name), QtGui.QColor(value))
    disabled = QtGui.QColor("#9a9a9a")
    for role in (
        QtGui.QPalette.ColorRole.WindowText,
        QtGui.QPalette.ColorRole.Text,
        QtGui.QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QtGui.QPalette.ColorGroup.Disabled, role, disabled)
    return palette


def apply_look(app: QtWidgets.QApplication) -> None:
    """Give the whole application the same style, palette and font size on every OS."""
    app.setStyle("Fusion")
    app.setPalette(light_palette())
    font = app.font()
    font.setPointSize(FONT_POINT_SIZE)
    app.setFont(font)
