"""One look on every OS: Fusion style, light or dark palette, fixed font size, in-window menu bar.

The platform styles (macOS, Windows 11) and the OS dark/light setting would otherwise make the
window look different on each system. Fonts still come from the OS (only the size is fixed).
"""

from __future__ import annotations

from PySide6 import QtGui, QtWidgets

# In pixels: a point is 1 px on macOS but about 1.33 px on Windows, so points would not match.
FONT_PIXEL_SIZE = 16

THEMES = ("light", "dark")

_LIGHT = {
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

_DARK = {
    "Window": "#2b2d31",
    "WindowText": "#e6e6e6",
    "Base": "#1e1f22",
    "AlternateBase": "#26282c",
    "Text": "#e6e6e6",
    "Button": "#3a3d42",
    "ButtonText": "#e6e6e6",
    "ToolTipBase": "#3a3d42",
    "ToolTipText": "#e6e6e6",
    "Highlight": "#4a8cf0",
    "HighlightedText": "#ffffff",
    "Link": "#6ea8ff",
    "PlaceholderText": "#8a8d93",
}

# Colours for the plots and the 3D view: (background, text, grid/axis lines).
PLOT_COLORS = {
    "light": ("#ffffff", "#202020", "#cccccc"),
    "dark": ("#1e1f22", "#e6e6e6", "#4a4d52"),
}


def palette(theme: str = "light") -> QtGui.QPalette:
    colors = _DARK if theme == "dark" else _LIGHT
    palette = QtGui.QPalette()
    for name, value in colors.items():
        palette.setColor(getattr(QtGui.QPalette.ColorRole, name), QtGui.QColor(value))
    disabled = QtGui.QColor("#7a7d83" if theme == "dark" else "#9a9a9a")
    for role in (
        QtGui.QPalette.ColorRole.WindowText,
        QtGui.QPalette.ColorRole.Text,
        QtGui.QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QtGui.QPalette.ColorGroup.Disabled, role, disabled)
    return palette


def light_palette() -> QtGui.QPalette:
    return palette("light")


def mpl_rc(theme: str) -> dict[str, object]:
    """matplotlib rc settings for the plots in the given theme."""
    bg, fg, grid = PLOT_COLORS[theme]
    return {
        "figure.facecolor": bg,
        "axes.facecolor": bg,
        "savefig.facecolor": bg,
        "axes.edgecolor": fg,
        "axes.labelcolor": fg,
        "axes.titlecolor": fg,
        "text.color": fg,
        "xtick.color": fg,
        "ytick.color": fg,
        "grid.color": grid,
        "legend.facecolor": bg,
        "legend.edgecolor": grid,
        "legend.labelcolor": fg,
    }


def apply_look(app: QtWidgets.QApplication, theme: str = "light") -> None:
    """Give the whole application the same style, palette and font size on every OS.

    `theme` is "light" or "dark" (chosen in the View menu, never taken from the OS setting).
    """
    app.setStyle("Fusion")
    app.setPalette(palette(theme))
    font = app.font()
    font.setPixelSize(FONT_PIXEL_SIZE)
    app.setFont(font)
