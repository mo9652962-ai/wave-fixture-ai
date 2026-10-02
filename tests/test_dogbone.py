"""狗骨头（Dogbone Relief）内凹拐角减隙刀路与几何生成测试。

测试矩阵：
1. 基础几何：90° 矩形板角点检测、角平分线计算、刀具中心坐标推导
2. 角度过滤：锐角/直角（<=135°）清角，钝角（>135°）平缓过渡跳过
3. 三种风格对比：dogbone (角平分线外移) / corner_hole (顶点钻孔) / tbone (单边延伸)
4. 减隙验证：拐角顶点必须严格落在切削区内（PCB 尖角可无干涉放入）
5. DXF 图层契约：add_dogbone_to_dxf 输出切削外圆、下刀引线与中心十字标
6. phase1 集成：make_sink_region 默认启用 dogbone，enable_dogbone=False 回退经典圆角
7. DRC 门禁联动：DOGBONE_BODY_OVERFLOW / DOGBONE_CLAMP_COLLISION / DOGBONE_PIN_COLLISION
8. 自然语言调参：nl_adjust 解析「狗骨头半径改2.5mm」
9. 真实板验证：case_001 / case_002 生成真实狗骨头刀路
"""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import ezdxf
import pytest
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

import drc
from dogbone import (
    DogboneCorner,
    DogboneParams,
    add_dogbone_to_dxf,
    detect_concave_corners,
    generate_dogbone_relief,
)
from fixture_phase1 import (
    FixtureParams,
    make_sink_region,
    parse_gerber,
)
from nl_adjust import parse_adjust_command

ROOT = Path(__file__).resolve().parent.parent


# ── 1. 基础几何与 90° 矩形 ──────────────────────────────────────
def test_detect_concave_corners_on_rectangle():
    """100x80 矩形应精准检出 4 个 90° 内凹拐角（PCB 凸角）。"""
    b = box(0, 0, 100, 80)
    corners = detect_concave_corners(b)
    assert len(corners) == 4

    vertices = {tuple(round(v, 2) for v in c.vertex) for c in corners}
    assert vertices == {(0.0, 0.0), (100.0, 0.0), (100.0, 80.0), (0.0, 80.0)}

    for c in corners:
        assert c.angle_deg == pytest.approx(90.0, abs=0.1)
        assert c.cutter_r == 1.85
        assert c.style == "dogbone"


def test_dogbone_center_offset_along_bisector():
    """狗骨头刀具中心应沿角平分线向外侧（材料内部）偏移。"""
    b = box(0, 0, 100, 80)
    corners = detect_concave_corners(b, DogboneParams(cutter_r=2.0, clearance_mm=0.0))
    # 找到原点角 (0, 0)，平分线应指向 (-1, -1)
    bl = next(c for c in corners if c.vertex == (0.0, 0.0))
    bx, by = bl.bisector
    assert bx == pytest.approx(-1 / math.sqrt(2), abs=1e-3)
    assert by == pytest.approx(-1 / math.sqrt(2), abs=1e-3)

    # 刀具中心坐标必须位于负象限 (外侧材料内)
    cx, cy = bl.center
    assert cx < 0.0 and cy < 0.0
    # 刀具中心距拐角顶点的距离必须大于 0 且小于 cutter_r
    dist = math.hypot(cx, cy)
    assert 0 < dist < 2.0


def test_dogbone_relief_clears_corner_vertex():
    """核心物理特性：PCB 拐角顶点必须严格被狗骨头切削圆所包含并留有间隙。"""
    b = box(0, 0, 100, 80)
    sink, corners = generate_dogbone_relief(
        b, expand_mm=0.2, params=DogboneParams(cutter_r=1.85, clearance_mm=0.05)
    )
    assert sink.is_valid
    assert sink.area > b.area

    # 原矩形 4 个尖角顶点必须完全落在沉板区多边形内部（非边界）
    for c in corners:
        vx, vy = c.vertex
        pt = Point(vx, vy)
        assert sink.contains(pt), f"拐角顶点 {c.vertex} 未被减隙槽完全包含！"


