"""MCP server for Wave Fixture AI (stdio transport).

Exposes the repository's core wave-soldering fixture capabilities as Model
Context Protocol tools: Gerber analysis and fixture generation with the DRC
gate, dogbone corner relief, wave-flow chamfers, thermal expansion checks,
quotation, process windows and wave-line process checks.

Run with ``wave-fixture-ai-mcp`` (installed script) or ``python mcp_server.py``.

Startup stays fast and dependency-light on purpose: only the MCP SDK and
pydantic are imported at module load. Every geometry / CAD module (shapely,
ezdxf, gerbonara, ...) is imported inside the tool that needs it, so the
server always answers ``initialize`` and ``tools/list`` even if an optional
heavy dependency is missing or slow to import.

Works with both MCP Python SDK lines: v1 (``FastMCP``) and v2 (``MCPServer``,
the renamed FastMCP).
"""

from __future__ import annotations

import inspect
import json
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field

try:  # MCP Python SDK v2: FastMCP was renamed to MCPServer
    from mcp.server.mcpserver import MCPServer as _ServerClass
except ImportError:  # MCP Python SDK v1
    from mcp.server.fastmcp import FastMCP as _ServerClass

try:
    from mcp.types import ToolAnnotations
except ImportError:  # very old SDKs without tool annotations
    ToolAnnotations = None  # type: ignore[assignment,misc]

SERVER_NAME = "wave-fixture-ai"

INSTRUCTIONS = (
    "Wave Fixture AI: design and check wave-soldering fixtures (selective solder pallets). "
    "Start with analyze_gerber_board on a Gerber directory, then generate_fixture_from_gerber "
    "to produce the fixture DXF, DRC gate report and optional CNC G-code. The geometry and "
    "process tools (dogbone relief, wave-flow chamfers, thermal expansion, preheat, dross/"
    "bridging, quotation) work from plain numbers and need no files. All lengths are in mm."
)



def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("wave-fixture-ai")
    except Exception:
        return "0.0.0"


_server_kwargs: dict[str, Any] = {"instructions": INSTRUCTIONS}
if "version" in inspect.signature(_ServerClass.__init__).parameters:  # SDK v2
    _server_kwargs["version"] = _package_version()
mcp = _ServerClass(SERVER_NAME, **_server_kwargs)

_TOOL_SUPPORTS_ANNOTATIONS = "annotations" in inspect.signature(mcp.tool).parameters


def _tool(title: str, *, read_only: bool, idempotent: bool = True, destructive: bool = False):
    """Register a tool with MCP annotations when the installed SDK supports them."""
    kwargs: dict[str, Any] = {}
    if ToolAnnotations is not None and _TOOL_SUPPORTS_ANNOTATIONS:
        kwargs["annotations"] = ToolAnnotations(
            title=title,
            readOnlyHint=read_only,
            destructiveHint=destructive,
            idempotentHint=idempotent,
            openWorldHint=False,
        )
    return mcp.tool(**kwargs)


MaterialKey = Literal["durostone", "ricocel", "fr4_high_tg", "aluminum"]

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _gerber_dir(path: str) -> Path:
    d = Path(path).expanduser().resolve()
    if not d.is_dir():
        raise ValueError(f"gerber_dir is not an existing directory: {d}")
    return d


def _polygon(points: list[list[float]]):
    from shapely.geometry import Polygon

    if len(points) < 3:
        raise ValueError("a polygon needs at least 3 [x, y] vertices")
    for p in points:
        if len(p) != 2:
            raise ValueError(f"each vertex must be [x, y], got {p!r}")
    poly = Polygon([(float(x), float(y)) for x, y in points])
    if poly.is_empty or poly.area <= 0:
        raise ValueError("polygon has zero area")
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly


def _bounds(poly) -> dict[str, float] | None:
    if poly is None or getattr(poly, "is_empty", True):
        return None
    minx, miny, maxx, maxy = poly.bounds
    return {
        "min_x": round(minx, 3),
        "min_y": round(miny, 3),
        "max_x": round(maxx, 3),
        "max_y": round(maxy, 3),
        "width_mm": round(maxx - minx, 3),
        "height_mm": round(maxy - miny, 3),
    }


# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #


