"""Tests for flux puddling drainage channels, vapor relief ports, and DRC rules 62-63."""

from types import SimpleNamespace

import ezdxf
from shapely.geometry import box

from drc import run_drc
from fixture_phase2 import Phase2Result
from flux_drainage import (
    export_flux_drainage_to_dxf,
    generate_flux_drainage_and_vapor_ports,
)


def test_generate_flux_drainage_and_vapor_ports():
    """Verify weep channel and vapor relief port generation on avoid pockets."""
    # Pocket 1: 10 x 10mm = 100mm² >= 50mm² (triggers drainage & port)
    # Pocket 2: 4 x 4mm = 16mm² < 50mm² (small, exempt)
    p1 = box(10, 10, 20, 20)
    p2 = box(30, 30, 34, 34)
    res = generate_flux_drainage_and_vapor_ports([p1, p2])

    assert res.pockets_analyzed == 2
    assert res.pockets_requiring_drainage == 1
    assert len(res.weep_channels) == 1
    assert len(res.vapor_ports) == 1

    ch = res.weep_channels[0]
    assert ch.pocket_id == "AVOID_1"
    assert ch.draft_angle_deg == 45.0
    assert ch.channel_width_mm == 2.0
    assert ch.channel_poly is not None

    vp = res.vapor_ports[0]
    assert vp.pocket_id == "AVOID_1"
    assert vp.diameter_mm == 2.5
    assert abs(vp.x_mm - 15.0) < 0.1
    assert abs(vp.y_mm - 15.0) < 0.1


def test_export_flux_drainage_to_dxf():
    """Verify DXF export of weep channels and vapor relief ports on layer '助焊剂排液'."""
    p1 = box(20, 20, 40, 40)
    res = generate_flux_drainage_and_vapor_ports([p1])

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    export_flux_drainage_to_dxf(msp, res)

    layers = {entity.dxf.layer for entity in msp}
    assert "助焊剂排液" in layers

    circles = [e for e in msp if e.dxftype() == "CIRCLE" and e.dxf.layer == "助焊剂排液"]
    assert len(circles) == 1

    texts = [e.dxf.text for e in msp if e.dxf.layer == "助焊剂排液" and e.dxftype() == "TEXT"]
    assert any("WEEP DRAIN" in t for t in texts)


def test_drc_rules_62_and_63():
    """Verify DRC rule 62 (FLUX_PUDDLING_DRAINAGE_MISSING) and rule 63 (FLUX_EXPANSION_VAPOR_TRAP_RISK)."""
    outer = box(0, 0, 180, 140)
    sink = box(20, 20, 160, 120)
    r1 = SimpleNamespace(board_poly=sink, sink_poly=sink, handles=[], screws=[], pins=[])

    # 1. Trigger Rule 62: pocket requires drainage but 0 weep channels
    fd_missing = SimpleNamespace(
        pockets_requiring_drainage=2,
        weep_channels=[],
        vapor_ports=[],
    )
    r2_no_drain = Phase2Result(outer_poly=outer, sink_poly=sink, flux_drainage=fd_missing)
    r2_no_drain.require_flux_drainage = True
    issues_62 = run_drc(r1, r2_no_drain)
    codes_62 = [i["code"] for i in issues_62]
    assert "FLUX_PUDDLING_DRAINAGE_MISSING" in codes_62

    # 2. Trigger Rule 63: pocket requires drainage but 0 vapor ports
    r2_no_drain.check_vapor_ports = True
    issues_63 = run_drc(r1, r2_no_drain)
    codes_63 = [i["code"] for i in issues_63]
    assert "FLUX_EXPANSION_VAPOR_TRAP_RISK" in codes_63

    # 3. With compliant drainage, both rules pass
    p_avoid = box(30, 30, 50, 50)
    fd_ok = generate_flux_drainage_and_vapor_ports([p_avoid])
    r2_ok = Phase2Result(outer_poly=outer, sink_poly=sink, flux_drainage=fd_ok)
    r2_ok.require_flux_drainage = True
    r2_ok.check_vapor_ports = True
    issues_ok = run_drc(r1, r2_ok)
    codes_ok = [i["code"] for i in issues_ok]
    assert "FLUX_PUDDLING_DRAINAGE_MISSING" not in codes_ok
    assert "FLUX_EXPANSION_VAPOR_TRAP_RISK" not in codes_ok


def test_generate_flux_drainage_exempt_small_pockets():
    """Verify small pockets under 50mm² do not trigger drainage channels."""
    p_tiny1 = box(10, 10, 15, 15)  # 25 mm² < 50 mm²
    p_tiny2 = box(20, 20, 24, 24)  # 16 mm² < 50 mm²
    res = generate_flux_drainage_and_vapor_ports([p_tiny1, p_tiny2])
    assert res.pockets_analyzed == 2
    assert res.pockets_requiring_drainage == 0
    assert len(res.weep_channels) == 0
    assert len(res.vapor_ports) == 0