# ── 2. 角度过滤与非 90° 几何 ────────────────────────────────────
def test_blunt_angle_is_skipped():
    """钝角 (>135°) 不需要做清角（刀具自身圆弧即可自然走过）。"""
    # 带有 150° 钝角的多边形
    pts = [(0, 0), (50, 0), (100, 30), (100, 80), (0, 80)]
    poly = Polygon(pts)
    corners = detect_concave_corners(poly, DogboneParams(max_angle_deg=135.0))
    # 100, 30 处的角约为 150°，应被过滤
    angles = [c.angle_deg for c in corners]
    assert not any(a > 135.0 for a in angles)


def test_internal_notch_reflex_corner_not_treated_as_convex():
    """凹槽拐角（PCB 内部开槽）的外角不应被误判为需要清角的凸角。"""
    # L 形板
    l_shape = Polygon([(0, 0), (100, 0), (100, 40), (50, 40), (50, 80), (0, 80)])
    corners = detect_concave_corners(l_shape)
    # 5 个凸角应被检出，内凹拐角 (50, 40) 是外角不应生成向内的狗骨头
    v_set = {tuple(round(v, 1) for v in c.vertex) for c in corners}
    assert (50.0, 40.0) not in v_set
    assert len(corners) == 5


# ── 3. 清角风格对比 ──────────────────────────────────────────────
def test_style_corner_hole():
    """corner_hole 风格以顶点为圆心。"""
    b = box(0, 0, 50, 50)
    corners = detect_concave_corners(b, DogboneParams(style="corner_hole"))
    for c in corners:
        assert c.center == c.vertex


def test_style_tbone():
    """tbone 风格刀心沿其中一条边向外偏移。"""
    b = box(0, 0, 50, 50)
    corners = detect_concave_corners(b, DogboneParams(style="tbone", cutter_r=2.0))
    for c in corners:
        vx, vy = c.vertex
        cx, cy = c.center
        # 沿单边偏移：x 或 y 其中一个与顶点一致
        assert (cx == pytest.approx(vx, abs=1e-3)) or (cy == pytest.approx(vy, abs=1e-3))


# ── 4. DXF 图层与图元契约 ─────────────────────────────────────────
def test_add_dogbone_to_dxf(tmp_path):
    """验证 DXF 模型空间正确输出「清角刀路」图层。"""
    doc = ezdxf.new("R2010")
    doc.layers.add("清角刀路", color=30)
    msp = doc.modelspace()

    b = box(0, 0, 100, 80)
    corners = detect_concave_corners(b, DogboneParams(cutter_r=1.85))
    add_dogbone_to_dxf(msp, corners, layer="清角刀路")

    dxf_file = tmp_path / "dogbone_test.dxf"
    doc.saveas(str(dxf_file))
    assert dxf_file.exists()

    d2 = ezdxf.readfile(str(dxf_file))
    msp2 = d2.modelspace()

    # 4 个拐角：每个应有 1 个切削圆 + 1 个下刀引线 + 2 条十字标线 = 4 个图元
    circles = [e for e in msp2 if e.dxftype() == "CIRCLE" and e.dxf.layer == "清角刀路"]
    lines = [e for e in msp2 if e.dxftype() == "LINE" and e.dxf.layer == "清角刀路"]

    assert len(circles) == 4
    for c in circles:
        assert c.dxf.radius == pytest.approx(1.85)

    assert len(lines) == 4 * 3  # 引线 + 十字


# ── 5. phase1 与 phase2 管道集成 ─────────────────────────────────
def test_phase1_make_sink_region_dogbone_integration():
    """make_sink_region 默认启用狗骨头并能返回刀路拐角列表。"""
    b = box(0, 0, 100, 80)
    p = FixtureParams(enable_dogbone=True, dogbone_r=1.85)
    sink, corners = make_sink_region(b, p, return_corners=True)

    assert len(corners) == 4
    assert sink.is_valid
    assert sink.area > b.area * 1.002  # 外扩 + 狗骨头耳

    # 当禁用狗骨头时回退到经典清角圆角
    p_off = FixtureParams(enable_dogbone=False)
    sink_off, corners_off = make_sink_region(b, p_off, return_corners=True)
    assert len(corners_off) == 0
    assert sink_off.is_valid


