"""排气孔 (AGICORP §4.2) / 过板流向指示 / 五金紧固件清单 测试。

权威标准出处：
- AGICORP Wave Solder Pallet Design Guidelines §4.2: 闭合避位腔排气通孔
- AGICORP §2.1: 治具过板流向箭头 (Conveyor Travel Direction Arrow)
- 治具标准件采购清单 (Hardware / Fasteners BOM): 旋转压扣、沉头螺钉、定位销、弹力压柱、挡锡条
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import ezdxf
from shapely.geometry import box

import drc
from fixture_phase2 import Phase2Params, Phase2Result, export_dxf2, make_outer, make_vent_holes

ROOT = Path(__file__).resolve().parent.parent
CASE = ROOT / "cases" / "case_003_stm32_4layer"


def test_make_vent_holes():
    """闭合深腔（面积 ≥ 50mm²）自动生成 Φ2.0mm (r=1.0) 排气孔。"""
    p = Phase2Params(enable_vent_holes=True, min_vent_cavity_area=50.0, vent_hole_r=1.0)
    avoids = [
        box(10, 10, 30, 30),  # 20×20 = 400mm² > 50mm² -> 生成排气孔
        box(40, 10, 45, 15),  # 5×5 = 25mm² < 50mm² -> 跳过小腔
    ]
    vents = make_vent_holes(avoids, [], p)
    assert len(vents) == 1
    vx, vy, vr = vents[0]
    assert vr == 1.0
    assert 10 <= vx <= 30 and 10 <= vy <= 30


def test_dxf_venting_and_flow_arrow_layers(tmp_path):
    """DXF 导出包含「排气孔」和「工程注记」图层及流向文字。"""
    outer = make_outer(box(0, 0, 80, 60), Phase2Params())
    vents = [(20.0, 20.0, 1.0)]
    r2 = Phase2Result(
        outer_poly=outer.outer_poly,
        vent_holes=vents,
        flow_arrow_lines=outer.flow_arrow_lines,
    )
    dxf_path = tmp_path / "test_layers.dxf"
    export_dxf2(r2, str(dxf_path))

    doc = ezdxf.readfile(str(dxf_path))
    layers = {l.dxf.name for l in doc.layers}
    assert "排气孔" in layers
    assert "工程注记" in layers

    msp = doc.modelspace()
    vent_circles = [e for e in msp if e.dxftype() == "CIRCLE" and e.dxf.layer == "排气孔"]
    assert len(vent_circles) == 1

    arrow_lines = [e for e in msp if e.dxftype() == "LINE" and e.dxf.layer == "工程注记"]
    assert len(arrow_lines) >= 3

    texts = [e for e in msp if e.dxftype() == "TEXT" and e.dxf.layer == "工程注记"]
    assert any("FLOW" in e.dxf.text for e in texts)


def test_drc_unvented_avoid_pocket():
    """面积 > 100mm² 的闭合避位腔若无排气孔，触发 UNVENTED_AVOID_POCKET 告警。"""
    board = box(10, 10, 60, 60)
    sink = board.buffer(0.2)
    big_avoid = [box(20, 20, 40, 40)]  # 400mm² > 100mm²
    r1 = SimpleNamespace(
        board_poly=board,
        sink_poly=sink,
        handles=[],
        screws=[],
        pins=[(15.0, 15.0, 1.5), (45.0, 45.0, 1.5)],
    )
    # 未设排气孔
    r2_no_vent = SimpleNamespace(
        avoid_polys=big_avoid,
        solder_polys=[],
        cap_holes=[],
        outer_poly=box(0, 0, 100, 80),
        rail_lines=[],
        tin_strip_lines=[],
        tin_holes=[],
        sink_poly=sink,
        dogbone_corners=[],
        panel_grid=None,
        vent_holes=[],
    )
    issues1 = drc.run_drc(r1, r2_no_vent)
    codes1 = {i["code"] for i in issues1}
    assert "UNVENTED_AVOID_POCKET" in codes1

    # 设有排气孔位于腔体内 -> 告警消除
    r2_with_vent = SimpleNamespace(
        avoid_polys=big_avoid,
        solder_polys=[],
        cap_holes=[],
        outer_poly=box(0, 0, 100, 80),
        rail_lines=[],
        tin_strip_lines=[],
        tin_holes=[],
        sink_poly=sink,
        dogbone_corners=[],
        panel_grid=None,
        vent_holes=[(30.0, 30.0, 1.0)],
    )
    issues2 = drc.run_drc(r1, r2_with_vent)
    codes2 = {i["code"] for i in issues2}
    assert "UNVENTED_AVOID_POCKET" not in codes2


def test_gcode_drills_vent_holes(tmp_path):
    """G 代码自动将排气孔归入钻孔换刀组。"""
    from cnc_gcode import generate_gcode

    sink = box(0, 0, 60, 40)
    pins = [(5.0, 5.0, 1.5)]  # D3.0mm
    vents = [(20.0, 20.0, 1.0), (30.0, 20.0, 1.0)]  # D2.0mm
    out_nc = tmp_path / "fixture.nc"
    stats = generate_gcode(
        sink,
        [],
        [],
        [],
        pins,
        [],
        box(-20, -20, 80, 60),
        str(out_nc),
        vent_holes=vents,
        parent_hint=tmp_path,
    )
    text = out_nc.read_text(encoding="ascii")
    # 应有 D3.0mm (pins) 与 D2.0mm (vents) 两个不同直径的钻孔工具
    assert any(t["dia_mm"] == 2.0 for t in stats["tools"])
    assert stats["drill_groups"] >= 2
    assert "X20" in text and "X30" in text


def test_fasteners_bom_in_report():
    """生产工单中包含治具五金标准件采购清单 (Hardware BOM)。"""
    from report import build_report

    board = box(0, 0, 50, 50)
    r1 = SimpleNamespace(
        board_poly=board,
        sink_poly=board.buffer(0.2),
        handles=[],
        screws=[(5, 5), (45, 5), (5, 45), (45, 45)],  # 4 压扣
        pins=[(10, 10), (40, 40)],  # 2 定位销
        dogbone_corners=[],
    )
    r2 = SimpleNamespace(
        avoid_polys=[],
        solder_polys=[],
        cap_holes=[(25, 25, 2.45)],  # 1 顶针
        outer_poly=box(-10, -10, 60, 60),
        rail_lines=[],
        tin_strip_lines=[(0, 0, 1, 1), (0, 0, 1, 1)],  # 2 挡锡条
        tin_holes=[],
        sink_poly=board.buffer(0.2),
        dogbone_corners=[],
        panel_grid=None,
        vent_holes=[(20, 20, 1.0)],  # 1 排气孔
    )
    verdict = {
        "allowed": True,
        "counts": {"blocking": 0, "error": 0, "warning": 0, "info": 0},
        "worst": "info",
        "total": 0,
    }
    md = build_report(
        "fastener-test",
        r1,
        r2,
        verdict,
        material={"key": "durostone", "thickness": 10.0},
        weight_kg=0.3,
        cost={"material_cost": 50, "machining_cost": 50, "total": 100, "currency": "CNY"},
    )
    assert "治具标准五金采购与装配清单 (Hardware BOM)" in md
    assert "旋转压扣 (Turn Clamp)" in md and "4 件" in md
    assert "压扣固定沉头螺钉" in md and "4 支" in md
    assert "阶梯定位销 (Guide Pin)" in md and "2 支" in md
    assert "盖板弹力压柱 (Push Plunger)" in md and "1 支" in md
    assert "防溢锡挡锡条 (Solder Dam)" in md and "2 条" in md
    assert "闭合腔排气通孔 (Vent Hole)" in md and "1 个" in md
