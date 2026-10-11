"""Tests for trailing edge solder run-off scuppers and DRC rules 58-59."""

from types import SimpleNamespace

import ezdxf
from shapely.geometry import box

from drc import run_drc
from fixture_phase2 import Phase2Result
from solder_scuppers import (
    export_solder_scuppers_to_dxf,
    generate_trailing_solder_scuppers,
)


def test_generate_trailing_solder_scuppers():
    """Verify scupper placement along trailing edge and ramp line generation."""
    outer = box(0, 0, 240, 180)
    sink = box(20, 20, 200, 160)
    res = generate_trailing_solder_scuppers(outer, sink_poly=sink)

    assert res.scupper_count >= 2
    assert len(res.scuppers) == res.scupper_count
    assert len(res.scupper_polys) == res.scupper_count
    assert res.ramp_angle_deg == 30.0

    # Scupper box must be located at the trailing edge (X+ exit -> right side ox1=240)
    s0 = res.scuppers[0]
    assert s0.center_x_mm > 220.0
    assert len(s0.ramp_lines) == 2
    assert res.min_clearance_found_mm > 0.0


def test_export_solder_scuppers_to_dxf():
    """Verify DXF export of scupper outlines and note on layer '沥锡导流'."""
    outer = box(0, 0, 200, 150)
    res = generate_trailing_solder_scuppers(outer)

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    export_solder_scuppers_to_dxf(msp, res)

    layers = {entity.dxf.layer for entity in msp}
    assert "沥锡导流" in layers

    texts = [e.dxf.text for e in msp if e.dxf.layer == "沥锡导流" and e.dxftype() == "TEXT"]
    assert any("RUN-OFF SCUPPER" in t for t in texts)


def test_drc_rule_58_scuppers_missing():
    """Verify DRC rule 58 (TRAILING_SOLDER_SCUPPER_MISSING) on long flow span."""
    outer = box(0, 0, 220, 160)  # flow span 220 >= 180mm
    sink = box(20, 20, 180, 140)
    r1 = SimpleNamespace(board_poly=sink, sink_poly=sink, handles=[], screws=[], pins=[])

    # Missing scuppers when required
    r2_none = Phase2Result(outer_poly=outer, sink_poly=sink)
    r2_none.require_solder_scuppers = True
    issues_none = run_drc(r1, r2_none)
    codes_none = [i["code"] for i in issues_none]
    assert "TRAILING_SOLDER_SCUPPER_MISSING" in codes_none

    # With scuppers planned, rule passes
    ss = generate_trailing_solder_scuppers(outer, sink_poly=sink)
    r2_ok = Phase2Result(outer_poly=outer, sink_poly=sink, solder_scuppers=ss)
    r2_ok.require_solder_scuppers = True
    issues_ok = run_drc(r1, r2_ok)
    assert "TRAILING_SOLDER_SCUPPER_MISSING" not in [i["code"] for i in issues_ok]


def test_drc_rule_59_scupper_clearance_insufficient():
    """Verify DRC rule 59 (SCUPPER_CLEARANCE_TO_BOARD_INSUFFICIENT)."""
    outer = box(0, 0, 200, 160)
    # Sink extends too close to trailing edge ox1=200 (distance = 2.0mm < 4.0mm seal land)
    sink_tight = box(20, 20, 196, 140)
    r1 = SimpleNamespace(board_poly=sink_tight, sink_poly=sink_tight, handles=[], screws=[], pins=[])

    # Scupper slot depth is 12mm inward from ox1=200 -> slot left edge is at 188mm!
    # So slot overlaps sink_tight (which extends to 196mm), giving distance = 0
    # Let's test with distance = 2.5mm:
    ss_tight = SimpleNamespace(scupper_count=2, min_clearance_found_mm=2.5)
    r2_tight = Phase2Result(outer_poly=outer, sink_poly=sink_tight, solder_scuppers=ss_tight)

    issues = run_drc(r1, r2_tight)
    codes = [i["code"] for i in issues]
    assert "SCUPPER_CLEARANCE_TO_BOARD_INSUFFICIENT" in codes
