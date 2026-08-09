from __future__ import annotations
import sys
from gtarcexplorer.gui import run
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


if __name__ == "__main__":
    run()