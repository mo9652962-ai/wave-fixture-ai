"""Tests for solder dam dross skimmer and conveyor incline dynamics (DRC 44-45)."""

from types import SimpleNamespace

import ezdxf
from shapely.geometry import box

from drc import run_drc
from fixture_phase2 import Phase2Result
from solder_dam import (
    compute_incline_dynamic_clearance,
    export_solder_dam_to_dxf,
    generate_solder_dam_and_incline,
)


def test_generate_solder_dam():
    """Verify geometry generation of 8mm dross skimmer slot and bevel lines."""
    outer = box(0, 0, 300, 200)
    sink = box(30, 20, 270, 180)
    res = generate_solder_dam_and_incline(outer, sink)

    assert not res.dam_poly.is_empty
    _bx0, by0, _bx1, by1 = res.dam_poly.bounds
    # Slot placed at bottom leading edge (oy0 + 6mm to + 14mm)
    assert by0 >= 6.0
    assert by1 <= 15.0
    assert res.stats["dam_width_mm"] == 8.0
    assert len(res.bevel_lines) == 2
    assert len(res.drainage_lines) == 2


def test_export_solder_dam_to_dxf():
    """Verify DXF export of solder dam, bevel lines, and engineering text on layer '防渣导流'."""
    outer = box(0, 0, 250, 180)
    res = generate_solder_dam_and_incline(outer)

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    export_solder_dam_to_dxf(msp, res)

    layers = {entity.dxf.layer for entity in msp}
    assert "防渣导流" in layers
    texts = [e.dxf.text for e in msp if e.dxftype() == "TEXT"]
    assert any("DROSS SKIMMER DAM" in t for t in texts)


def test_incline_dynamic_clearance_calculation():
    """Verify conveyor incline dynamic clearance equation."""
    # At x = 100mm, with 5.5 deg incline: tan(5.5°) ≈ 0.0963 -> dz ≈ 9.63mm
    res = compute_incline_dynamic_clearance(
        comp_x_mm=100.0,
        comp_height_mm=1.5,
        board_length_mm=150.0,
        incline_deg=5.5,
        nominal_pocket_depth_mm=15.0,
    )
    assert 9.0 < res["dz_slope_mm"] < 10.5
    assert res["effective_clearance_mm"] > 0.8
    assert not res["has_wave_contact_risk"]

    # At tall component where clearance drops below 0.8mm
    res_risk = compute_incline_dynamic_clearance(
        comp_x_mm=100.0,
        comp_height_mm=14.0,
        board_length_mm=150.0,
        incline_deg=5.5,
        nominal_pocket_depth_mm=15.0,
    )
    assert res_risk["has_wave_contact_risk"] is True


def test_drc_rules_44_and_45():
    """Verify DRC rule 44 (SOLDER_DAM_DROSS_SKIMMER_MISSING) and rule 45 (CONVEYOR_INCLINE_COLLISION_RISK)."""
    outer = box(0, 0, 300, 200)
    sink = box(20, 20, 280, 180)
    r1 = SimpleNamespace(
        board_poly=sink,
        sink_poly=sink,
        handles=[],
        screws=[],
        pins=[],
    )

    # 1. Trigger Rule 44 (large pallet without solder dam)
    r2_no_dam = Phase2Result(
        avoid_polys=[],
        solder_polys=[box(50, 50, 80, 80)],
        cap_holes=[],
        outer_poly=outer,
        sink_poly=sink,
        solder_dam=None,
    )
    r2_no_dam.require_dross_skimmer = True
    issues_44 = run_drc(r1, r2_no_dam)
    codes_44 = [i["code"] for i in issues_44]
    assert "SOLDER_DAM_DROSS_SKIMMER_MISSING" in codes_44

    # 2. Resolve Rule 44
    dam_res = generate_solder_dam_and_incline(outer, sink)
    r2_with_dam = Phase2Result(
        avoid_polys=[],
        solder_polys=[box(50, 50, 80, 80)],
        cap_holes=[],
        outer_poly=outer,
        sink_poly=sink,
        solder_dam=dam_res,
    )
    r2_with_dam.require_dross_skimmer = True
    issues_ok = run_drc(r1, r2_with_dam)
    assert "SOLDER_DAM_DROSS_SKIMMER_MISSING" not in [i["code"] for i in issues_ok]

    # 3. Trigger Rule 45 (long sink span >= 180mm with incline clearance check)
    r2_with_dam.check_incline_clearance = True
    issues_45 = run_drc(r1, r2_with_dam)
    codes_45 = [i["code"] for i in issues_45]
    assert "CONVEYOR_INCLINE_COLLISION_RISK" in codes_45
