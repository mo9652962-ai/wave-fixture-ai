"""Tests for bottom SMD red glue stencil and DRC rules 60-61."""

from types import SimpleNamespace

import ezdxf
from shapely.geometry import box

from drc import run_drc
from fixture_phase2 import Phase2Result
from red_glue_stencil import export_red_glue_to_dxf, generate_red_glue_dots


def test_generate_red_glue_dots_smd():
    """Verify dot coordinates, volume, and clearance for 0805/0603 passives."""
    comps = [
        {"ref": "C1", "package": "0805", "x_mm": 20.0, "y_mm": 30.0, "pad_inner_gap_mm": 1.7},
        {"ref": "R1", "package": "0603", "x_mm": 40.0, "y_mm": 50.0, "pad_inner_gap_mm": 1.5},
    ]
    res = generate_red_glue_dots(comps)

    assert res.total_dots == 2
    assert res.contaminated_dots_count == 0
    assert len(res.dots) == 2

    d0 = res.dots[0]
    assert d0.ref == "C1"
    assert d0.diameter_mm == 1.0
    assert d0.volume_nl == 0.12
    # clearance = (1.7 - 1.0)/2 = 0.35mm >= 0.30mm (safe)
    assert d0.pad_clearance_mm == 0.35
    assert d0.is_safe_from_pads is True
    assert "Ref,Dot_ID" in res.csv_dispense_table


def test_generate_red_glue_dots_soic_dual():
    """Verify dual glue dots generated for SOIC components."""
    comps = [
        {"ref": "U1", "package": "SOIC-8", "x_mm": 50.0, "y_mm": 60.0, "rotation_deg": 0.0},
    ]
    res = generate_red_glue_dots(comps)
    # SOIC-8 generates 2 dots
    assert res.total_dots == 2
    assert res.dots[0].dot_id == "GLUE_U1_1"
    assert res.dots[1].dot_id == "GLUE_U1_2"
    assert abs(res.dots[0].y_mm - res.dots[1].y_mm) < 0.01  # horizontal line


def test_export_red_glue_to_dxf():
    """Verify DXF export of red glue circles and labels on layer '红胶点胶'."""
    comps = [{"ref": "C10", "package": "0805", "x_mm": 25.0, "y_mm": 35.0}]
    res = generate_red_glue_dots(comps)

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    export_red_glue_to_dxf(msp, res)

    layers = {entity.dxf.layer for entity in msp}
    assert "红胶点胶" in layers

    circles = [e for e in msp if e.dxftype() == "CIRCLE" and e.dxf.layer == "红胶点胶"]
    assert len(circles) == 1
    assert abs(circles[0].dxf.radius - 0.5) < 0.01  # dia=1.0 -> r=0.5


def test_drc_rules_60_and_61():
    """Verify DRC rule 60 (BOTTOM_SMD_RED_GLUE_MISSING) and rule 61 (RED_GLUE_PAD_CONTAMINATION_RISK)."""
    outer = box(0, 0, 160, 120)
    sink = box(20, 20, 140, 100)
    r1 = SimpleNamespace(board_poly=sink, sink_poly=sink, handles=[], screws=[], pins=[])

    # Rule 60: has bottom SMD but no red glue
    r2_no_glue = Phase2Result(outer_poly=outer, sink_poly=sink)
    r2_no_glue.has_bottom_smd_components = True
    r2_no_glue.require_red_glue = True
    issues_60 = run_drc(r1, r2_no_glue)
    codes_60 = [i["code"] for i in issues_60]
    assert "BOTTOM_SMD_RED_GLUE_MISSING" in codes_60

    # Rule 61: contaminated dots (<0.30mm clearance to pad)
    comps_tight = [
        {"ref": "C_TIGHT", "package": "0805", "x_mm": 30.0, "y_mm": 40.0, "pad_inner_gap_mm": 1.2},
    ]  # (1.2 - 1.0)/2 = 0.10mm < 0.30mm
    rgs_tight = generate_red_glue_dots(comps_tight)
    assert rgs_tight.contaminated_dots_count == 1

    r2_tight = Phase2Result(outer_poly=outer, sink_poly=sink, red_glue_stencil=rgs_tight)
    r2_tight.has_bottom_smd_components = True
    r2_tight.require_red_glue = True
    issues_61 = run_drc(r1, r2_tight)
    codes_61 = [i["code"] for i in issues_61]
    assert "RED_GLUE_PAD_CONTAMINATION_RISK" in codes_61
    assert "BOTTOM_SMD_RED_GLUE_MISSING" not in codes_61
