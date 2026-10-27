"""PyInstaller entry launcher for wave-fixture-ai.exe."""
from __future__ import annotations

import multiprocessing

from web_server import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
