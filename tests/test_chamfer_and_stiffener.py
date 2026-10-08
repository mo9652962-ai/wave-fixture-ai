"""波峰焊导流斜面 (wave_chamfer)、脱锡槽与大板防下垂加强筋 (stiffener_bar) 测试。

对标标准：
- AGICORP Wave Solder Pallet Design Guidelines (60° 导流斜面 & 跨度 > 250mm 防下垂加强梁)
- SMTA Wave Soldering Defect Prevention Guidelines (开孔深宽比 & 脱锡防桥连短路槽)
"""

from __future__ import annotations

from types import SimpleNamespace

import ezdxf
import pytest
from shapely.geometry import box

import drc
from fixture_phase2 import Phase2Result, export_dxf2
from stiffener_bar import StiffenerBarParams, generate_stiffener_bars
from wave_chamfer import ChamferParams, generate_wave_flow_chamfers


# ── 1. 导流倒角与脱锡槽测试 ───────────────────────────────────────
def test_generate_wave_flow_chamfers():
    """验证 60° 导流倒角外扩边界、刀路及脱锡槽生成。"""
    solders = [box(10, 10, 20, 30)]  # 10x20mm
    p = ChamferParams(
        enabled=True,
        chamfer_angle_deg=60.0,
        chamfer_width_mm=2.0,
        enable_solder_thief=True,
        conveyor_flow_direction="X+",
    )
    chamfers = generate_wave_flow_chamfers(
        solders, pallet_thickness_mm=10.0, board_pocket_depth_mm=2.0, params=p
    )
    assert len(chamfers) == 1
    ch = chamfers[0]
    # 外扩 2mm 后的边界 bounds 应从 (10,10,20,30) 变为 (8,8,22,32)
    cb = ch.chamfer_poly.bounds
    assert cb[0] == pytest.approx(8.0, abs=0.1)
    assert cb[2] == pytest.approx(22.0, abs=0.1)

    # 包含刀心刀路线段
    assert len(ch.chamfer_toolpath_lines) >= 4
    # 包含右侧脱锡槽折线
    assert len(ch.solder_thief_lines) == 2
    assert ch.solder_thief_lines[0][0][0] == 20.0  # 起自右侧脱锡边


def test_export_chamfer_to_dxf(tmp_path):
    """DXF 导出包含「导流倒角」图层及虚线引流槽。"""
    solders = [box(10, 10, 30, 30)]
    chamfers = generate_wave_flow_chamfers(solders)
    r2 = Phase2Result(
        outer_poly=box(0, 0, 50, 50),
        solder_polys=solders,
        chamfers=chamfers,
    )
    out_file = tmp_path / "chamfer_test.dxf"
    export_dxf2(r2, str(out_file))

    doc = ezdxf.readfile(out_file)
    layers = {l.dxf.name for l in doc.layers}
    assert "导流倒角" in layers
    msp = doc.modelspace()
    chamfer_entities = [e for e in msp if e.dxf.layer == "导流倒角"]
    assert len(chamfer_entities) > 0


# ── 2. 防下垂加强梁测试 ───────────────────────────────────────────
def test_stiffener_bar_generation_on_large_pallet():
    """跨距 ≥ 250mm 时自动生成中支撑加强梁与 M4 紧固沉孔。"""
    large_outer = box(0, 0, 320, 180)  # 跨距 320mm > 250mm
    p = StiffenerBarParams(enabled=True, span_threshold_mm=250.0, bar_width_mm=12.0)
    res = generate_stiffener_bars(large_outer, params=p)
    assert res.needed is True
    assert res.max_span_mm == 320.0
    assert len(res.bar_polys) == 1
    # 螺丝沉孔 2 颗
    assert len(res.screw_holes) == 2
    # 检查螺丝位于东西中线 160mm 处
    assert res.screw_holes[0][0] == pytest.approx(160.0, abs=0.1)
    assert res.screw_holes[0][2] == pytest.approx(2.1, abs=0.1)  # M4 半径 2.1mm


def test_stiffener_bar_not_needed_for_small_pallet():
    """小尺寸治具跨距 < 250mm 不生成加强梁。"""
    small_outer = box(0, 0, 140, 100)
    res = generate_stiffener_bars(small_outer)
    assert res.needed is False
    assert len(res.bar_polys) == 0


def test_export_stiffener_to_dxf(tmp_path):
    """DXF 导出包含「加强筋」图层。"""
    large_outer = box(0, 0, 300, 200)
    stiff = generate_stiffener_bars(large_outer)
    r2 = Phase2Result(
        outer_poly=large_outer,
        stiffener=stiff,
    )
    out_file = tmp_path / "stiffener_test.dxf"
    export_dxf2(r2, str(out_file))

    doc = ezdxf.readfile(out_file)
    layers = {l.dxf.name for l in doc.layers}
    assert "加强筋" in layers


# ── 3. DRC 规则 34 & 35 测试 ───────────────────────────────────────
def test_drc_sag_deflection_risk():
    """治具跨距 ≥ 250mm 且无加强筋时触发 FIXTURE_SAG_DEFLECTION_RISK。"""
    large_outer = box(0, 0, 300, 150)
    r1 = SimpleNamespace(
        board_poly=box(10, 10, 200, 100),
        sink_poly=box(10, 10, 200, 100),
        handles=[],
        screws=[],
        pins=[],
    )
    r2_unsupported = Phase2Result(
        outer_poly=large_outer,
        stiffener=None,  # 未配置加强筋
    )
    issues = drc.run_drc(r1, r2_unsupported)
    codes = {i["code"] for i in issues}
    assert "FIXTURE_SAG_DEFLECTION_RISK" in codes

    # 配置加强筋后告警消除
    r2_supported = Phase2Result(
        outer_poly=large_outer,
        stiffener=generate_stiffener_bars(large_outer),
    )
    issues2 = drc.run_drc(r1, r2_supported)
    codes2 = {i["code"] for i in issues2}
    assert "FIXTURE_SAG_DEFLECTION_RISK" not in codes2


def test_drc_solder_aspect_ratio_warning():
    """开孔深宽比 > 1.2 触发 SOLDER_OPENING_ASPECT_RATIO。"""
    # 治具厚度 10mm - 2.1mm = 7.9mm 深度
    # 开孔 5x10mm，最小跨度 5mm -> 深宽比 7.9 / 5.0 = 1.58 > 1.2
    narrow_solder = [box(20, 20, 25, 30)]
    r1 = SimpleNamespace(
        board_poly=box(0, 0, 80, 80), sink_poly=box(0, 0, 80, 80), handles=[], screws=[], pins=[]
    )
    r2 = Phase2Result(
        outer_poly=box(-10, -10, 90, 90),
        solder_polys=narrow_solder,
    )
    issues = drc.run_drc(r1, r2, pallet_thickness=10.0)
    codes = {i["code"] for i in issues}
    assert "SOLDER_OPENING_ASPECT_RATIO" in codes
