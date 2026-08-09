"""GTExplorer entry point."""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from gtarcexplorer.gui import run

if __name__ == "__main__":
    run()