@_tool("List fixture materials and wave machines", read_only=True)
def list_fixture_materials() -> dict[str, Any]:
    """List the built-in fixture material presets (Durostone, Ricocel, high-Tg FR-4,
    aluminum 6061) with density, max service temperature, sheet thicknesses, reference
    price and recommended CNC cutting parameters, plus the wave-soldering machine
    profiles (rail width range, conveyor load) used by the DRC gate."""
    from equipment import MACHINES
    from materials import DEFAULT_MATERIAL, MATERIALS

    return {
        "default_material": DEFAULT_MATERIAL,
        "materials": [m.to_dict() for m in MATERIALS.values()],
        "machines": [m.to_dict() for m in MACHINES.values()],
    }


@_tool("Get wave soldering process window", read_only=True)
def get_wave_process_window(
    solder: Annotated[
        Literal["lead_free", "leaded"],
        Field(description="Solder type: 'lead_free' (SAC305) or 'leaded' (Sn63/Pb37)."),
    ] = "lead_free",
    material: Annotated[
        MaterialKey | None,
        Field(description="Optional fixture material key to cross-check its max service "
                          "temperature against the lead-free solder pot window."),
    ] = None,
) -> dict[str, Any]:
    """Return the recommended wave-soldering process window for a solder type: pot
    temperature, preheat temperature and time, wave dwell time, ramp rate and peak
    limits, with the source. Optionally checks whether a fixture material survives
    the lead-free pot temperature."""
    from process import get_process, material_process_compat

    result: dict[str, Any] = {"process": get_process(solder).to_dict()}
    if material:
        from materials import get_material

        mat = get_material(material)
        ok, msg = material_process_compat(mat.max_service_temp_c)
        result["material_check"] = {
            "material": mat.key,
            "max_service_temp_c": mat.max_service_temp_c,
            "compatible_with_lead_free": ok,
            "message": msg,
        }
    return result


# --------------------------------------------------------------------------- #
# Geometry tools (no files)
# --------------------------------------------------------------------------- #


@_tool("Dogbone corner relief for a board pocket", read_only=True)
def compute_dogbone_relief(
    outline: Annotated[
        list[list[float]],
        Field(description="PCB outline as a list of [x, y] vertices in mm (closed "
                          "automatically), e.g. [[0,0],[100,0],[100,60],[0,60]]."),
    ],
    pocket_clearance_mm: Annotated[
        float, Field(ge=0, le=5, description="Pocket clearance added around the board, per side (mm).")
    ] = 0.2,
    cutter_radius_mm: Annotated[
        float, Field(gt=0, le=10, description="End-mill radius used to clear the corners (mm).")
    ] = 1.85,
    style: Annotated[
        Literal["dogbone", "corner_hole", "tbone"],
        Field(description="Corner relief style."),
    ] = "dogbone",
) -> dict[str, Any]:
    """Compute dogbone (corner relief) cuts so a rectangular-cornered PCB drops fully
    into a CNC-milled fixture pocket. Detects the sharp board corners a round end mill
    cannot reach, returns each relief's cutter center, angle and lead-in line, and the
    resulting pocket size and area. Pure geometry: writes no files."""
    from dogbone import DogboneParams, generate_dogbone_relief

    board = _polygon(outline)
    params = DogboneParams(cutter_r=cutter_radius_mm, style=style)
    pocket, corners = generate_dogbone_relief(board, expand_mm=pocket_clearance_mm, params=params)
    return {
        "corner_count": len(corners),
        "corners": [c.to_dict() for c in corners],
        "board_area_mm2": round(board.area, 2),
        "pocket_area_mm2": round(pocket.area, 2),
        "pocket_bounds": _bounds(pocket),
    }


