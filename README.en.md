<div align="center">

  <img src="docs/images/brand-mark.png" alt="Wave Fixture AI" width="110">

  # WAVE FIXTURE AI

  **Gerber in · fixture drawings out · 21 automations · a CAD assistant that listens**

  **wave-fixture-ai turns wave-soldering fixture design from manual CAD drafting into one command: drop in PCB Gerber files and it auto-generates sink regions, handles, avoid zones, solder areas, screw holes, locating pins and the fixture outline — exporting DXF/STL/GLB with 3D preview, component interference analysis, and natural-language parameter adjustment.**

  <p>
    <a href="README.md">🇨🇳 中文</a>
    ·
    <a href="#-use-in-ci-github-action">🤖 GitHub Action</a>
    ·
    <a href="llms.txt">📄 llms.txt (AI Direct)</a>
    ·
    <a href="VALIDATION.md">🧪 Real-world Validation (16 defects)</a>
    ·
    <a href="#-api-endpoints">🔌 API</a>
    ·
    <a href="LICENSE">MIT</a>
  </p>

  <p>
    <a href="https://github.com/mo9652962-ai/wave-fixture-ai/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mo9652962-ai/wave-fixture-ai/ci.yml?style=flat-square&label=CI" alt="CI"></a>
    <img src="https://img.shields.io/badge/features-21%20automations-2563EB?style=flat-square" alt="features">
    <img src="https://img.shields.io/badge/DRC-47_Rules-059669?style=flat-square" alt="47 DRC rules">
    <img src="https://img.shields.io/badge/KiCad-10%20compatible-314CE0?style=flat-square&logo=kicad&logoColor=white" alt="KiCad 10">
    <img src="https://img.shields.io/badge/tests-296%20passed-success?style=flat-square" alt="tests">
    <img src="https://img.shields.io/badge/coverage-85%25-success?style=flat-square" alt="coverage">
    <a href="VALIDATION.md"><img src="https://img.shields.io/badge/real--world-16%20defects%20fixed-gold?style=flat-square" alt="16 defects fixed"></a>
    <a href="LICENSE"><img src="https://img.shields.io/github/license/mo9652962-ai/wave-fixture-ai?style=flat-square" alt="MIT"></a>
    <a href="https://securityscorecards.dev/viewer/?uri=github.com/mo9652962-ai/wave-fixture-ai"><img src="https://img.shields.io/ossf-scorecard/github.com/mo9652962-ai/wave-fixture-ai?style=flat-square&label=Scorecard" alt="Scorecard"></a>
  </p>
</div>

<div align="center">
  <img src="docs/images/banner-1200x630.png" alt="WAVE FIXTURE AI" width="100%">
</div>

## The 21 automations

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
| 13 | **Natural-language adjustment** (29 parameters) | ✅ |
| 14 | **DRC manufacturing safety gate** (47 rules · 4 severities · cited) | ✅ |
| 15 | **Golden sample regression** (IoU≥0.9 · Hausdorff≤0.5mm · circle best-match) | ✅ |
| 16 | **Human review loop** (missing-data gating → operator audit log) | ✅ |
| 17 | **Locating pin scoring** (diameter window / NPTH / edge distance) | ✅ |
| 18 | **Dogbone corner relief** (bisector toolpath · dogbone/T-bone/corner-hole · dedicated DXF layer) | ✅ |
| 19 | **Panelization** (N×M array per pallet · barrier-gap DRC · full geometry replication) | ✅ |
| 20 | **Material presets & cost estimation** (Durostone/Ricocel/FR-4/aluminum · weight & cost) | ✅ |
| 21 | **CNC G-code output + production job report** (drill/pocket/profile ops · .nc delivery) | ✅ |

## 🏭 Enterprise delivery (benchmarked against Macaos Solder Pallet Designer)

- **Panelization** — N×M copies per pallet with barrier-gap DRC (`panel_cols/rows/gap`)
- **Material presets** — Durostone (1.90 g/cm³, 280°C, ESD) / Ricocel / high-Tg FR-4 / aluminum,
  with blank-size snapping, weight and cost estimation (sources cited in `materials.py`)
- **CNC G-code (.nc)** — RS-274 (G21/G90/G54, tool changes, M30): grouped pin drilling,
  raster roughing + wall finishing pockets, helical bores, profile cuts; feeds/speeds per material
- **Production job report** — spec, materials & cost, CNC summary, DRC verdict,
  wave-soldering process window (lead-free 255–265°C pot, 4–8 s dwell), deliverables list
- **Batch jobs** — declarative YAML job spec (`batch_run.py`, KiBot-style): one command
  produces DXF + G-code + report for a whole batch, with a batch summary and per-job failure isolation

## 🚀 Quick start

```bash
pip install wave-fixture-ai
wave-fixture-ai --port 8000
# open http://localhost:8000 and drop your Gerber files
```

## 🤖 Use in CI (GitHub Action)

Automatically generate solder fixtures and enforce DRC manufacturing gates on PRs:

```yaml
name: drc
on: [pull_request, push]
jobs:
  fixture-drc:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: mo9652962-ai/wave-fixture-ai@main
        with:
          gerber-dir: gerber/
          severity-threshold: error
```

Outputs `fixture.dxf` (production ready, or watermarked with `PREVIEW` if gates fail) + `drc-report.json`.

## Command-line equivalents

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

## ⭐ Star History

If wave-fixture-ai helps your manufacturing or CAD workflow, consider giving the repo a star!

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=mo9652962-ai/wave-fixture-ai&type=Date)](https://star-history.com/#mo9652962-ai/wave-fixture-ai&Date)

</div>

## License

MIT
