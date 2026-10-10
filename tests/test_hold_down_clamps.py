"""Tests for hold-down clamps layout, solder buoyancy calculation, and DRC 46-47."""

from types import SimpleNamespace

import ezdxf
from shapely.geometry import box

from drc import run_drc
from fixture_phase2 import Phase2Result
from hold_down_clamps import (
    calculate_solder_buoyancy_force,
    export_hold_down_clamps_to_dxf,
    generate_hold_down_clamps,
)


def test_calculate_solder_buoyancy_force():
    """Verify Archimedes buoyancy calculation for submerged PCB in molten solder."""
    # 100 x 80 x 1.6mm board (8000 mm² * 1.6mm = 12.8 cm³)
    # (7.4 - 1.85) * 12.8 = 71.04g ≈ 0.071kg * 9.8 ≈ 0.696N * 1.35 ≈ 0.94N
    f = calculate_solder_buoyancy_force(
        board_area_mm2=8000.0,
        pcb_thickness_mm=1.6,
        solder_density_g_cm3=7.4,
        pcb_density_g_cm3=1.85,
    )
    assert 0.7 < f < 1.3


def test_generate_hold_down_clamps_geometry():
    """Verify perimeter clamp placement, pivot holes, and overlap lip polygons."""
    sink = box(20, 20, 180, 140)  # 160 x 120mm board
    outer = box(0, 0, 220, 180)
    res = generate_hold_down_clamps(sink, outer)

    assert res.actual_clamp_count >= 4
    assert len(res.clamps) == res.actual_clamp_count
    assert len(res.clamp_polys) == res.actual_clamp_count
    assert res.stats["clamp_overlap_mm"] == 3.0

    # Ensure clamps are distributed across perimeter
    sides = {c.edge_side for c in res.clamps}
    assert {"bottom", "top", "left", "right"}.issubset(sides)


def test_export_hold_down_clamps_to_dxf():
    """Verify DXF export of hold-down clamps to layer '压扣压舌'."""
    sink = box(30, 30, 150, 110)
    outer = box(0, 0, 180, 140)
    res = generate_hold_down_clamps(sink, outer)

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    export_hold_down_clamps_to_dxf(msp, res)

    layers = {entity.dxf.layer for entity in msp}
    assert "压扣压舌" in layers

    circles = [e for e in msp if e.dxftype() == "CIRCLE" and e.dxf.layer == "压扣压舌"]
    assert len(circles) >= res.actual_clamp_count * 2


def test_drc_rules_46_and_47():
    """Verify DRC rule 46 (SOLDER_BUOYANCY_CLAMP_DEFICIT) and rule 47 (HOLD_DOWN_CLAMP_COMPONENT_INTERFERENCE)."""
    sink = box(20, 20, 200, 160)
    outer = box(0, 0, 240, 200)
    r1 = SimpleNamespace(
        board_poly=sink,
        sink_poly=sink,
        handles=[],
        screws=[],
        pins=[],
    )

    # 1. Trigger Rule 46 (insufficient clamps to resist buoyancy)
    r2_deficit = Phase2Result(
        avoid_polys=[],
        solder_polys=[],
        cap_holes=[],
        outer_poly=outer,
        sink_poly=sink,
        hold_down_clamps=SimpleNamespace(
            actual_clamp_count=2,
            recommended_clamp_count=6,
            buoyancy_force_n=5.2,
            clamp_polys=[],
        ),
    )
    r2_deficit.require_hold_down_clamps = True
    issues_46 = run_drc(r1, r2_deficit)
    codes_46 = [i["code"] for i in issues_46]
    assert "SOLDER_BUOYANCY_CLAMP_DEFICIT" in codes_46

    # 2. Trigger Rule 47 (clamp overlap lip collides with avoid component)
    hdc = generate_hold_down_clamps(sink, outer)
    # Put an avoid component directly on the bottom edge lip
    c0_lip = hdc.clamp_polys[0]
    colliding_avoid = box(c0_lip.bounds[0], c0_lip.bounds[1], c0_lip.bounds[2], c0_lip.bounds[3])

    r2_collision = Phase2Result(
        avoid_polys=[colliding_avoid],
        solder_polys=[],
        cap_holes=[],
        outer_poly=outer,
        sink_poly=sink,
        hold_down_clamps=hdc,
    )
    issues_47 = run_drc(r1, r2_collision)
    codes_47 = [i["code"] for i in issues_47]
    assert "HOLD_DOWN_CLAMP_COMPONENT_INTERFERENCE" in codes_47
