"""波峰焊热电偶测温孔通道 (thermal_profile) 与 DRC 规则 40/41 测试。

对标标准：
- SMTA Wave Soldering Thermal Profiling Guidelines & KIC Standards (Φ2.5mm 热电偶测温孔道与引线槽)
- IPC-SMEMA-9851 自动化导轨传感器感应切角
"""

from __future__ import annotations

from types import SimpleNamespace

import ezdxf
import pytest
from shapely.geometry import box

import drc
from fixture_phase2 import Phase2Result, export_dxf2
from thermal_profile import (
    ThermalProfileResult,
    generate_thermocouple_channels,
)


def test_generate_thermocouple_channels():
    """验证从上锡区自动布置热电偶测温孔与引出线槽。"""
    solders = [box(20, 20, 30, 30), box(50, 40, 60, 50)]
    outer = box(0, 0, 100, 80)
    res = generate_thermocouple_channels(solders, outer, channel_width_mm=2.5, tc_hole_dia_mm=2.5)

    assert len(res.tc_holes) == 2
    assert len(res.wire_channel_lines) == 2
    assert len(res.sensor_notches) == 2
    assert len(res.channels) == 2

    # 验证孔径 Φ2.5mm -> 半径 1.25mm
    assert res.tc_holes[0][2] == pytest.approx(1.25)
    # 验证走线槽引线延伸至外沿附近
    exit_x = res.channels[0].fixture_edge_exit[0]
    assert exit_x == pytest.approx(4.0) or exit_x == pytest.approx(96.0)


def test_export_thermal_profile_to_dxf(tmp_path):
    """DXF 导出包含「测温孔」图层。"""
    solders = [box(20, 20, 35, 35)]
    outer = box(0, 0, 100, 80)
    tp_res = generate_thermocouple_channels(solders, outer)

    r2 = Phase2Result(
        outer_poly=outer,
        thermal_profile=tp_res,
    )
    out_file = tmp_path / "thermal_test.dxf"
    export_dxf2(r2, str(out_file))

    doc = ezdxf.readfile(out_file)
    layers = {l.dxf.name for l in doc.layers}
    assert "测温孔" in layers
    msp = doc.modelspace()
    circles = [e for e in msp if e.dxf.layer == "测温孔" and e.dxftype() == "CIRCLE"]
    assert len(circles) >= 1


def test_drc_thermal_profile_missing_alert():
    """中大尺寸治具且上锡区密集时，若未规划测温孔触发 THERMAL_PROFILE_CHANNELS_MISSING。"""
    large_outer = box(0, 0, 160, 130)  # 20800 mm² >= 20000 mm²
    solders = [box(20, 20, 30, 30), box(40, 40, 50, 50), box(60, 60, 70, 70)]  # 3 处上锡区
    r1 = SimpleNamespace(
        board_poly=box(10, 10, 80, 80),
        sink_poly=box(10, 10, 80, 80),
        handles=[],
        screws=[],
        pins=[],
    )

    # 未规划测温通道
    r2_no_tc = Phase2Result(
        outer_poly=large_outer,
        solder_polys=solders,
        thermal_profile=None,
    )
    issues = drc.run_drc(r1, r2_no_tc)
    codes = {i["code"] for i in issues}
    assert "THERMAL_PROFILE_CHANNELS_MISSING" in codes

    # 规划测温孔后告警消除
    r2_with_tc = Phase2Result(
        outer_poly=large_outer,
        solder_polys=solders,
        thermal_profile=generate_thermocouple_channels(solders, large_outer),
    )
    issues2 = drc.run_drc(r1, r2_with_tc)
    codes2 = {i["code"] for i in issues2}
    assert "THERMAL_PROFILE_CHANNELS_MISSING" not in codes2


def test_drc_pallet_conveyor_sensor_notch():
    """自动化进板要求 SMEMA 切角但未设时触发 PALLET_CONVEYOR_SENSOR_NOTCH。"""
    outer = box(0, 0, 100, 80)
    r1 = SimpleNamespace(
        board_poly=box(0, 0, 80, 60), sink_poly=box(0, 0, 80, 60), handles=[], screws=[], pins=[]
    )
    r2 = Phase2Result(
        outer_poly=outer,
        thermal_profile=ThermalProfileResult(sensor_notches=[]),
    )
    r2.require_smema_notch = True
    issues = drc.run_drc(r1, r2)
    codes = {i["code"] for i in issues}
    assert "PALLET_CONVEYOR_SENSOR_NOTCH" in codes
