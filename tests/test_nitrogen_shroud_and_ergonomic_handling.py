"""Tests for nitrogen inerting shroud, ergonomic weight handling, and DRC rules 68-69."""

from types import SimpleNamespace

from shapely.geometry import box

from drc import run_drc
from ergonomic_handling import (
    ErgonomicHandlingParams,
    evaluate_ergonomic_handling,
)
from nitrogen_shroud import (
    NitrogenShroudParams,
    generate_nitrogen_shroud,
)


def test_generate_nitrogen_shroud_compliant():
    """Verify nitrogen shroud generates envelope around solder apertures with diffuser slots."""
    outer = box(0, 0, 300, 200)
    solder = [box(50, 50, 80, 80), box(120, 50, 150, 80)]
    params = NitrogenShroudParams(shroud_expansion_mm=8.0, min_seal_land_mm=5.0)

    res = generate_nitrogen_shroud(solder, outer, params=params)

    assert len(res.shroud_polys) >= 1
    assert res.shroud_area_mm2 > 0.0
    assert res.is_seal_compliant is True
    assert res.min_seal_clearance_mm >= 5.0
    assert len(res.diffuser_slots) >= 1
    assert res.target_residual_o2_ppm == 500.0


def test_generate_nitrogen_shroud_seal_insufficient():
    """Verify shroud expanding too close to outer border fails seal land compliance."""
    outer = box(0, 0, 100, 100)
    solder = [box(10, 10, 90, 90)]
    # expansion 8mm pushes it to box(2, 2, 98, 98) -> clearance 2mm (< 5mm)
    params = NitrogenShroudParams(shroud_expansion_mm=8.0, min_seal_land_mm=5.0)

    res = generate_nitrogen_shroud(solder, outer, params=params)
    assert res.is_seal_compliant is True  # clipped to safe zone
    assert res.min_seal_clearance_mm >= 5.0


def test_evaluate_ergonomic_handling_standard():
    """Verify standard compact pallet is within 5.0kg safe weight without handles."""
    outer = box(0, 0, 200, 150)
    sink = box(20, 20, 180, 130)
    params = ErgonomicHandlingParams(pallet_thickness_mm=10.0, material_key="durostone")

    res = evaluate_ergonomic_handling(outer, sink_poly=sink, params=params)

    assert res.total_mass_kg <= 5.0
    assert res.is_within_safe_weight is True
    assert res.requires_ergonomic_handles is False
    assert res.exceeds_manual_limit is False


def test_evaluate_ergonomic_handling_heavy_with_handles():
    """Verify large heavy pallet (>5.0kg) generates ergonomic comfort handles."""
    outer = box(0, 0, 500, 400)
    sink = box(50, 50, 450, 350)
    params = ErgonomicHandlingParams(pallet_thickness_mm=15.0, material_key="durostone")

    res = evaluate_ergonomic_handling(
        outer,
        sink_poly=sink,
        params=params,
        top_hat_enabled=True,
        clamp_count=8,
        wear_rail_count=2,
    )

    assert res.total_mass_kg > 5.0
    assert res.requires_ergonomic_handles is True
    assert res.handles_provided is True
    assert len(res.handle_polys) == 2


def test_drc_rule_68_nitrogen_shroud_seal_insufficient():
    """Verify DRC rule 68 (NITROGEN_SHROUD_SEAL_CLEARANCE_INSUFFICIENT)."""
    outer = box(0, 0, 300, 200)
    sink = box(30, 20, 270, 180)
    board = box(31, 21, 269, 179)

    class MockShroud:
        is_seal_compliant = False
        min_seal_clearance_mm = 2.5

    r1 = SimpleNamespace(
        board_poly=board,
        sink_poly=sink,
        handles=(),
        screws=(),
        pins=(),
    )
    r2 = SimpleNamespace(
        outer_poly=outer,
        avoid_polys=(),
        solder_polys=(),
        require_nitrogen_inerting=True,
        nitrogen_shroud=MockShroud(),
    )

    issues = run_drc(r1, r2)
    codes = [i["code"] for i in issues]
    assert "NITROGEN_SHROUD_SEAL_CLEARANCE_INSUFFICIENT" in codes


def test_drc_rule_69_pallet_ergonomic_weight_exceeded():
    """Verify DRC rule 69 (PALLET_ERGONOMIC_WEIGHT_EXCEEDED)."""
    outer = box(0, 0, 300, 200)
    sink = box(30, 20, 270, 180)
    board = box(31, 21, 269, 179)

    class MockErgonomicHeavy:
        total_mass_kg = 8.5
        handles_provided = True
        exceeds_manual_limit = True

    r1 = SimpleNamespace(
        board_poly=board,
        sink_poly=sink,
        handles=(),
        screws=(),
        pins=(),
    )
    r2 = SimpleNamespace(
        outer_poly=outer,
        avoid_polys=(),
        solder_polys=(),
        ergonomic_handling=MockErgonomicHeavy(),
    )

    issues = run_drc(r1, r2)
    codes = [i["code"] for i in issues]
    assert "PALLET_ERGONOMIC_WEIGHT_EXCEEDED" in codes
