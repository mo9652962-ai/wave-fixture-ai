"""Tests for titanium wear inserts, wave dwell time window, and DRC rules 48-49."""

from types import SimpleNamespace

import ezdxf
from shapely.geometry import box

from drc import run_drc
from fixture_phase2 import Phase2Result
from titanium_inserts import (
    calculate_wave_dwell_window,
    detect_knife_edge_walls_and_inserts,
    export_titanium_inserts_to_dxf,
)


def test_calculate_wave_dwell_window():
    """Verify wave contact dwell time calculation against SMTA / IPC J-STD-001 windows."""
    # Speed: 1.1 m/min = 18.33 mm/s.
    # Opening length = 70mm -> dwell = 70 / 18.33 ≈ 3.82s (in 2.5 ~ 5.5s window)
    win_normal = calculate_wave_dwell_window(pocket_length_x_mm=70.0, conveyor_speed_m_per_min=1.1)
    assert win_normal.is_compliant is True
    assert 3.5 <= win_normal.dwell_time_sec <= 4.2
    assert "COMPLIANT" in win_normal.status_summary

    # Opening length = 20mm -> dwell = 20 / 18.33 ≈ 1.09s (< 2.5s)
    win_short = calculate_wave_dwell_window(pocket_length_x_mm=20.0, conveyor_speed_m_per_min=1.1)
    assert win_short.is_compliant is False
    assert "TOO_SHORT" in win_short.status_summary

    # Opening length = 150mm -> dwell = 150 / 18.33 ≈ 8.18s (> 5.5s)
    win_long = calculate_wave_dwell_window(pocket_length_x_mm=150.0, conveyor_speed_m_per_min=1.1)
    assert win_long.is_compliant is False
    assert "TOO_LONG" in win_long.status_summary


def test_detect_knife_edge_walls_and_inserts():
    """Verify detection of <1.8mm knife-edge dam between solder openings and blade planning."""
    # Two solder pockets separated by 1.2mm (< 1.8mm threshold)
    p1 = box(10, 10, 50, 40)
    p2 = box(10, 41.2, 50, 71.2)  # Distance = 41.2 - 40 = 1.2mm
    res = detect_knife_edge_walls_and_inserts([p1, p2])

    assert res.thin_walls_detected == 1
    assert len(res.blades) == 1
    b = res.blades[0]
    assert b.thickness_mm == 0.8
    assert len(b.screw_holes) >= 2
    assert b.orientation == "horizontal"


def test_export_titanium_inserts_to_dxf():
    """Verify DXF export of titanium blades and M2 fixing holes on layer '钛合金嵌件'."""
    p1 = box(20, 20, 60, 50)
    p2 = box(20, 51.5, 60, 81.5)
    res = detect_knife_edge_walls_and_inserts([p1, p2])

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    export_titanium_inserts_to_dxf(msp, res)

    layers = {entity.dxf.layer for entity in msp}
    assert "钛合金嵌件" in layers
    circles = [e for e in msp if e.dxftype() == "CIRCLE" and e.dxf.layer == "钛合金嵌件"]
    assert len(circles) >= 2


def test_drc_rules_48_and_49():
    """Verify DRC rule 48 (WAVE_DWELL_TIME_OUT_OF_WINDOW) and rule 49 (KNIFE_EDGE_WALL_TITANIUM_INSERT_MISSING)."""
    sink = box(10, 10, 100, 80)
    outer = box(0, 0, 130, 110)
    r1 = SimpleNamespace(board_poly=sink, sink_poly=sink, handles=[], screws=[], pins=[])

    # 1. Trigger Rule 48 (dwell time out of window)
    r2_dwell = Phase2Result(
        avoid_polys=[],
        solder_polys=[],
        cap_holes=[],
        outer_poly=outer,
        sink_poly=sink,
        titanium_inserts=SimpleNamespace(
            thin_walls_detected=0,
            blades=[],
            dwell_window=SimpleNamespace(
                is_compliant=False,
                conveyor_speed_m_per_min=1.1,
                dwell_time_sec=1.2,
                min_compliant_dwell_sec=2.5,
                max_compliant_dwell_sec=5.5,
                status_summary="TOO_SHORT",
            ),
        ),
    )
    r2_dwell.check_dwell_time = True
    issues_48 = run_drc(r1, r2_dwell)
    codes_48 = [i["code"] for i in issues_48]
    assert "WAVE_DWELL_TIME_OUT_OF_WINDOW" in codes_48

    # 2. Trigger Rule 49 (knife-edge wall without titanium inserts)
    r2_knife = Phase2Result(
        avoid_polys=[],
        solder_polys=[],
        cap_holes=[],
        outer_poly=outer,
        sink_poly=sink,
        titanium_inserts=SimpleNamespace(
            thin_walls_detected=2,
            blades=[],
            dwell_window=None,
        ),
    )
    r2_knife.require_titanium_inserts = True
    issues_49 = run_drc(r1, r2_knife)
    codes_49 = [i["code"] for i in issues_49]
    assert "KNIFE_EDGE_WALL_TITANIUM_INSERT_MISSING" in codes_49