@_tool("Wave-flow chamfers for solder openings", read_only=True)
def design_wave_flow_chamfers(
    openings: Annotated[
        list[list[float]],
        Field(description="Solder openings on the pallet bottom as rectangles "
                          "[min_x, min_y, max_x, max_y] in mm."),
    ],
    pallet_thickness_mm: Annotated[
        float, Field(gt=0, le=50, description="Total fixture (pallet) thickness (mm).")
    ] = 10.0,
    board_pocket_depth_mm: Annotated[
        float, Field(ge=0, le=20, description="Depth of the board pocket on the top side (mm).")
    ] = 2.1,
    chamfer_angle_deg: Annotated[
        float, Field(ge=30, le=75, description="Chamfer angle, usually 60 (standard) or 45.")
    ] = 60.0,
    chamfer_width_mm: Annotated[
        float, Field(gt=0, le=10, description="Horizontal width of the bottom chamfer (mm).")
    ] = 2.0,
    conveyor_flow_direction: Annotated[
        Literal["X+", "X-", "Y+", "Y-"],
        Field(description="Board travel direction over the wave; the trailing edge gets the solder thief."),
    ] = "X+",
    solder_thief: Annotated[
        bool, Field(description="Add a solder-thief relief on the trailing edge to reduce bridging.")
    ] = True,
) -> dict[str, Any]:
    """Design bottom-side wave-flow chamfers (60 or 45 degree) and trailing-edge solder
    thieves for each solder opening of a wave pallet, and flag openings whose depth-to-
    width aspect ratio exceeds 1.2 (solder may not fill the hole). Pure geometry."""
    from shapely.geometry import box

    from wave_chamfer import ChamferParams, generate_wave_flow_chamfers

    polys = []
    for r in openings:
        if len(r) != 4:
            raise ValueError(f"each opening must be [min_x, min_y, max_x, max_y], got {r!r}")
        x0, y0, x1, y1 = (float(v) for v in r)
        if x1 <= x0 or y1 <= y0:
            raise ValueError(f"opening has non-positive size: {r!r}")
        polys.append(box(x0, y0, x1, y1))
    params = ChamferParams(
        chamfer_angle_deg=chamfer_angle_deg,
        chamfer_width_mm=chamfer_width_mm,
        enable_solder_thief=solder_thief,
        conveyor_flow_direction=conveyor_flow_direction,
    )
    chamfers = generate_wave_flow_chamfers(
        polys,
        pallet_thickness_mm=pallet_thickness_mm,
        board_pocket_depth_mm=board_pocket_depth_mm,
        params=params,
    )
    items = []
    for c in chamfers:
        d = c.to_dict()
        d["aspect_ratio_ok"] = c.aspect_ratio <= 1.2
        d["chamfer_bounds"] = _bounds(c.chamfer_poly)
        items.append(d)
    return {
        "opening_count": len(items),
        "hole_depth_mm": round(max(pallet_thickness_mm - board_pocket_depth_mm, 1.0), 3),
        "high_aspect_ratio_openings": [i["index"] for i in items if not i["aspect_ratio_ok"]],
        "chamfers": items,
    }


@_tool("Thermal expansion clearance check", read_only=True)
def check_thermal_expansion_gap(
    pallet_length_mm: Annotated[float, Field(gt=0, description="Fixture length along the checked axis (mm).")],
    pcb_length_mm: Annotated[
        float | None,
        Field(gt=0, description="PCB length along the same axis (mm). Defaults to 92% of the pallet length."),
    ] = None,
    material: Annotated[MaterialKey, Field(description="Fixture material key.")] = "durostone",
    delta_t_c: Annotated[
        float, Field(gt=0, le=400, description="Temperature rise from room temperature to the wave (°C).")
    ] = 235.0,
    design_clearance_mm: Annotated[
        float, Field(gt=0, le=5, description="Room-temperature pocket clearance per side (mm).")
    ] = 0.2,
) -> dict[str, Any]:
    """Check whether differential thermal expansion between the fixture and the FR-4
    PCB at wave temperature eats the room-temperature pocket clearance (board jamming
    or pinching risk). Returns both expansions, the differential and the share of the
    clearance consumed."""
    from thermal_expansion import compute_expansion_gap

    return compute_expansion_gap(
        pallet_len_mm=pallet_length_mm,
        pcb_len_mm=pcb_length_mm,
        material_key=material,
        delta_t_c=delta_t_c,
        design_clearance_mm=design_clearance_mm,
    ).to_dict()


# --------------------------------------------------------------------------- #
# Cost
# --------------------------------------------------------------------------- #


