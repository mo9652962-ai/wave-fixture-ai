"""选择焊喷嘴避障 (selective_wave) 与工程尺寸自动标注 (fixture_dimensioning) 测试。

对标标准：
- ERSA Versaflow 3/45 与 SEHO SelectLine 喷嘴安全间隙指南 (≥3.0mm)
- 机械制图国家标准 GB/T 4458.1 & ISO 129-1 尺寸标注
"""
from __future__ import annotations

from types import SimpleNamespace

import ezdxf
from shapely.geometry import box

import drc
from fixture_dimensioning import (
    export_dimensions_to_dxf,
    generate_fixture_dimensions,
)
from selective_wave import (
    NOZZLE_PROFILES,
    compute_selective_nozzle_toolpath,
    get_nozzle,
    verify_selective_solder_clearance,
)


# ── 1. 选择焊喷嘴避障测试 ─────────────────────────────────────────
def test_nozzle_profiles_loaded():
    """验证包含 ERSA 4mm/6mm, SEHO 8mm 及通用喷嘴。"""
    assert "ersa_4mm" in NOZZLE_PROFILES
    assert "ersa_6mm" in NOZZLE_PROFILES
    assert "seho_8mm" in NOZZLE_PROFILES

    n = get_nozzle("ersa_6mm")
    assert n.inner_dia_mm == 6.0
    assert n.outer_dia_mm == 9.0
    assert n.recommended_clearance_mm >= 3.0


def test_selective_clearance_violation():
    """开孔尺寸过小 (< 喷嘴外径 + 2*间隙) 产生告警。"""
    # 喷嘴外径 9.0mm + 2*3.0mm = 15.0mm 最小开孔
    small_opening = [box(10, 10, 18, 18)]  # 8x8mm < 15mm
    v = verify_selective_solder_clearance(small_opening, [], nozzle_key="ersa_6mm")
    assert len(v) == 1
    assert v[0]["code"] == "SELECTIVE_NOZZLE_COLLISION"
    assert v[0]["current"] == 8.0
    assert v[0]["required"] == 15.0

    # 足够大的开孔 (25x25mm > 15mm)
    big_opening = [box(10, 10, 35, 35)]
    v2 = verify_selective_solder_clearance(big_opening, [], nozzle_key="ersa_6mm")
    assert len(v2) == 0


def test_selective_nozzle_toolpath():
    """计算选择焊焊点移动轨迹。"""
    solders = [box(50, 20, 70, 40), box(10, 20, 30, 40)]
    path = compute_selective_nozzle_toolpath(solders, nozzle_key="ersa_6mm")
    assert len(path) == 2
    # 自动按 X 升序排序
    assert path[0]["x"] < path[1]["x"]
    assert path[0]["dwell_time_s"] > 0


def test_drc_rule_selective_collision():
    """DRC 规则集成：选择焊喷嘴避障间隙不足检查。"""
    small_solder = [box(10, 10, 20, 20)]  # 10x10mm < 15mm (9 + 2*3)
    r1 = SimpleNamespace(
        board_poly=box(0, 0, 100, 80), sink_poly=box(0, 0, 100, 80), handles=[], screws=[], pins=[]
    )
    r2 = SimpleNamespace(
        avoid_polys=[], solder_polys=small_solder, cap_holes=[],
        outer_poly=box(-10, -10, 110, 90), rail_lines=[], tin_strip_lines=[], tin_holes=[],
        sink_poly=box(0, 0, 100, 80), dogbone_corners=[], panel_grid=None, vent_holes=[],
    )
    issues = drc.run_drc(r1, r2)
    codes = {i["code"] for i in issues}
    assert "SELECTIVE_NOZZLE_COLLISION" in codes


# ── 2. 工程尺寸标注测试 ───────────────────────────────────────────
def test_generate_fixture_dimensions():
    """自动生成外形尺寸、沉板尺寸及定位销跨度尺寸。"""
    outer = box(0, 0, 150, 100)
    sink = box(20, 15, 130, 85)
    pins = [(30.0, 25.0, 1.5), (120.0, 75.0, 1.5)]

    dims = generate_fixture_dimensions(outer, sink_poly=sink, pins=pins)
    labels = {d.label for d in dims}
    assert "治具总宽" in labels
    assert "治具总高" in labels
    assert "沉板区长" in labels
    assert "沉板区宽" in labels
    assert "定位销中心距" in labels

    w_dim = next(d for d in dims if d.label == "治具总宽")
    assert w_dim.text_val == "150.0 mm"


def test_export_dimensions_to_dxf(tmp_path):
    """DXF 输出包含尺寸线、界线与标注文字。"""
    outer = box(0, 0, 100, 80)
    dims = generate_fixture_dimensions(outer)

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    export_dimensions_to_dxf(msp, dims, layer="工程尺寸")

    dxf_file = tmp_path / "dim_test.dxf"
    doc.saveas(dxf_file)

    doc_read = ezdxf.readfile(dxf_file)
    msp_read = doc_read.modelspace()
    dim_lines = [e for e in msp_read if e.dxftype() == "LINE" and e.dxf.layer == "工程尺寸"]
    dim_texts = [e for e in msp_read if e.dxftype() == "TEXT" and e.dxf.layer == "工程尺寸"]
    assert len(dim_lines) > 0
    assert len(dim_texts) >= 2