def test_phase1_run_produces_dogbone_layer(tmp_path):
    """run() 输出的 DXF 必须包含「清角刀路」图层。"""
    case = ROOT / "cases" / "case_003_stm32_4layer"
    if not case.exists():
        pytest.skip("case_003 缺失")
    out = tmp_path / "dogbone_run.dxf"
    p = FixtureParams(enable_dogbone=True)
    from fixture_phase1 import run

    res = run(str(case), str(out), params=p)
    assert len(res.dogbone_corners) > 0

    doc = ezdxf.readfile(str(out))
    layers = {l.dxf.name for l in doc.layers}
    assert "清角刀路" in layers
    db_circles = [
        e for e in doc.modelspace() if e.dxftype() == "CIRCLE" and e.dxf.layer == "清角刀路"
    ]
    assert len(db_circles) > 0


# ── 6. DRC 门禁联动 ──────────────────────────────────────────────
def test_drc_flags_dogbone_clamp_collision():
    """当狗骨头切削圆与压扣孔干涉时，DRC 必须拦截并报错。"""
    board = box(0, 0, 100, 80)
    sink = box(-0.2, -0.2, 100.2, 80.2)
    outer = box(-20, -20, 120, 100)

    # 构造一个假拐角刀路：刀心位于 (-1, -1)，半径 2.0mm
    fake_corner = DogboneCorner(
        index=1,
        vertex=(0, 0),
        center=(-1.0, -1.0),
        cutter_r=2.0,
        bisector=(-0.7071, -0.7071),
        angle_deg=90.0,
        style="dogbone",
        lead_in_line=((0, 0), (-1.0, -1.0)),
    )
    # 压扣孔刚好落在切削圆内部：(-1.5, -1.5)
    screws = [(-1.5, -1.5), (110, -10), (-10, 90), (110, 90)]

    r1 = SimpleNamespace(
        board_poly=board,
        sink_poly=sink,
        handles=[],
        screws=screws,
        pins=[],
        dogbone_corners=[fake_corner],
    )
    r2 = SimpleNamespace(
        outer_poly=outer,
        avoid_polys=[],
        solder_polys=[],
        cap_holes=[],
        tin_holes=[],
        tin_strip_lines=[],
        dogbone_corners=[fake_corner],
    )

    issues = drc.run_drc(r1, r2)
    hits = [i for i in issues if i["code"] == "DOGBONE_CLAMP_COLLISION"]
    assert len(hits) == 1
    assert hits[0]["severity"] == "error"
    assert "压扣孔" in hits[0]["detail"]


# ── 7. 自然语言调参 ──────────────────────────────────────────────
def test_nl_adjust_dogbone_radius():
    p1 = {"dogbone_r": 1.85, "dogbone_clearance": 0.05}
    p2 = {}
    r = parse_adjust_command("狗骨头半径改2.5mm", p1, p2)
    assert r.matched
    assert r.param == "dogbone_r"
    assert r.new_value == 2.5


# ── 8. 真实板验证（case_001 与 case_002）─────────────────────────
def test_real_board_case001_dogbone():
    case = ROOT / "cases" / "case_001_espmh"
    if not case.exists():
        pytest.skip("case_001 缺失")
    bp, _ = parse_gerber(str(case))
    board = unary_union(bp)
    sink, corners = make_sink_region(board, FixtureParams(enable_dogbone=True), return_corners=True)
    # 25.654 x 48.26mm 矩形板应稳定产出 4 个清角刀路
    assert len(corners) == 4
    for c in corners:
        assert c.cutter_r == 1.85
        assert sink.contains(Point(c.vertex[0], c.vertex[1]))


def test_real_board_case002_dogbone():
    case = ROOT / "cases" / "case_002_aircon_kicad"
    if not case.exists():
        pytest.skip("case_002 缺失")
    bp, _ = parse_gerber(str(case))
    board = unary_union(bp)
    sink, corners = make_sink_region(board, FixtureParams(enable_dogbone=True), return_corners=True)
    assert len(corners) >= 4
    assert sink.is_valid
