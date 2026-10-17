"""Tests for conveyor wear rails, ESD grounding, and DRC rules 66-67."""

from types import SimpleNamespace

from shapely.geometry import box

from conveyor_wear_rails import (
    ConveyorWearRailsParams,
    plan_conveyor_wear_rails,
)
from drc import run_drc
from esd_grounding import plan_esd_grounding


def test_plan_conveyor_wear_rails_y_axis():
    """Verify Y-axis conveyor creates left and right wear rails with M3 holes."""
    outer = box(0, 0, 300, 200)
    sink = box(30, 20, 270, 180)
    params = ConveyorWearRailsParams(rail_width_mm=10.0, conveyor_axis="Y")
    res = plan_conveyor_wear_rails(outer, sink_poly=sink, params=params)

    assert len(res.rails) == 2
    assert res.rails[0].side == "left"
    assert res.rails[1].side == "right"
    assert res.total_rail_length_mm == 400.0
    assert res.mounting_hole_count >= 4
    assert res.min_clearance_to_sink_mm >= 20.0  # 30 - 10 = 20mm
    assert len(res.bom_items) == 2


def test_plan_conveyor_wear_rails_x_axis():
    """Verify X-axis conveyor creates bottom and top wear rails."""
    outer = box(0, 0, 300, 200)
    params = ConveyorWearRailsParams(rail_width_mm=10.0, conveyor_axis="X")
    res = plan_conveyor_wear_rails(outer, params=params)

    assert len(res.rails) == 2
    assert res.rails[0].side == "bottom"
    assert res.rails[1].side == "top"
    assert res.total_rail_length_mm == 600.0


def test_plan_esd_grounding_compliance():
    """Verify ESD grounding generates 4 contact buttons and meets ANSI/ESD S20.20."""
    outer = box(0, 0, 300, 200)
    res = plan_esd_grounding(outer)

    assert res.total_point_count == 4
    assert res.is_compliant is True
    assert res.estimated_point_to_ground_rg_ohm < 1.0e9
    assert res.decay_time_sec < 2.0
    assert len(res.bom_items) == 1
    d = res.to_dict()
    assert d["total_point_count"] == 4
    assert d["is_compliant"] is True


def test_drc_rule_66_conveyor_wear_rail_clearance():
    """Verify DRC rule 66 (CONVEYOR_WEAR_RAIL_CLEARANCE_INSUFFICIENT)."""
    # Outer 300x200, sink at X=5mm -> clearance = 0mm (< 8.0mm)
    outer = box(0, 0, 300, 200)
    sink = box(5, 20, 295, 180)
    board = box(6, 21, 294, 179)
    cwr = plan_conveyor_wear_rails(outer, sink_poly=sink)

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
        conveyor_wear_rails=cwr,
    )

    issues = run_drc(r1, r2)
    codes = [i["code"] for i in issues]
    assert "CONVEYOR_WEAR_RAIL_CLEARANCE_INSUFFICIENT" in codes


def test_drc_rule_67_esd_ground_path_missing():
    """Verify DRC rule 67 (ESD_GROUND_PATH_MISSING)."""
    outer = box(0, 0, 300, 200)
    sink = box(30, 30, 270, 170)
    board = box(31, 31, 269, 169)

    r1 = SimpleNamespace(
        board_poly=board,
        sink_poly=sink,
        handles=(),
        screws=(),
        pins=(),
    )
    r2_deficit = SimpleNamespace(
        outer_poly=outer,
        avoid_polys=(),
        solder_polys=(),
        require_esd_compliance=True,
        esd_grounding=None,
    )

    issues = run_drc(r1, r2_deficit)
    codes = [i["code"] for i in issues]
    assert "ESD_GROUND_PATH_MISSING" in codes
