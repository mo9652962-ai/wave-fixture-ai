"""Tests for chip wave de-bridging baffle, pallet lifting force / ergonomic grips, and DRC rules 86-87."""

from types import SimpleNamespace

import ezdxf
from shapely.geometry import box

from chip_wave_baffle import export_chip_wave_baffles_to_dxf, plan_chip_wave_baffles
from drc import run_drc
from pallet_lifting_force import check_pallet_lifting_force, export_pallet_lifting_grips_to_dxf


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


def test_chip_wave_baffle_planning_and_dxf():
    """Verify chip wave de-bridging baffles are correctly positioned on trailing edge and exported to DXF."""
    clusters = [
        {"x_min": 50.0, "y_min": 60.0, "x_max": 80.0, "y_max": 90.0, "has_fine_pitch_ic": True},
        {"x_min": 120.0, "y_min": 110.0, "x_max": 140.0, "y_max": 130.0, "has_fine_pitch_ic": False},
    ]
    res = plan_chip_wave_baffles(
        smd_clusters=clusters,
        flow_direction="x_positive",
        baffle_gap_mm=2.0,
        baffle_width_mm=3.5,
    )
    assert res.total_baffles == 2
    assert res.is_debridging_effective is True
    assert res.bridging_risk_reduction_pct >= 80.0
    assert len(res.violations) == 0
    assert res.baffles[0].poly is not None
    assert res.baffles[0].x_max == 50.0 - 2.0  # Trailing edge: cx0 - gap

    # DXF 导出验证
    doc = ezdxf.new()
    msp = doc.modelspace()
    count = export_chip_wave_baffles_to_dxf(res, msp)
    assert count == 2
    assert "消锡挡板" in doc.layers


def test_chip_wave_baffle_gap_violation():
    """Verify gap too small flags clearance violation against squeezing SMD components."""
    clusters = [{"x_min": 50.0, "y_min": 60.0, "x_max": 80.0, "y_max": 90.0}]
    res = plan_chip_wave_baffles(smd_clusters=clusters, baffle_gap_mm=0.8)
    assert res.is_debridging_effective is False
    assert any("过于逼近贴片元件焊盘" in v for v in res.violations)


def test_pallet_lifting_force_compliant():
    """Verify standard fixture with recessed grips passes ergonomic lifting standards."""
    res = check_pallet_lifting_force(
        pallet_length_mm=380.0,
        pallet_width_mm=280.0,
        pallet_thickness_mm=12.0,
        total_mass_kg=5.2,
        has_recessed_grips=True,
        grip_width_mm=115.0,
        grip_depth_mm=26.0,
    )
    assert res.is_ergonomically_acceptable is True
    assert res.coupling_multiplier_cm == 1.00
    assert res.lifting_index_niosh <= 1.00
    assert len(res.grips) == 2
    assert res.grips[0].edge == "left"
    assert res.grips[1].edge == "right"

    # DXF 导出验证
    doc = ezdxf.new()
    msp = doc.modelspace()
    cnt = export_pallet_lifting_grips_to_dxf(res, msp)
    assert cnt == 2
    assert "人体工学拉手" in doc.layers


def test_pallet_lifting_force_violations():
    """Verify heavy fixture without grips or with shallow grips triggers violations."""
    # 质量达 5.5kg 但未配置手抓槽
    res_no_grip = check_pallet_lifting_force(
        total_mass_kg=5.5,
        has_recessed_grips=False,
    )
    assert res_no_grip.is_ergonomically_acceptable is False
    assert res_no_grip.coupling_multiplier_cm == 0.70
    assert any("未设计内嵌手指抓持槽" in v for v in res_no_grip.violations)

    # 抓槽深度仅 16mm < 22mm
    res_shallow = check_pallet_lifting_force(
        total_mass_kg=5.0,
        has_recessed_grips=True,
        grip_width_mm=110.0,
        grip_depth_mm=16.0,
    )
    assert res_shallow.is_ergonomically_acceptable is False
    assert any("内凹深度" in v for v in res_shallow.violations)


def test_drc_rules_86_and_87():
    """Verify DRC rule 86 (CHIP_WAVE_BAFFLE_MISSING) and rule 87 (PALLET_ERGONOMIC_LIFTING_EXCESSIVE)."""
    r1, outer = _mk_results()

    # Case A: 含有底面贴片器件但未配置消锡扰流挡板 -> 触发规则 86
    r2_a = SimpleNamespace(
        outer_poly=outer,
        sink_poly=r1.sink_poly,
        avoid_polys=[],
        solder_polys=[],
        cap_holes=[],
        vent_holes=[],
        has_bottom_smd_chips=True,
        chip_wave_baffle=None,
    )
    issues_a = run_drc(r1, r2_a)
    codes_a = [i["code"] for i in issues_a]
    assert "CHIP_WAVE_BAFFLE_MISSING" in codes_a

    # Case B: 治具总质量 5.5kg 但未设计人体工学手抓槽 -> 触发规则 87
    plf_fail = check_pallet_lifting_force(total_mass_kg=5.5, has_recessed_grips=False)
    r2_b = SimpleNamespace(
        outer_poly=outer,
        sink_poly=r1.sink_poly,
        avoid_polys=[],
        solder_polys=[],
        cap_holes=[],
        vent_holes=[],
        pallet_lifting_force=plf_fail,
    )
    issues_b = run_drc(r1, r2_b)
    codes_b = [i["code"] for i in issues_b]
    assert "PALLET_ERGONOMIC_LIFTING_EXCESSIVE" in codes_b
