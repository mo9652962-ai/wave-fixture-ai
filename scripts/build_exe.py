"""Build Windows single-file portable exe (PyInstaller onefile).

Usage: uv run --with pyinstaller python scripts/build_exe.py
Artifact: dist/wave-fixture-ai.exe
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("build-exe")

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "scripts" / "exe_entry.py"
WEB_DIR = ROOT / "web"


def main() -> int:
    log.info("[*] Starting Windows portable EXE build via PyInstaller...")
    dist_dir = ROOT / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--clean",
        "--noconfirm",
        "--name",
        "wave-fixture-ai",
        "--add-data",
        f"{WEB_DIR};web",
        "--copy-metadata",
        "ezdxf",
        "--copy-metadata",
        "shapely",
        "--copy-metadata",
        "trimesh",
        "--copy-metadata",
        "fastapi",
        "--copy-metadata",
        "uvicorn",
        "--copy-metadata",
        "starlette",
        "--copy-metadata",
        "pydantic",
        "--copy-metadata",
        "matplotlib",
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.loops",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.protocols",
        "--hidden-import",
        "uvicorn.protocols.http",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.lifespan",
        "--hidden-import",
        "uvicorn.lifespan.on",
        str(ENTRY),
    ]

    log.info(f"    Running: {' '.join(cmd[:6])} ...")
    res = subprocess.run(
        cmd,
        cwd=str(ROOT),
        shell=False,
        check=False,
    )

    if res.returncode == 0:
        exe_path = dist_dir / "wave-fixture-ai.exe"
        if exe_path.is_file():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            log.info(f"[+] Portable EXE built successfully: {exe_path} ({size_mb:.1f} MB)")
        else:
            log.warning("[-] Build reported success but exe not found in dist/")
    else:
        log.error(f"[-] PyInstaller exited with code {res.returncode}")

    return res.returncode


if __name__ == "__main__":
    raise SystemExit(main())
