# AGENTS.md — Project Orientation for AI Coding Agents

> Guidance for AI coding agents (Claude Code, Cursor, Codex, Hermes) working on WaveFixture AI.

## Project Overview

WaveFixture AI is an open-source, automated wave-soldering pallet (fixture) design system and CAD assistant. It ingests PCB Gerber RS-274X files and exports production-grade DXF engineering drawings, 3D solids (STL/GLB), and CNC G-code with 26 DRC production safety gates and deterministic natural-language parameter adjustment.

## Toolchain & Verification

- **Runtime**: Python 3.10+ (Dependencies managed via `pyproject.toml` / `uv.lock`)
- **Test Runner**: `pytest tests/ -q` (232 tests passing)
- **Doc Consistency Guard**: `pytest tests/test_doc_consistency.py -q` (Strictly guards DRC count [26], parameter count [28], and material presets)
- **CAD & Geometry Libraries**: `gerbonara` (Gerber parsing), `shapely` (2D boolean), `ezdxf` (DXF export), `trimesh` + `manifold` (3D solid generation)

## Core Architecture

| Module | Purpose |
|:---|:---|
| `fixture_phase1.py` | Generates sink regions, handles, screws, and locating pins |
| `fixture_phase2.py` | Generates full fixture body, avoid zones, and solder windows |
| `drc.py` | 26 production safety gates with severity levels & source standards |
| `nl_adjust.py` | Deterministic regex lexer for 28 natural language adjustment parameters |
| `cnc_gcode.py` | Automated CNC G-code toolpath generation (.nc) & Markdown production reports |
| `web_server.py` | FastAPI server exposing web UI and REST API |

## Non-Negotiable Constraints

1. **Doc Consistency Invariant**: Any change to DRC rule codes in `drc.py` or parameter aliases in `nl_adjust.py` MUST be synced with `README.md`, `README.en.md`, and `llms.txt`. Never change one without the others.
2. **Deterministic Geometry**: Wave soldering tolerances are sub-millimeter (e.g. 0.2mm expansion, R1.85 corner relief). Do not introduce fuzzy or heuristic approximations without running Golden Sample regressions.
3. **No External Cloud Storage**: Pallet designs and Gerber files must remain local. No telemetry or cloud uploads.
