"""
Tests for KiCad PCM (Plugin and Content Manager) metadata, plugin layout, and distribution zip.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
PCM_DIR = REPO_ROOT / "community" / "kicad-pcm"
METADATA_FILE = PCM_DIR / "metadata.json"
PLUGINS_DIR = PCM_DIR / "plugins"
DIST_DIR = PCM_DIR / "dist"


def test_pcm_metadata_structure_and_fields():
    assert METADATA_FILE.is_file(), "metadata.json missing"
    meta = json.loads(METADATA_FILE.read_text(encoding="utf-8"))

    # Required official fields
    assert meta.get("identifier") == "com.github.mo9652962-ai.wave-fixture-ai"
    assert meta.get("name") == "Wave Fixture AI"
    assert meta.get("category") == "Manufacturing"
    assert meta.get("license") == "MIT"
    assert "author" in meta
    assert meta["author"].get("name") == "mo9652962-ai"

    # Versions
    assert "versions" in meta and len(meta["versions"]) >= 1
    v0 = meta["versions"][0]
    assert v0.get("version") in ("0.5.1", "0.5.2")
    assert v0.get("status") == "stable"
    assert v0.get("kicad_version") == ">=8.0.0"
    assert v0.get("download_size", 0) > 0
    assert v0.get("install_size", 0) > 0
    assert len(v0.get("download_sha256", "")) == 64


def test_pcm_plugin_files_and_icon_integrity():
    assert PLUGINS_DIR.is_dir()
    init_file = PLUGINS_DIR / "__init__.py"
    action_file = PLUGINS_DIR / "action_wave_fixture.py"
    icon_file = PLUGINS_DIR / "icon.png"

    assert init_file.is_file() and init_file.stat().st_size > 0
    assert action_file.is_file() and action_file.stat().st_size > 0
    assert icon_file.is_file() and icon_file.stat().st_size > 0

    with Image.open(icon_file) as im:
        assert im.format == "PNG"
        w, h = im.size
        assert w == h, f"icon must be square, got {w}x{h}"
        assert w in (24, 26, 48, 64), f"icon size {w}x{h} outside recommended sizes"


def test_pcm_zip_archive_integrity():
    import sys
    scripts_dir = str(REPO_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from build_kicad_pcm_package import build_pcm_package, validate_source_files

    meta = validate_source_files()
    version = meta["versions"][0]["version"]
    zip_path = DIST_DIR / f"wave-fixture-ai-kicad-pcm-v{version}.zip"

    # If not yet built on fresh CI checkout, run builder to verify end-to-end build
    if not zip_path.is_file():
        zip_path = build_pcm_package(meta)

    assert zip_path.is_file(), f"Distribution zip missing at {zip_path}"

    # Verify true SHA256 matches metadata.json claim
    h = hashlib.sha256()
    with open(zip_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    actual_sha = h.hexdigest().lower()

    # Re-read metadata after possible build
    updated_meta = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
    claimed_sha = updated_meta["versions"][0]["download_sha256"].lower()
    assert actual_sha == claimed_sha, f"SHA256 mismatch: claimed={claimed_sha}, actual={actual_sha}"

    # Verify file contents inside zip
    with zipfile.ZipFile(zip_path, "r") as z:
        names = z.namelist()
        assert "metadata.json" in names
        assert "plugins/__init__.py" in names
        assert "plugins/action_wave_fixture.py" in names
        assert "plugins/icon.png" in names


def test_action_wave_fixture_class_contract():
    # Read source directly to verify class and methods without requiring pcbnew C++ binary
    src = (PLUGINS_DIR / "action_wave_fixture.py").read_text(encoding="utf-8")
    assert "class WaveFixturePlugin" in src
    assert "def defaults(self):" in src
    assert "def Run(self):" in src
    assert "self.show_on_toolbar = True" in src
    assert "self.icon_file_name" in src
