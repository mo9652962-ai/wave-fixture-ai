"""Tests for 3D AOI camera FOV chamfer windows, conveyor drag torque limits, and DRC rules 82-83."""

from types import SimpleNamespace

from shapely.geometry import box

from aoi_vision_window import plan_aoi_vision_windows
from conveyor_drag_torque import ConveyorDragTorqueParams, calculate_conveyor_drag_torque
from drc import run_drc


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


def test_aoi_vision_windows_safe():
    """Verify generous openings (>3.5mm clearance) have zero occlusion and clear FOV."""
    openings = [box(40, 40, 60, 60)]  # 20x20mm opening
    leads = [(50.0, 50.0)]  # 10mm from any edge (> 3.5mm)

    res = plan_aoi_vision_windows(solder_polys=openings, lead_positions=leads, wall_thickness_mm=6.0)

    assert res.openings_evaluated == 1
    assert res.is_aoi_inspection_safe is True
    assert res.max_observed_occlusion_pct == 0.0
    assert res.min_observed_clearance_mm >= 3.5
    assert len(res.violations) == 0


def test_aoi_vision_windows_occluded_flags_violation():
    """Verify lead placed 1.0mm from vertical opening wall flags high 45° occlusion."""
    openings = [box(40, 40, 60, 60)]
    leads = [(41.0, 50.0)]  # 1.0mm from left edge (< 3.5mm)

    res = plan_aoi_vision_windows(solder_polys=openings, lead_positions=leads, wall_thickness_mm=6.0)

    assert res.is_aoi_inspection_safe is False
    assert res.max_observed_occlusion_pct > 5.0
    assert len(res.violations) == 1
    assert any("逃光倒角" in a for a in res.corrective_actions)


def test_conveyor_drag_torque_safe_with_wear_rails():
    """Verify light pallet with low-friction wear rails maintains healthy motor safety factor >= 1.5."""
    params = ConveyorDragTorqueParams(
        conveyor_incline_deg=5.5,
        pallets_on_line_count=6,
        motor_rated_torque_nm=25.0,
        has_wear_rails=True,  # mu = 0.18
    )
    res = calculate_conveyor_drag_torque(pallet_mass_kg=5.0, params=params)

    assert res.friction_coefficient == 0.18
    assert res.is_motor_safe is True
    assert res.is_chain_pull_safe is True
    assert res.motor_torque_safety_factor >= 1.5
    assert res.total_drag_force_n < 650.0
    assert len(res.violations) == 0


def test_conveyor_drag_torque_heavy_pallets_stalls_motor():
    """Verify 8 heavy pallets (8.5kg) on bare composite (mu=0.30) trips motor torque overload."""
    params = ConveyorDragTorqueParams(
        conveyor_incline_deg=6.0,
        pallets_on_line_count=8,
        motor_rated_torque_nm=18.0,  # small motor
        has_wear_rails=False,  # mu = 0.30
    )
    res = calculate_conveyor_drag_torque(pallet_mass_kg=8.5, params=params)

    assert res.friction_coefficient == 0.30
    assert res.is_motor_safe is False
    assert res.motor_torque_safety_factor < 1.5
    assert len(res.violations) >= 1
    assert any("耐磨导轨" in r for r in res.recommendations)


def test_drc_rule_82_aoi_fov_occlusion():
    """Verify DRC rule 82 fires when AOI camera FOV is blocked by vertical fixture walls."""
    r1, outer = _mk_results()
    openings = [box(40, 40, 60, 60)]
    leads = [(41.0, 50.0)]  # 1mm clearance
    aoi_res = plan_aoi_vision_windows(openings, lead_positions=leads, wall_thickness_mm=6.0)

    r2 = SimpleNamespace(
        outer_poly=outer,
        avoid_polys=(),
        solder_polys=openings,
        aoi_vision_window=aoi_res,
    )
    issues = run_drc(r1, r2)
    codes = [i["code"] for i in issues]
    assert "AOI_CAMERA_FOV_OCCLUSION_RISK" in codes


def test_drc_rule_83_conveyor_drag_torque():
    """Verify DRC rule 83 fires on motor torque and chain pull overload."""
    r1, outer = _mk_results()
    params = ConveyorDragTorqueParams(
        pallets_on_line_count=10,
        motor_rated_torque_nm=15.0,
        has_wear_rails=False,
    )
    cdt_res = calculate_conveyor_drag_torque(pallet_mass_kg=9.0, params=params)

    r2 = SimpleNamespace(
        outer_poly=outer,
        avoid_polys=(),
        solder_polys=(),
        conveyor_drag_torque=cdt_res,
    )
    issues = run_drc(r1, r2)
    codes = [i["code"] for i in issues]
    assert "CONVEYOR_DRIVE_TORQUE_OVERLOAD" in codes
