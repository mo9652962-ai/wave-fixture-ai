<div align="center">

  <img src="docs/images/brand-mark.png" alt="Wave Fixture AI" width="110">

  # WAVE FIXTURE AI

  **Gerber in · fixture drawings out · 13 automations · a CAD assistant that listens**

  **wave-fixture-ai turns wave-soldering fixture design from manual CAD drafting into one command: drop in PCB Gerber files and it auto-generates sink regions, handles, avoid zones, solder areas, screw holes, locating pins and the fixture outline — exporting DXF/STL/GLB with 3D preview, component interference analysis, and natural-language parameter adjustment.**

  <p>
    <a href="README.md">🇨🇳 中文</a>
    ·
    <a href="#-api-endpoints">🔌 API</a>
    ·
    <a href="LICENSE">MIT</a>
  </p>

  <p>
    <a href="https://github.com/mo9652962-ai/wave-fixture-ai/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mo9652962-ai/wave-fixture-ai/ci.yml?style=flat-square&label=CI" alt="CI"></a>
    <img src="https://img.shields.io/badge/features-13-2563EB?style=flat-square" alt="features">
    <img src="https://img.shields.io/badge/KiCad-10%20compatible-314CE0?style=flat-square&logo=kicad&logoColor=white" alt="KiCad 10">
  </p>
</div>

<div align="center">
  <img src="docs/images/banner-1200x630.png" alt="WAVE FIXTURE AI" width="100%">
</div>

## The 13 automations

| Step | Feature | Status |
|:---|:---|:---|
| 1 | Gerber upload & parsing (KiCad 10 compatible) | ✅ gerbonara + regex fallback |
| 2 | Sink region (0.2mm outline expansion + R1.85 fillet) | ✅ |
| 3 | Handles (20×40mm both sides, 1mm overlap, R2 fillet) | ✅ |
| 4 | Snap-screw holes (Φ3.4, four corners, 10mm inset) | ✅ |
| 5 | Locating pins (DRL drills inset 0.1mm) | ✅ |
| 6 | Avoid zones (BOT+TOP SMD envelope + auto-merge) | ✅ ESP32-board tested |
| 7 | Solder areas (TOP through-hole pad envelope + R2) | ✅ |
| 8 | Cover-plate spring holes (silkscreen center Φ2.45) | ✅ |
| 9 | Fixture outline (integerized expansion + R5 + rail lines + tin bar) | ✅ |
| 10 | Fixture DXF export (8 layers) | ✅ |
| 11 | **3D preview** (STL/GLB export + in-browser viewer) | ✅ |
| 12 | **Interference analysis** (2D coverage + 3D boolean dual test) | ✅ |
| 13 | **Natural-language adjustment** (23 parameters) | ✅ |

## 🚀 Quick start

```bash
pip install -e .
wave-fixture-ai --port 8000
# open http://localhost:8000 and drop your Gerber files
```

Command-line equivalents:

```bash
python fixture_phase1.py <gerber_dir> -o output/fixture.dxf    # sink/handles/screws/pins
python fixture_phase2.py <gerber_dir> -o output/fixture-full.dxf  # full fixture
```

## 🔌 API endpoints

| Endpoint | Purpose |
|:---|:---|
| `POST /api/generate` | Upload Gerber → DXF + PNG |
| `POST /api/generate3d` | Upload Gerber → 3D fixture (STL + GLB) |
| `POST /api/adjust` | Natural-language adjustment → regenerate |
| `POST /api/interference` | Interference analysis (requires .kicad_pcb) |
| `GET /dl/{file}` | Download generated files |

## Interference analysis

Requires a **.kicad_pcb** file (Gerber carries pad geometry only, no component heights). Rule: a component is flagged when its box covers <85% of an avoid zone or overlaps the fixture 3D solid by >5mm³. Through-hole footprints (PinHeader/Connector/USB…) are skipped — the solder area handles them.

## Natural-language adjustment

Deterministic rule parsing (no LLM in the loop) — engineering parameters must be exact and reproducible:

```
避位区外扩1mm   → avoid_pad_extra: 0.3 → 1.3
盖板孔径改3mm    → cap_hole_r: 2.45 → 3.0
```

## Tech stack

**gerbonara** (Gerber/Excellon parsing) · **shapely** (geometry) · **ezdxf** (DXF) · **trimesh + manifold** (3D boolean) · **fastapi + uvicorn** · **three.js** (frontend 3D)

## License

MIT