@_tool("Fixture quotation and material cost", read_only=True)
def estimate_fixture_quotation(
    pallet_width_mm: Annotated[float, Field(gt=0, le=2000, description="Fixture blank width (mm).")],
    pallet_height_mm: Annotated[float, Field(gt=0, le=2000, description="Fixture blank height (mm).")],
    pallet_thickness_mm: Annotated[float, Field(gt=0, le=50, description="Fixture thickness (mm).")] = 10.0,
    material: Annotated[MaterialKey, Field(description="Fixture material key.")] = "durostone",
    quantity: Annotated[int, Field(ge=1, le=10000, description="Number of fixtures ordered.")] = 1,
    machining_minutes: Annotated[
        float, Field(ge=0, description="CNC machining time per fixture (min), e.g. from the G-code estimate.")
    ] = 0.0,
    screws_m3x16: Annotated[int, Field(ge=0, description="M3x16 screws per fixture.")] = 0,
    locating_pins: Annotated[int, Field(ge=0, description="Hardened Φ3 locating pins per fixture.")] = 0,
    turn_lock_clamps: Annotated[int, Field(ge=0, description="Spring turn-lock clamps per fixture.")] = 0,
    brass_inserts_m3: Annotated[int, Field(ge=0, description="M3 brass threaded inserts per fixture.")] = 0,
    machine_hourly_rate_cny: Annotated[
        float, Field(gt=0, description="CNC machine hourly rate (CNY/h).")
    ] = 120.0,
    margin_factor: Annotated[
        float, Field(ge=1, le=5, description="Gross margin multiplier applied to cost.")
    ] = 1.35,
) -> dict[str, Any]:
    """Estimate a production quotation for wave fixtures: nests blanks on a standard
    1020x1220 mm sheet, then sums material, CNC machining and hardware BOM cost and
    applies quantity discount tiers and margin. Prices are reference values in CNY,
    not a binding quote. Includes a Markdown quotation table."""
    from quotation import estimate_quotation

    hw = {
        "screw_m3x16": screws_m3x16,
        "locating_pin_d3": locating_pins,
        "turn_lock_clamp": turn_lock_clamps,
        "brass_insert_m3": brass_inserts_m3,
    }
    q = estimate_quotation(
        material_key=material,
        pallet_w_mm=pallet_width_mm,
        pallet_h_mm=pallet_height_mm,
        pallet_thickness_mm=pallet_thickness_mm,
        machining_time_min=machining_minutes,
        hardware_counts={k: v for k, v in hw.items() if v},
        quantity=quantity,
        machine_hourly_rate_cny=machine_hourly_rate_cny,
        margin_factor=margin_factor,
    )
    d = q.to_dict()
    d["currency"] = "CNY"
    d["markdown"] = q.markdown
    return d


# --------------------------------------------------------------------------- #
# Wave line process checks
# --------------------------------------------------------------------------- #


@_tool("Preheat profile compliance check", read_only=True)
def check_preheat_profile(
    preheat_length_m: Annotated[float, Field(gt=0, le=10, description="Total preheat zone length (m).")] = 1.8,
    conveyor_speed_m_per_min: Annotated[float, Field(gt=0, le=5, description="Conveyor speed (m/min).")] = 1.2,
    zone1_temp_c: Annotated[float, Field(ge=0, le=400, description="Preheat zone 1 set temperature (°C).")] = 110.0,
    zone2_temp_c: Annotated[float, Field(ge=0, le=400, description="Preheat zone 2 set temperature (°C).")] = 140.0,
    ambient_temp_c: Annotated[float, Field(ge=-20, le=60, description="Board entry temperature (°C).")] = 25.0,
    measured_exit_temp_c: Annotated[
        float | None, Field(description="Optional measured board exit temperature from a profiler (°C).")
    ] = None,
    soak_time_s: Annotated[float | None, Field(ge=0, description="Optional measured soak time (s).")] = None,
    flux_type: Annotated[
        Literal["no_clean", "water_based", "rosin"], Field(description="Flux chemistry.")
    ] = "no_clean",
    wave_temp_c: Annotated[float, Field(ge=180, le=320, description="Solder wave temperature (°C).")] = 255.0,
) -> dict[str, Any]:
    """Check a wave-solder preheat setup against IPC J-STD-001 / SMTA windows: ramp
    rate, board exit temperature, soak time and thermal shock at wave entry. Returns
    each check with violations and corrective actions."""
    from preheat_profile import check_preheat_profile as _check

    return _check(
        preheat_length_m=preheat_length_m,
        conveyor_speed_m_per_min=conveyor_speed_m_per_min,
        preheat_zone1_temp_c=zone1_temp_c,
        preheat_zone2_temp_c=zone2_temp_c,
        ambient_temp_c=ambient_temp_c,
        measured_exit_temp_c=measured_exit_temp_c,
        soak_time_s=soak_time_s,
        flux_type=flux_type,
        wave_temp_c=wave_temp_c,
    ).to_dict()


