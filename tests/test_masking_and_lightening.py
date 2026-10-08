"""边缘金手指遮罩压条 (gold_finger_mask)、减重散热槽 (lightening_pockets) 与 DRC 测试。

对标标准：
- IPC-A-610G §7.1.4: 金手指沾锡报废缺陷防范
- AGICORP Wave Pallet Guidelines §5.0: 金手指遮罩压条与防爬锡隔离
- SMTA Wave Soldering Thermal Profiling: 治具热容平衡与轻量化
"""

from __future__ import annotations

from types import SimpleNamespace

import ezdxf
import pytest
from shapely.geometry import box

import drc
from fixture_phase2 import Phase2Result, export_dxf2
from gold_finger_mask import (
    detect_edge_connectors_and_fingers,
    generate_gold_finger_masks,
)
from lightening_pockets import (
    LighteningPocketResult,
    generate_lightening_pockets,
)


# ── 1. 金手指遮罩测试 ─────────────────────────────────────────────
def test_detect_edge_connectors_and_fingers():
    """从元器件清单中正确识别金手指或边缘插座。"""
    board = box(0, 0, 100, 80)
    comps = [
        {"ref": "J_PCIE", "name": "PCIe_x4_GoldFinger", "x": 50, "y": 2, "w": 30, "h": 4},
        {"ref": "R1", "name": "Resistor", "x": 20, "y": 40, "w": 1.6, "h": 0.8},
    ]
    regs = detect_edge_connectors_and_fingers(board, comps)
    assert len(regs) == 1
    rb = regs[0].bounds
    assert (rb[2] - rb[0]) == pytest.approx(30.0)


def test_generate_gold_finger_masks():
    """生成金手指遮罩外壳与紧固沉孔。"""
    board = box(0, 0, 100, 80)
    regs = [box(35, 0, 65, 4)]
    shields = generate_gold_finger_masks(board, regs, barrier_margin_mm=4.0)
    assert len(shields) == 1
    s = shields[0]
    assert s.name == "GoldFinger_Shield_1"
    assert len(s.screw_holes) == 2
    # 遮罩外包围由于向外扩展 4mm，X 跨度从 30mm 变成 38mm
    mb = s.mask_poly.bounds
    assert (mb[2] - mb[0]) == pytest.approx(38.0, abs=0.1)


def test_export_gold_finger_masks_to_dxf(tmp_path):
    """DXF 导出包含「金手指遮罩」图层。"""
    board = box(0, 0, 80, 60)
    regs = [box(20, 0, 40, 3)]
    shields = generate_gold_finger_masks(board, regs)
    r2 = Phase2Result(
        outer_poly=box(-10, -10, 90, 70),
        gold_shields=shields,
    )
    out_file = tmp_path / "mask_test.dxf"
    export_dxf2(r2, str(out_file))

    doc = ezdxf.readfile(out_file)
    layers = {l.dxf.name for l in doc.layers}
    assert "金手指遮罩" in layers


# ── 2. 减重开槽测试 ───────────────────────────────────────────────
def test_generate_lightening_pockets():
    """在大尺寸治具底面实心区自动生成减重槽并计算减重率。"""
    outer = box(0, 0, 180, 150)  # 27000 mm²
    sink = box(40, 30, 140, 120)  # 沉板区占据中间
    res = generate_lightening_pockets(outer, sink_poly=sink, wall_margin_mm=12.0)
    assert len(res.pockets) >= 1
    assert res.total_pocket_area_mm2 > 500.0
    assert res.lightening_ratio_pct > 5.0
    assert res.weight_reduction_kg > 0.01


def test_export_lightening_pockets_to_dxf(tmp_path):
    """DXF 导出包含「减重槽」图层。"""
    outer = box(0, 0, 120, 100)
    sink = box(30, 20, 90, 80)
    light = generate_lightening_pockets(outer, sink_poly=sink)
    r2 = Phase2Result(
        outer_poly=outer,
        lightening=light,
    )
    out_file = tmp_path / "lightening_test.dxf"
    export_dxf2(r2, str(out_file))

    doc = ezdxf.readfile(out_file)
    layers = {l.dxf.name for l in doc.layers}
    assert "减重槽" in layers


# ── 3. DRC 规则 36 & 37 测试 ───────────────────────────────────────
def test_drc_gold_finger_unprotected():
    """存在板边金手指但未设防护遮罩时触发 GOLD_FINGER_UNPROTECTED 告警。"""
    r1 = SimpleNamespace(
        board_poly=box(0, 0, 80, 60), sink_poly=box(0, 0, 80, 60), handles=[], screws=[], pins=[]
    )
    r2_unprotected = Phase2Result(
        outer_poly=box(-10, -10, 90, 70),
        gold_shields=[],
    )
    r2_unprotected.has_unprotected_gold_fingers = True

    issues = drc.run_drc(r1, r2_unprotected)
    codes = {i["code"] for i in issues}
    assert "GOLD_FINGER_UNPROTECTED" in codes


def test_drc_thermal_mass_imbalance():
    """治具面积大且减重率不足时触发 THERMAL_MASS_IMBALANCE 告警。"""
    large_outer = box(0, 0, 200, 150)  # 30000 mm² >= 25000 mm²
    r1 = SimpleNamespace(
        board_poly=box(0, 0, 100, 80), sink_poly=box(0, 0, 100, 80), handles=[], screws=[], pins=[]
    )
    # 减重率只有 2.0% < 10.0%
    r2_solid = Phase2Result(
        outer_poly=large_outer,
        lightening=LighteningPocketResult(lightening_ratio_pct=2.0),
    )
    issues = drc.run_drc(r1, r2_solid)
    codes = {i["code"] for i in issues}
    assert "THERMAL_MASS_IMBALANCE" in codes
