"""Shared pytest setup: Qt runs without a display (offscreen) for the GUI tests."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyside6")
# The calculation worker: threads are enough for the tests (the process worker has its own test).
os.environ.setdefault("ANTENNAMAX_GUI_BACKEND", "thread")
# VTK/OpenGL is unreliable on headless CI: the interactive 3D view is only tested on request.
os.environ.setdefault("ANTENNAMAX_GUI_3D", "0")
