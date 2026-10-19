# Awesome-KiCad Pull Request Proposal

This document provides ready-to-submit PR materials for adding `wave-fixture-ai` to curated Awesome KiCad lists, notably:
- Upstream 1: [heitorPB/awesome-kicad](https://github.com/heitorPB/awesome-kicad)
- Upstream 2: [salfter/Awesome-KiCad](https://github.com/salfter/Awesome-KiCad)

---

## 1. PR Title
`Add wave-fixture-ai to Manufacturing / CAM Tools`

---

## 2. PR Description (Markdown)

```markdown
### Summary
Add **[wave-fixture-ai](https://github.com/mo9652962-ai/wave-fixture-ai)** under the **Manufacturing / Fabrication / CAM** section.

### About wave-fixture-ai
`wave-fixture-ai` is an open-source, automated wave soldering pallet (selective solder fixture) CAM engine designed for PCB manufacturing. It takes KiCad 8/9/10 PCB layouts and Gerber RS-274X files and instantly generates production-grade fixture CAD and CNC G-code.

- **License**: MIT
- **KiCad Compatibility**: Compatible with KiCad 7, 8, 9, and 10 `.kicad_pcb` formats and raw Gerbers.
- **Key Features**:
  - 21 automated CAM operations: pocket expansion (0.2mm + R1.85 dogbone reliefs), 60° wave chamfers, solder dam dross skimmers, titanium knife inserts, and push-latch clamp holes.
  - 3D watertight mesh export (STL/GLB) with component collision interference detection against board elements.
  - 71 industrial DRC manufacturing rules (APTPCB, Macaos, IPC-SMEMA-9851) preventing tool breakage and solder bridging.
  - Direct RS-274 CNC G-code toolpaths and IATF 16949 / ISO 9001 workshop inspection checklists.
  - Zero-friction live 3D web preview: https://mo9652962-ai.github.io/wave-fixture-ai/
- **Test Suite**: 367 automated tests passing on both Ubuntu and Windows with 85% coverage ratchet.
- **Install**: `pip install wave-fixture-ai` or run instantly with `uvx wave-fixture-ai`.

Thank you for curating this awesome community resource!
```

---

## 3. Markdown Diff to Apply in `README.md`

Locate the `### Fabrication and Assembly / CAM` or `### Manufacturing` category in `README.md` and insert:

```markdown
* [wave-fixture-ai](https://github.com/mo9652962-ai/wave-fixture-ai) - Automated wave soldering pallet and selective soldering fixture CAM engine. Takes KiCad PCB / Gerber files and outputs DXF blueprints, watertight 3D STL/GLB models, 71 DRC validation rules, and CNC RS-274 G-code toolpaths. Includes a zero-friction live 3D demo.
```
