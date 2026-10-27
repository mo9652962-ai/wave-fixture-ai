"""Tests for labyrinth solder seal, pallet anti-derailment guide snubbers, and DRC rules 84-85."""

from types import SimpleNamespace

from shapely.geometry import box

from drc import run_drc
from labyrinth_seal import LabyrinthSealParams, plan_labyrinth_solder_seal
from pallet_guide_snubbers import plan_pallet_guide_snubbers


def _mk_results():
    r1 = SimpleNamespace(
        board_poly=box(21, 21, 279, 179),
        sink_poly=box(20, 20, 280, 180),
        handles=(),
        screws=(),
        pins=(),
    )
    outer = box(0, 0, 300, 200)
    return r1, outer


def test_labyrinth_seal_geometry_generation():
    """Verify dual-step shelf and capillary breaker groove are generated outside sink."""
    sink = box(30, 30, 270, 170)
    outer = box(0, 0, 300, 200)
    params = LabyrinthSealParams(shelf_width_mm=1.8, breaker_groove_width_mm=1.2, breaker_groove_depth_mm=1.5)

    res = plan_labyrinth_solder_seal(sink, outer_poly=outer, params=params, has_tight_edge_components=True)

    assert res.shelf_poly is not None
    assert res.breaker_groove_poly is not None
    assert not res.breaker_groove_poly.is_empty
    assert res.is_capillary_break_effective is True
    assert res.estimated_capillary_rise_suppression_pct >= 90.0
    assert len(res.recommendations) >= 2
    d = res.to_dict()
    assert d["groove_width_mm"] == 1.2
    assert d["groove_depth_mm"] == 1.5


def test_pallet_guide_snubbers_y_axis():
    """Verify Y-axis conveyor creates left and right underside guide lips with lead-in ramps."""
    outer = box(0, 0, 300, 220)
    res = plan_pallet_guide_snubbers(outer, pallet_mass_kg=5.2, conveyor_axis="Y")

    assert res.total_snubber_count == 2
    assert res.snubbers[0].side == "left"
    assert res.snubbers[1].side == "right"
    assert res.snubbers[0].length_mm == 220.0
    assert res.is_derailment_prevented is True
    assert res.max_vertical_play_mm <= 1.0
    assert len(res.recommendations) >= 2


def test_pallet_guide_snubbers_x_axis():
    """Verify X-axis conveyor creates bottom and top underside guide lips."""
    outer = box(0, 0, 280, 180)
    res = plan_pallet_guide_snubbers(outer, pallet_mass_kg=4.0, conveyor_axis="X")

    assert res.total_snubber_count == 2
    assert res.snubbers[0].side == "bottom"
    assert res.snubbers[1].side == "top"
    assert res.snubbers[0].length_mm == 280.0


def test_drc_rule_84_labyrinth_seal_missing():
    """Verify DRC rule 84 fires when PCB has tight edge components but no labyrinth seal."""
    r1, outer = _mk_results()

    r2 = SimpleNamespace(
        outer_poly=outer,
        avoid_polys=(),
        solder_polys=(),
        has_tight_edge_components=True,
        labyrinth_seal=None,  # Missing!
    )
    issues = run_drc(r1, r2)
    codes = [i["code"] for i in issues]
    assert "LABYRINTH_CAPILLARY_SEAL_MISSING" in codes


def test_drc_rule_85_conveyor_rail_snubber_missing():
    """Verify DRC rule 85 fires on heavy/long pallets lacking bottom guide lips."""
    r1, outer = _mk_results()  # Outer span = 300mm >= 240mm

    r2 = SimpleNamespace(
        outer_poly=outer,
        avoid_polys=(),
        solder_polys=(),
        pallet_mass_kg=5.2,  # >= 4.5kg
        pallet_guide_snubbers=None,  # Missing!
    )
    issues = run_drc(r1, r2)
    codes = [i["code"] for i in issues]
    assert "CONVEYOR_RAIL_SNUBBER_MISSING" in codes
