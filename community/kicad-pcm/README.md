# KiCad PCM (Plugin and Content Manager) Integration

This directory contains the official KiCad Plugin and Content Manager (PCM) package definition for **Wave Fixture AI**.

---

## 1. Directory Structure

```text
kicad-pcm/
├── metadata.json              # Official KiCad PCM metadata specification
├── README.md                  # Installation and submission guide
└── plugins/
    ├── __init__.py
    ├── icon.png               # 64x64 Toolbar Icon
    └── action_wave_fixture.py # KiCad PCB Editor Action Plugin
```

---

## 2. Manual Local Installation for Testing

To test this plugin locally in KiCad:

### Windows:
Copy the `plugins/` directory to:
`%APPDATA%\kicad\8.0\scripting\plugins\wave_fixture_ai\` (or `9.0` / `10.0`)

### Linux:
Copy the `plugins/` directory to:
`~/.local/share/kicad/8.0/scripting/plugins/wave_fixture_ai/`

### macOS:
Copy the `plugins/` directory to:
`~/Library/Preferences/kicad/8.0/scripting/plugins/wave_fixture_ai/`

After copying:
1. Open KiCad PCB Editor (`pcbnew`).
2. Go to **Tools → External Plugins → Refresh Plugins**.
3. You will see the **Wave Fixture AI** icon in the top action plugin toolbar. Clicking it launches the 3D fixture viewer.

---

## 3. Submitting to Official KiCad Addons Repository

1. Zip the package according to KiCad PCM conventions:
   ```bash
   zip -r wave-fixture-ai-kicad-pcm.zip metadata.json plugins/
   ```
2. Compute the SHA256 checksum:
   ```bash
   sha256sum wave-fixture-ai-kicad-pcm.zip
   ```
3. Update `download_sha256` and `download_size` in `metadata.json`.
4. Fork [kicad/kicad-addons](https://gitlab.com/kicad/addons/metadata) on GitLab and submit a merge request adding `packages/wave-fixture-ai/`.
