# Reddit Publication Posts: r/KiCad & r/PrintedCircuitBoard

This guide contains pre-composed, community-friendly technical posts for **Reddit**. Both posts adhere strictly to subreddit anti-spam and self-promotion guidelines (100% open source, MIT licensed, no paywall, no signup required).

---

## 1. Post for `r/KiCad`

### Post Title
`I built an open-source tool that turns KiCad PCB & Gerber files into wave soldering pallets (with 3D interference checking & CNC G-code)`

### Post Content (Markdown)

```markdown
Hi r/KiCad,

Whenever we have through-hole components (like connectors, relays, or terminal blocks) on a mixed-technology PCB, wave soldering or selective soldering is necessary. But drafting the wave soldering pallet (selective solder fixture) in AutoCAD or FreeCAD is typically a painful 3-to-4 hour process:

1. Offset the board outline for the pocket (and manually filleting concave corners for router bits).
2. Measure every bottom SMD part to cut avoid pockets.
3. Draw openings for through-hole leads with 60° wave chamfers.
4. Manually verify component heights so the pallet doesn't crush high-profile parts.
5. Export DXF, re-import into CAM software, and program CNC toolpaths.

To automate this entire headache, I built **[wave-fixture-ai](https://github.com/mo9652962-ai/wave-fixture-ai)** — an open-source (MIT) CAM engine that automates all 21 steps directly from your KiCad files in less than a second.

### What it does automatically:
- **KiCad 8/9/10 native parsing**: Directly reads your `.kicad_pcb` or Gerber zip to detect board edge cuts, drills, SMD avoid zones, and THT solder openings.
- **R1.85 Dogbone relief corners**: Automatically adds dogbone clearances to sharp inside corners so the rectangular PCB drops into the milled pocket without getting stuck on CNC cutter radius.
- **3D Digital Twin & Collision Check**: Reconstructs the board in 3D and runs volumetric mesh interference detection between bottom-side components (from KiCad 3D models) and the fixture pocket ceiling.
- **71 Industrial DRC Rules**: Checks APTPCB wall thickness limits (≥1.5mm), SMEMA conveyor track clearances (330/350mm), and Macaos aperture rules.
- **Direct Deliverables**: Outputs standard AutoCAD DXF, watertight 3D STL/GLB, RS-274 CNC G-code (`.nc`), and an IATF 16949 inspection report.

### Try it without installing anything:
I put together a zero-friction, static 3D web showcase running on GitHub Pages (built with Three.js). You can rotate the 3D model, inspect collision bounding boxes, and download the G-code:
👉 **Live 3D Demo**: https://mo9652962-ai.github.io/wave-fixture-ai/

### Local Offline CLI / Web:
If you want to run it locally on your own design files without anything touching the cloud:
```bash
uvx wave-fixture-ai
# or
pip install wave-fixture-ai && wave-fixture-ai
```

The repo currently has 367 automated unit tests covering geometric invariants, edge chain closures, and real PCB test boards. 

Source code: https://github.com/mo9652962-ai/wave-fixture-ai

I'd love to hear your feedback on CAM parameters, rule tolerances, or features you'd like to see next!
```

---

## 2. Post for `r/PrintedCircuitBoard`

### Post Title
`Open-source DFM/CAM: Automating Wave Soldering Pallet Design, Solder Dams, and CNC G-Code Generation`

### Post Content (Markdown)

```markdown
Hi everyone,

Wave soldering pallets are one of those manufacturing assets that every PCBA production line needs, yet almost everyone still designs manually in 2D CAD or pays €1,500/year for proprietary tools like Macaos Solder Pallet Designer.

Over the past few weeks, I developed **wave-fixture-ai**, a fully open-source CAM engine implementing 21 core manufacturing automations and 71 DRC validation rules for wave soldering fixtures.

Here are the key engineering challenges we solved algorithmically with Python, Shapely 2.0, and Manifold3D:

### 1. The Inside Corner Routing Paradox (Dogbone Reliefs)
Standard endmills (e.g. Ø3.0mm or Ø1.85mm) cannot machine a sharp 90° inside pocket corner, leaving an uncut radius that prevents the rectangular PCB from seating flush. We implemented automated dogbone reliefs along the exterior angle bisector ($\Delta = R \cdot (1/\sin(\theta/2) - 1) + clearance$), outputting dedicated DXF layers and CNC cutter sequences.

### 2. Wave Dynamics & Dross Mitigation
- **60° Inflow Chamfers**: Slanted chamfers on the leading edge prevent turbulent liquid solder waves from washing over the top of the pallet.
- **Dross Skimmer Dams**: 8mm wide transverse skimming slots that capture floating solder dross before it enters component through-hole apertures.
- **Titanium Knife Inserts**: Thin isolation walls (<1.8mm) between adjacent SMD avoid zones and solder waves erode quickly under 260°C SAC305 solder wash. The engine flags these and designs slots for M2-fastened 0.8mm Grade 2 titanium insert blades.

### 3. Archimedes Buoyancy & Clamp Force
Molten SAC305 solder has a density of ~7.4 g/cm³. When an unpopulated or lightweight PCB enters the wave, solder buoyancy forces the board upward, causing solder bleed. The engine calculates net upward buoyancy and automatically places spring-loaded rotary clamp fingers along the edges.

### 4. 71 Industrial DRC Rules Engine
The engine includes a non-blocking/blocking manufacturing gate evaluating rules derived from APTPCB, IPC-SMEMA-9851, and empirical assembly guidelines. If blocking errors are detected (e.g. wall thickness <1.2mm or conveyor track mismatch), output drawings are watermarked as PREVIEW ONLY to prevent shop-floor tool crashes.

---

### Links & Resources:
- **GitHub Repository**: https://github.com/mo9652962-ai/wave-fixture-ai (MIT License, 367 tests passed, 85% coverage ratchet)
- **Interactive 3D Web Showcase**: https://mo9652962-ai.github.io/wave-fixture-ai/
- **Run locally**: `uvx wave-fixture-ai`

Would love to discuss CAM rules, CNC cutting feed rates for Durostone/Ricocel, and any edge-case PCB geometries you've encountered!
```

---

## 3. Best Practices for Comment Engagement
1. **Be transparent**: Explicitly mention that you are the author and that the project is 100% free and open-source under MIT.
2. **Prioritize technical depth**: When commenters ask about specific materials (Durostone vs FR-4 vs Aluminum), quote the exact CTE numbers ($22 \times 10^{-6}/\text{K}$ for Durostone vs $15 \times 10^{-6}/\text{K}$ for FR-4) and thermal expansion clearance calculations ($L \cdot \Delta CTE \cdot \Delta T$).
3. **No aggressive upvote begging**: Let the utility and the live 3D showcase speak for itself.
