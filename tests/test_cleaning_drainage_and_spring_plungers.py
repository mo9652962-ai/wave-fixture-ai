"""Tests for ultrasonic cleaning drainage, spring plunger array, and DRC rules 70-71."""

from types import SimpleNamespace

from shapely.geometry import box

from cleaning_drainage import (
    CleaningDrainageParams,
    plan_cleaning_drainage,
)
from drc import run_drc
from spring_plunger_array import (
    SpringPlungerParams,
    plan_spring_plunger_array,
)


def test_plan_cleaning_drainage_deep_cavity():
    """Verify deep cavity (>=4mm) with large area generates drain slots and weep holes."""
    # Cavity 15x10mm -> area 150mm² (>= 80mm²)
    pockets = [box(20, 20, 35, 30)]
    params = CleaningDrainageParams(trigger_depth_mm=4.0, trigger_area_mm2=80.0)

    res = plan_cleaning_drainage(pockets, cavity_depth_mm=5.0, params=params)

    assert res.pockets_evaluated == 1
    assert res.pockets_with_drainage == 1
    assert res.total_drain_holes >= 2
    assert res.is_safe_against_water_trap is True
    d = res.to_dict()
    assert d["total_drain_holes"] >= 2


def test_plan_cleaning_drainage_shallow_exempt():
    """Verify shallow cavity (<4mm) is exempt from drainage machining."""
    pockets = [box(20, 20, 35, 30)]
    params = CleaningDrainageParams(trigger_depth_mm=4.0)

    res = plan_cleaning_drainage(pockets, cavity_depth_mm=2.5, params=params)

    assert res.pockets_evaluated == 1
    assert res.pockets_with_drainage == 0
    assert res.total_drain_holes == 0


def test_plan_spring_plunger_array_distribution():
    """Verify spring plungers distribute across sink while strictly avoiding solder apertures."""
    sink = box(0, 0, 200, 150)
    # Solder window in center
    solder = [box(80, 50, 120, 90)]
    params = SpringPlungerParams(grid_spacing_mm=40.0)

    res = plan_spring_plunger_array(sink, solder_polys=solder, params=params, estimated_buoyancy_force_n=6.0)

    assert res.total_plunger_count >= 4
    assert res.total_downward_force_n >= 6.0 * 1.2
    assert res.is_force_balanced is True
    assert res.cushioned_plunger_count >= 1
    assert len(res.bom_items) == 2


def test_drc_rule_70_cleaning_drainage_missing():
    """Verify DRC rule 70 (CLEANING_DRAINAGE_DEAD_ZONE_RISK)."""
    outer = box(0, 0, 300, 200)
    sink = box(30, 20, 270, 180)
    board = box(31, 21, 269, 179)
    # Large deep avoid pocket without drainage
    avoid = [box(50, 50, 70, 70)]  # 400 mm²

    r1 = SimpleNamespace(
        board_poly=board,
        sink_poly=sink,
        handles=(),
        screws=(),
        pins=(),
    )
    r2 = SimpleNamespace(
        outer_poly=outer,
        avoid_polys=avoid,
        solder_polys=(),
        require_cleaning_drainage=True,
        cleaning_drainage=None,
    )

    issues = run_drc(r1, r2)
    codes = [i["code"] for i in issues]
    assert "CLEANING_DRAINAGE_DEAD_ZONE_RISK" in codes


def test_drc_rule_71_rigid_plunger_crush_risk():
    """Verify DRC rule 71 (RIGID_PLUNGER_COMPONENT_CRUSH_RISK)."""
    outer = box(0, 0, 300, 200)
    sink = box(30, 20, 270, 180)
    board = box(31, 21, 269, 179)

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
        top_hat=object(),  # Top hat is installed
        require_spring_plungers=True,
        spring_plunger_array=None,  # No spring plungers installed!
    )

    issues = run_drc(r1, r2)
    codes = [i["code"] for i in issues]
    assert "RIGID_PLUNGER_COMPONENT_CRUSH_RISK" in codes
