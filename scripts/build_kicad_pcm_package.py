"""
Builds and validates the KiCad PCM (Plugin and Content Manager) distribution package.
Generates:
1. Validated and compressed zip: community/kicad-pcm/dist/wave-fixture-ai-kicad-pcm-v0.5.1.zip
2. Computes true SHA256, download_size, and install_size.
3. Automatically writes back accurate checksums and sizes to metadata.json.
4. Prepares the upstream GitLab package directory structure for direct submission.
"""

from __future__ import annotations

import hashlib
import json
import logging
import zipfile
from pathlib import Path

from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("kicad-pcm-builder")

REPO_ROOT = Path(__file__).resolve().parent.parent
PCM_DIR = REPO_ROOT / "community" / "kicad-pcm"
PLUGINS_DIR = PCM_DIR / "plugins"
METADATA_FILE = PCM_DIR / "metadata.json"
DIST_DIR = PCM_DIR / "dist"


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().lower()


def validate_source_files():
    log.info("[*] Step 1: Validating PCM source files...")
    if not METADATA_FILE.is_file():
        raise FileNotFoundError(f"Missing {METADATA_FILE}")

    meta = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
    required_keys = ["identifier", "name", "description", "category", "author", "license", "versions"]
    for k in required_keys:
        if k not in meta:
            raise ValueError(f"metadata.json missing required key: {k}")

    if not PLUGINS_DIR.is_dir():
        raise FileNotFoundError(f"Missing plugins directory: {PLUGINS_DIR}")

    required_plugins = ["__init__.py", "action_wave_fixture.py", "icon.png"]
    for pf in required_plugins:
        target = PLUGINS_DIR / pf
        if not target.is_file():
            raise FileNotFoundError(f"Missing plugin file: {target}")

    # Validate icon
    icon_path = PLUGINS_DIR / "icon.png"
    with Image.open(icon_path) as im:
        if im.format != "PNG":
            raise ValueError(f"Icon must be PNG format, found: {im.format}")
        w, h = im.size
        if w != h:
            raise ValueError(f"Icon must be square, found {w}x{h}")
        log.info(f"    Icon verified: {w}x{h} PNG ({icon_path.stat().st_size} bytes)")

    log.info("    Source files validation passed.")
    return meta


def build_pcm_package(meta: dict) -> Path:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    version = meta["versions"][0]["version"]
    zip_filename = f"wave-fixture-ai-kicad-pcm-v{version}.zip"
    zip_path = DIST_DIR / zip_filename

    log.info(f"[*] Step 2: Packaging PCM zip: {zip_path}...")

    # Compute uncompressed install_size
    install_size = 0
    files_to_pack = [
        (METADATA_FILE, "metadata.json"),
        (PLUGINS_DIR / "__init__.py", "plugins/__init__.py"),
        (PLUGINS_DIR / "action_wave_fixture.py", "plugins/action_wave_fixture.py"),
        (PLUGINS_DIR / "icon.png", "plugins/icon.png"),
    ]

    for src_path, _ in files_to_pack:
        install_size += src_path.stat().st_size

    # First pass: create archive
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for src_path, arc_name in files_to_pack:
            z.write(src_path, arc_name)

    download_size = zip_path.stat().st_size
    sha256_hash = compute_sha256(zip_path)

    log.info(f"    Initial ZIP size: {download_size} bytes, SHA256: {sha256_hash}")

    # Update metadata with true hash & size
    meta["versions"][0]["download_sha256"] = sha256_hash
    meta["versions"][0]["download_size"] = download_size
    meta["versions"][0]["install_size"] = install_size
    meta["versions"][0]["download_url"] = (
        f"https://github.com/mo9652962-ai/wave-fixture-ai/releases/download/v{version}/{zip_filename}"
    )

    formatted_meta = json.dumps(meta, ensure_ascii=False, indent=2) + "\n"
    METADATA_FILE.write_text(formatted_meta, encoding="utf-8")
    log.info(f"    Updated {METADATA_FILE} with accurate sha256 and sizes.")

    # Re-pack with the updated metadata.json so the zip itself contains the final metadata
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for src_path, arc_name in files_to_pack:
            z.write(src_path, arc_name)

    final_download_size = zip_path.stat().st_size
    final_sha256 = compute_sha256(zip_path)

    # If re-pack shifted size or hash, settle it
    if final_sha256 != sha256_hash or final_download_size != download_size:
        meta["versions"][0]["download_sha256"] = final_sha256
        meta["versions"][0]["download_size"] = final_download_size
        formatted_meta = json.dumps(meta, ensure_ascii=False, indent=2) + "\n"
        METADATA_FILE.write_text(formatted_meta, encoding="utf-8")

        # Third deterministic write-in
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for src_path, arc_name in files_to_pack:
                z.write(src_path, arc_name)
        final_sha256 = compute_sha256(zip_path)
        final_download_size = zip_path.stat().st_size
        meta["versions"][0]["download_sha256"] = final_sha256
        meta["versions"][0]["download_size"] = final_download_size
        METADATA_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    log.info("[+] Final ZIP built successfully:")
    log.info(f"    Path:         {zip_path}")
    log.info(f"    SHA256:       {final_sha256}")
    log.info(f"    Download Size:{final_download_size} bytes")
    log.info(f"    Install Size: {install_size} bytes")

    # Step 3: Prepare upstream GitLab addons package tree
    identifier = meta["identifier"]
    gitlab_pkg_dir = DIST_DIR / "kicad-addons-repo" / "packages" / identifier
    gitlab_pkg_dir.mkdir(parents=True, exist_ok=True)
    (gitlab_pkg_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    log.info(f"[+] Upstream GitLab package tree ready at: {gitlab_pkg_dir}")

    return zip_path


def main():
    meta = validate_source_files()
    build_pcm_package(meta)


if __name__ == "__main__":
    main()
