"""Tests for pallet orientation keying chamfer and DRC rule 55."""

from types import SimpleNamespace

import ezdxf
from shapely.geometry import box

from drc import run_drc
from fixture_phase2 import Phase2Result
from pallet_keying import (
    export_pallet_keying_to_dxf,
    generate_pallet_keying,
)


def test_generate_pallet_keying_geometry():
    """Verify asymmetric corner chamfer geometry on a near-square pallet."""
    outer = box(0, 0, 200, 200)
    res = generate_pallet_keying(outer)

    assert not res.keyed_poly.is_empty
    assert res.chamfer_mm == 15.0
    assert res.corner == "front_right"
    assert len(res.chamfer_lines) == 1
    # Area removed = 0.5 * 15 * 15 = 112.5 mm²
    assert abs(res.stats["area_removed_mm2"] - 112.5) < 0.1
    # Keyed polygon bounds shrink on the keyed corner
    kx0, ky0, kx1, ky1 = res.keyed_poly.bounds
    assert (kx0, ky0, kx1, ky1) == (0.0, 0.0, 200.0, 200.0)


def test_pallet_keying_all_corners():
    """Verify chamfer placement across the four corner options."""
    outer = box(0, 0, 150, 150)
    for corner in ("front_right", "front_left", "back_right", "back_left"):
        res = generate_pallet_keying(outer, params=SimpleNamespace(chamfer_mm=10.0, corner=corner))
        assert len(res.chamfer_lines) == 1
        assert res.corner == corner


def test_export_pallet_keying_to_dxf():
    """Verify DXF layer '防呆切角' with chamfer polyline and note."""
    outer = box(0, 0, 180, 180)
    res = generate_pallet_keying(outer)

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    export_pallet_keying_to_dxf(msp, res)

    layers = {entity.dxf.layer for entity in msp}
    assert "防呆切角" in layers
    texts = [e.dxf.text for e in msp if e.dxf.layer == "防呆切角" and e.dxftype() == "TEXT"]
    assert any("ORIENTATION KEY" in t for t in texts)


def test_drc_rule_55_pallet_orientation_keying():
    """Verify DRC rule 55 (PALLET_ORIENTATION_KEYING_MISSING)."""
    outer = box(0, 0, 180, 180)  # aspect 1.0
    sink = box(20, 20, 160, 160)
    r1 = SimpleNamespace(board_poly=sink, sink_poly=sink, handles=[], screws=[], pins=[])

    # Near-square without keying triggers
    r2_none = Phase2Result(outer_poly=outer, sink_poly=sink)
    issues_none = run_drc(r1, r2_none)
    assert "PALLET_ORIENTATION_KEYING_MISSING" in [i["code"] for i in issues_none]

    # With keying passes
    r2_keyed = Phase2Result(outer_poly=outer, sink_poly=sink)
    r2_keyed.pallet_keying = generate_pallet_keying(outer)
    issues_keyed = run_drc(r1, r2_keyed)
    assert "PALLET_ORIENTATION_KEYING_MISSING" not in [i["code"] for i in issues_keyed]

    # Elongated pallet exempt (aspect out of 0.85..1.15)
    outer_long = box(0, 0, 300, 150)
    r2_long = Phase2Result(outer_poly=outer_long, sink_poly=box(20, 20, 280, 130))
    issues_long = run_drc(r1, r2_long)
    assert "PALLET_ORIENTATION_KEYING_MISSING" not in [i["code"] for i in issues_long]