@_tool("Dross and solder bridging risk prediction", read_only=True)
def predict_dross_bridging(
    pocket_area_mm2: Annotated[float, Field(gt=0, description="Board pocket (sink) area (mm²).")] = 5000.0,
    solder_openings_area_mm2: Annotated[
        float, Field(ge=0, description="Total exposed solder opening area (mm²).")
    ] = 2500.0,
    min_pin_gap_mm: Annotated[float, Field(gt=0, description="Smallest pin-to-pin gap (mm).")] = 1.2,
    peel_off_angle_deg: Annotated[
        float, Field(ge=0, le=45, description="Peel-off angle at wave exit (°).")
    ] = 4.5,
    nitrogen: Annotated[bool, Field(description="Whether the wave runs under nitrogen.")] = True,
    wave_type: Annotated[
        Literal["laminar", "turbulent"], Field(description="Wave type: laminar or turbulent (chip wave).")
    ] = "laminar",
    pot_capacity_kg: Annotated[float, Field(gt=0, description="Solder pot capacity (kg).")] = 300.0,
) -> dict[str, Any]:
    """Predict dross generation rate, solder bridging risk and icicle risk for a wave
    pallet from its exposed opening area, pin pitch, peel-off angle and wave setup,
    with a risk level and corrective actions."""
    from dross_bridging_predictor import predict_dross_bridging as _predict

    return _predict(
        sink_area_mm2=pocket_area_mm2,
        solder_openings_area_mm2=solder_openings_area_mm2,
        min_pin_gap_mm=min_pin_gap_mm,
        peel_off_angle_deg=peel_off_angle_deg,
        has_nitrogen=nitrogen,
        wave_type=wave_type,
        pot_capacity_kg=pot_capacity_kg,
    ).to_dict()


# --------------------------------------------------------------------------- #
# Gerber pipeline
# --------------------------------------------------------------------------- #


@_tool("Analyze a Gerber board", read_only=True)
def analyze_gerber_board(
    gerber_dir: Annotated[
        str,
        Field(description="Path to a local directory with the board's Gerber/Excellon files "
                          "(needs an outline layer: Edge_Cuts / GM1 / GKO)."),
    ],
) -> dict[str, Any]:
    """Parse a Gerber directory and summarize the board for fixture design: outline
    size and area, drill count and diameters, the pocket size with default clearance,
    and the best diagonal pair of locating-pin holes. Reads files only."""
    from shapely.ops import unary_union

    from fixture_phase1 import FixtureParams, make_pins, make_sink_region, parse_gerber

    d = _gerber_dir(gerber_dir)
    board_polys, drills = parse_gerber(str(d))
    if not board_polys:
        return {"ok": False, "gerber_dir": str(d),
                "message": "No board outline layer found (Edge_Cuts / GM1 / GKO)."}
    board = unary_union(board_polys)
    p1 = FixtureParams()
    sink, corners = make_sink_region(board, p1, return_corners=True)
    pins = make_pins(drills, p1, sink_poly=sink)
    diameters: dict[str, int] = {}
    for _x, _y, dia in drills:
        key = f"{dia:.2f}"
        diameters[key] = diameters.get(key, 0) + 1
    return {
        "ok": True,
        "gerber_dir": str(d),
        "board_bounds": _bounds(board),
        "board_area_mm2": round(board.area, 2),
        "drill_count": len(drills),
        "drill_diameters_mm": dict(sorted(diameters.items(), key=lambda kv: float(kv[0]))),
        "pocket_bounds": _bounds(sink),
        "dogbone_corner_count": len(corners),
        "locating_pins": [{"x": round(x, 3), "y": round(y, 3), "radius_mm": round(r, 3)}
                          for x, y, r in pins],
    }


