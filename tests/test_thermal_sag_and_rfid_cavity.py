"""Tests for PCB thermal sag support pillars, UHF RFID embedded cavity, and DRC rules 72-73."""

from types import SimpleNamespace

from shapely.geometry import box

from drc import run_drc
from rfid_cavity import (
    RFIDCavityParams,
    plan_rfid_embedded_cavity,
)
from thermal_sag_support import (
    ThermalSagSupportParams,
    plan_thermal_sag_supports,
)


def test_plan_thermal_sag_supports_large_span():
    """Verify large span PCB (>=160mm) plans support pillars in center open area."""
    sink = box(0, 0, 200, 150)
    solder = [box(10, 10, 30, 30)]
    avoid = [box(40, 40, 50, 50)]
    params = ThermalSagSupportParams(trigger_span_mm=160.0)

    res = plan_thermal_sag_supports(sink, solder_polys=solder, avoid_polys=avoid, pcb_thickness_mm=1.6, params=params)

    assert res.total_pillar_count >= 1
    assert res.is_sag_deflection_acceptable is True
    assert res.estimated_thermal_sag_mm <= 0.50
    d = res.to_dict()
    assert d["total_pillar_count"] >= 1


def test_plan_thermal_sag_supports_small_board_exempt():
    """Verify compact board (<160mm) is exempt from anti-sag pillars."""
    sink = box(0, 0, 100, 80)
    params = ThermalSagSupportParams(trigger_span_mm=160.0)

    res = plan_thermal_sag_supports(sink, pcb_thickness_mm=1.6, params=params)

    assert res.total_pillar_count == 0
    assert res.is_sag_deflection_acceptable is True


def test_plan_rfid_embedded_cavity_safe():
    """Verify RFID cavity placed with >=8mm clearance to metal blocks."""
    outer = box(0, 0, 300, 200)
    metal = [box(100, 100, 150, 150)]  # Far away
    params = RFIDCavityParams(min_metal_clearance_mm=8.0)

    res = plan_rfid_embedded_cavity(outer, metal_keepouts=metal, params=params)

    assert res.cavity_poly is not None
    assert res.is_rf_detuning_safe is True
    assert res.min_clearance_to_metal_mm >= 8.0
    d = res.to_dict()
    assert d["is_rf_detuning_safe"] is True


def test_plan_rfid_embedded_cavity_metal_clash():
    """Verify RFID cavity placed <8mm to metal blocks flags detuning risk."""
    outer = box(0, 0, 300, 200)
    # Put metal block right adjacent to RFID default position (cx=25, cy=192)
    metal = [box(20, 185, 30, 195)]
    params = RFIDCavityParams(min_metal_clearance_mm=8.0)

    res = plan_rfid_embedded_cavity(outer, metal_keepouts=metal, params=params)

    assert res.cavity_poly is not None
    assert res.is_rf_detuning_safe is False
    assert res.min_clearance_to_metal_mm < 8.0


def test_drc_rule_72_thermal_sag_support_missing():
    """Verify DRC rule 72 (PCB_THERMAL_SAG_SUPPORT_MISSING)."""
    outer = box(0, 0, 300, 200)
    sink = box(20, 20, 280, 180)  # Span = 260mm >= 160mm
    board = box(21, 21, 279, 179)

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
        require_anti_sag_support=True,
        thermal_sag_support=None,
    )

    issues = run_drc(r1, r2)
    codes = [i["code"] for i in issues]
    assert "PCB_THERMAL_SAG_SUPPORT_MISSING" in codes


def test_drc_rule_73_rfid_metal_detuning():
    """Verify DRC rule 73 (RFID_TAG_METAL_DETUNING_RISK)."""
    outer = box(0, 0, 300, 200)
    sink = box(30, 20, 270, 180)
    board = box(31, 21, 269, 179)

    class MockRFIDDetuned:
        cavity_poly = box(20, 185, 30, 195)
        min_clearance_to_metal_mm = 3.2  # < 8.0mm

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
        rfid_cavity=MockRFIDDetuned(),
    )

    issues = run_drc(r1, r2)
    codes = [i["code"] for i in issues]
    assert "RFID_TAG_METAL_DETUNING_RISK" in codes
