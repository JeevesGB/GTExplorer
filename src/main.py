from __future__ import annotations
import os
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ["QT_OPENGL"] = "desktop"

from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

fmt = QSurfaceFormat()
fmt.setRenderableType(QSurfaceFormat.OpenGL)
fmt.setProfile(QSurfaceFormat.CompatibilityProfile)
fmt.setDepthBufferSize(24)
fmt.setStencilBufferSize(8)
fmt.setVersion(2, 1)
QSurfaceFormat.setDefaultFormat(fmt)

from gtarcexplorer.gui import run

if __name__ == "__main__":
    run()