@_tool("Generate fixture DXF, DRC report and G-code", read_only=False, idempotent=True)
def generate_fixture_from_gerber(
    gerber_dir: Annotated[
        str, Field(description="Path to a local directory with the board's Gerber/Excellon files.")
    ],
    output_dir: Annotated[
        str | None,
        Field(description="Directory to write fixture.dxf, drc-report.json and fixture.nc into. "
                          "Created if missing; defaults to a new temporary directory."),
    ] = None,
    material: Annotated[MaterialKey, Field(description="Fixture material key.")] = "durostone",
    machine: Annotated[
        str | None,
        Field(description="Optional wave machine key for rail/load checks (see list_fixture_materials)."),
    ] = None,
    pallet_thickness_mm: Annotated[float, Field(gt=0, le=50, description="Fixture thickness (mm).")] = 10.0,
    board_thickness_mm: Annotated[float, Field(gt=0, le=10, description="PCB thickness (mm).")] = 1.6,
    severity_threshold: Annotated[
        Literal["info", "warning", "error", "blocking"],
        Field(description="Lowest DRC severity that makes the gate verdict FAIL."),
    ] = "error",
    include_gcode: Annotated[bool, Field(description="Also generate CNC G-code (fixture.nc).")] = True,
) -> dict[str, Any]:
    """Run the full fixture pipeline on a Gerber directory: board pocket with dogbone
    relief, handles, clamps, locating pins, component avoidance and solder openings,
    exported as a DXF drawing; then the DRC production gate (PASS/FAIL with every
    finding and its source) and optionally CNC G-code with a machining-time estimate.
    Writes files only inside output_dir."""
    from types import SimpleNamespace

    from shapely.ops import unary_union

    import drc
    from fixture_phase1 import (
        FixtureParams,
        make_handles,
        make_pins,
        make_screws,
        make_sink_region,
        parse_gerber,
    )
    from fixture_phase2 import run_phase2

    d = _gerber_dir(gerber_dir)
    out = Path(output_dir).expanduser().resolve() if output_dir else Path(
        tempfile.mkdtemp(prefix="wave-fixture-"))
    out.mkdir(parents=True, exist_ok=True)

    board_polys, drills = parse_gerber(str(d))
    if not board_polys:
        return {"verdict": "INPUT_ERROR", "gerber_dir": str(d),
                "message": "No board outline layer found (Edge_Cuts / GM1 / GKO)."}
    board = unary_union(board_polys)
    p1 = FixtureParams()
    sink, corners = make_sink_region(board, p1, return_corners=True)
    r1 = SimpleNamespace(
        board_poly=board,
        sink_poly=sink,
        handles=make_handles(sink, p1),
        screws=make_screws(sink, p1),
        pins=make_pins(drills, p1, sink_poly=sink),
        dogbone_corners=corners,
    )
    dxf_path = out / "fixture.dxf"
    r2 = run_phase2(str(d), str(dxf_path))
    if r2 is None:
        return {"verdict": "INPUT_ERROR", "gerber_dir": str(d),
                "message": "Fixture generation failed (outline missing or unparsable)."}

    issues = drc.run_drc(
        r1, r2, material_key=material, machine_key=machine or None,
        pallet_thickness=pallet_thickness_mm,
    )
    gate = drc.gate(issues)
    order = {"info": 0, "warning": 1, "error": 2, "blocking": 3}
    threshold = order[severity_threshold]
    verdict = "FAIL" if any(order.get(i["severity"], 0) >= threshold for i in issues) else "PASS"

    files = {"dxf": str(dxf_path)}
    gcode_stats = None
    if include_gcode:
        from cnc_gcode import generate_gcode

        gcode_path = out / "fixture.nc"
        gcode_stats = generate_gcode(
            r2.sink_poly, r2.avoid_polys, r2.solder_polys, r2.cap_holes,
            r1.pins, r1.handles, r2.outer_poly, str(gcode_path),
            material_key=material,
            pallet_thickness=pallet_thickness_mm,
            board_thickness=board_thickness_mm,
            vent_holes=getattr(r2, "vent_holes", []),
            job_name=d.name,
            parent_hint=out,
        )
        files["gcode"] = str(gcode_path)

    report = {
        "verdict": verdict,
        "threshold": severity_threshold,
        "gate": gate,
        "issues": issues,
        "material": material,
        "machine": machine,
    }
    report_path = out / "drc-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                           encoding="utf-8")
    files["drc_report"] = str(report_path)

    return {
        "verdict": verdict,
        "threshold": severity_threshold,
        "production_allowed": gate.get("allowed"),
        "counts": gate.get("counts"),
        "issue_count": len(issues),
        "issues": issues[:30],
        "issues_truncated": len(issues) > 30,
        "outer_bounds": _bounds(getattr(r2, "outer_poly", None)),
        "stats": {
            "avoid_count": len(getattr(r2, "avoid_polys", []) or []),
            "solder_opening_count": len(getattr(r2, "solder_polys", []) or []),
            "vent_hole_count": len(getattr(r2, "vent_holes", []) or []),
            "locating_pin_count": len(r1.pins),
            "dogbone_corner_count": len(corners),
        },
        "gcode": gcode_stats,
        "files": files,
        "output_dir": str(out),
    }


def main() -> None:
    """Console entry point: serve the MCP tools over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
